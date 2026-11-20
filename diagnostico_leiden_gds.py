"""Diagnóstico global Leiden com etapas explícitas e recuperação de projeção ausente."""
from pathlib import Path
from datetime import datetime, timezone
import json, tempfile, shutil, zipfile, traceback, uuid
import pandas as pd
from revisao_pendencias import load, read, connectivity, write_json, csv, sha

VERSION='2.0.0'
SCHEMA='mo438-leiden-gds-diagnostic-2'
SAFE_VALIDATIONS={
 'Edições incompatíveis.','Recibo GDS alterado.',
 'Projeção ausente ou ambígua no catálogo GDS.',
 'Banco ou contagens diferentes da projeção esperada.',
 'Nós projetados incompatíveis com a edição.',
 'Topologia projetada diferente da entrada.',
 'Multiplicidade ou propriedade projetada diferente da entrada.',
 'Valor projetado inválido.',
 'Configure NEO4J_URI, NEO4J_USER (ou NEO4J_USERNAME) e NEO4J_PASSWORD no .env local.',
 'NEO4J_URI inválida; mantenha usuário e senha em variáveis separadas.',
 'Partição com identificador inválido.',
 'A partição deve atribuir exatamente uma comunidade a todos os nós.',
 'Projeção e partição têm universos diferentes.',
}

def _operations():
    from neo4j_integracao import _configuration
    from redes_projecoes import verificar_projecao, valores_esperados, query_projecao
    from redes_comunidades import executar_algoritmo,canonizar_particao,comparar_particoes
    return dict(configuration=_configuration,verify=verificar_projecao,expected=valores_esperados,
                project_query=query_projecao,run=executar_algoritmo,canonical=canonizar_particao,
                compare=comparar_particoes)

def _query(session,statement,**parameters):
    return session.execute_read(lambda tx:[r.data() for r in tx.run(statement,**parameters)])

def _safe_error(exc,stage):
    message=str(exc)
    reason=message if isinstance(exc,ValueError) and message in SAFE_VALIDATIONS else 'Mensagem externa omitida; consulte a etapa e a pilha reduzida.'
    if isinstance(exc,FileNotFoundError):reason='Arquivo local necessário ausente; conferir as entradas desta etapa.'
    code=getattr(exc,'code',None)
    import re
    if not isinstance(code,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,160}',code):code=None
    return {'stage':stage,'error_type':type(exc).__name__,'safe_reason':reason,'neo4j_code':code,
            'stack':[{'module':Path(x.filename).name,'function':x.name,'line':x.lineno}
                     for x in traceback.extract_tb(exc.__traceback__)[-8:]]}

def _package(folder,path):
    temporary=path.with_suffix('.tmp')
    try:
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
            for p in sorted(folder.iterdir()):
                if p.is_file():archive.write(p,p.name)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:raise ValueError('ZIP de diagnóstico inválido.')
        temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)

def diagnosticar_global(projeto,*,executar_gds=False,recriar_projecao_ausente=True,driver_factory=None):
    """Não escreve no banco nem substitui partições. Pode criar uma projeção temporária."""
    root=Path(projeto).resolve();receipts={};checks={}
    if root.name=='PROJECT_EXTRACAO':raise ValueError('Use PROJECT, não a pasta de extração.')
    comm,cm=load(root,'resultados/comunidades',receipts)
    projection,pm=load(root,'dados/processados/redes/projecoes',receipts)
    if cm['projection_snapshot_sha256']!=pm['snapshot_sha256']:raise ValueError('Edições incompatíveis.')
    if not executar_gds:
        return {'mode':'DRY_RUN','version':VERSION,'neo4j_connections':0,'database_writes':0,
                'partitions_modified':False,'files_written':0,
                'recreate_missing_projection_temporarily':bool(recriar_projecao_ausente)}
    base=root/'resultados/revisao_pendencias/diagnostico_gds';base.mkdir(parents=True,exist_ok=True)
    lock=base/'execucao.lock'
    try:lock.mkdir()
    except FileExistsError:raise RuntimeError('Outro diagnóstico GDS pode estar em execução.') from None
    staging=Path(tempfile.mkdtemp(prefix='.diagnostico_',dir=base))
    driver=None;temporary_graph=None;database=None;stage='CARREGAR_OPERACOES';results=[];cleanup={}
    report={'schema':SCHEMA,'version':VERSION,'inputs':receipts,'runs':results,'database_writes':0,
            'gds_graphs_created':0,'gds_graphs_removed':0,'partitions_modified':False,'api_calls':0,
            'started_at_utc':datetime.now(timezone.utc).isoformat()}
    def progress(value):
        nonlocal stage
        stage=value;print('[DIAGNÓSTICO GDS] Etapa:',value,flush=True)
    def drop_temporary():
        nonlocal temporary_graph
        if temporary_graph is None:return
        graph=temporary_graph
        try:
            with driver.session(database=database) as session:
                session.run('CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName',name=graph).consume()
            cleanup['temporary_graph_removed']=True;report['gds_graphs_removed']+=1;temporary_graph=None
        except Exception as exc:
            cleanup['temporary_graph_removed']=False;cleanup['cleanup_error']=_safe_error(exc,'REMOVER_PROJECAO_TEMPORARIA')
            # Retain name so it can be removed explicitly in a later diagnostic.
            cleanup['temporary_graph_name']=graph
        report['cleanup']=cleanup
    try:
        ops=_operations()
        progress('VALIDAR_ARQUIVOS_LOCAIS')
        saved=read(comm,cm,'particoes_nos.csv.gz',checks)
        pairs=read(projection,pm,'ponderada_nao_dirigida.csv.gz',checks)
        saved44=saved[saved.run_id=='leiden_seed_44'].sort_values('entity_group_id')
        if saved44.empty:raise ValueError('A partição de referência Leiden 44 está ausente.')
        nodes=saved44.drop(columns=['run_id','community_id','raw_community_id','internal_piece_id'])
        if sha(comm/'execucoes_gds.json')!=cm['outputs_sha256']['execucoes_gds.json']:raise ValueError('Recibo GDS alterado.')
        execution=json.loads((comm/'execucoes_gds.json').read_text(encoding='utf-8'))
        baseline=execution['leiden_seed_44']['config'];original_graph=pm['graph_names']['community']
        report['saved_gds_version']=execution['leiden_seed_44']['gds_version']
        cases=[('seed44_original',dict(baseline)),('seed44_sem_consecutiveIds',{**baseline,'consecutiveIds':False}),
               ('seed44_mais_niveis',{**baseline,'maxLevels':30}),
               ('seed44_tolerancia_menor',{**baseline,'maxLevels':30,'tolerance':1e-7})]
        progress('CONFIGURAR_NEO4J')
        uri,user,password,database=ops['configuration'](root)
        if driver_factory is None:
            from neo4j import GraphDatabase
            driver_factory=GraphDatabase.driver
        progress('CONECTAR_NEO4J')
        driver=driver_factory(uri,auth=(user,password));driver.verify_connectivity()
        with driver.session(database=database) as session:
            progress('INSPECIONAR_CATALOGO_GDS')
            report['current_gds_version']=_query(session,'RETURN gds.version() AS version')[0]['version']
            exists=_query(session,'CALL gds.graph.exists($name) YIELD exists RETURN exists',name=original_graph)[0]['exists']
            report['original_projection_exists']=bool(exists);graph=original_graph
            if not exists:
                if not recriar_projecao_ausente:
                    raise ValueError('Projeção ausente ou ambígua no catálogo GDS.')
                progress('CRIAR_PROJECAO_TEMPORARIA')
                graph=original_graph+'_diagnostico_'+uuid.uuid4().hex[:8]
                # Mark ownership before calling the procedure: cleanup also covers an uncertain response.
                temporary_graph=graph
                session.run(ops['project_query']('community'),tag='newsai_'+cm['network_snapshot_sha256'][:20],name=graph).consume()
                report['gds_graphs_created']=1
                print('[DIAGNÓSTICO GDS] Projeção original ausente; criada somente a projeção temporária deste diagnóstico.',flush=True)
            progress('VALIDAR_PROJECAO_COMPLETA')
            report['projection_all_edges_and_nodes_verified']=ops['verify'](session,graph,database,
                'newsai_'+cm['network_snapshot_sha256'][:20],set(map(int,nodes.entity_group_id)),
                ops['expected']('community',None,pairs))
            # No fallback on a mismatch: an existing invalid projection must not be silently replaced.
            for label,config in cases:
                progress('EXECUTAR_'+label)
                raw,receipt=ops['run'](session,graph,'leiden',config)
                progress('AVALIAR_'+label)
                partition=ops['canonical'](raw,nodes.entity_group_id)
                f,s=connectivity(nodes.merge(partition,on='entity_group_id',validate='one_to_one'),pairs)
                overlap=ops['compare'](saved44.community_id.tolist(),f.community_id.tolist())
                csv(staging/(label+'.csv.gz'),f)
                results.append({'case':label,'configuration':config,'execution':receipt,'connectivity':s,'comparison_to_saved_seed44':overlap})
                write_json(staging/'progresso.json',{'completed_runs':results})
                print('[DIAGNÓSTICO GDS]',label,'comunidades desconexas:',s['disconnected_communities'],flush=True)
        progress('REMOVER_PROJECAO_TEMPORARIA');drop_temporary()
        if cleanup.get('temporary_graph_removed') is False:
            raise ValueError('Não foi possível remover a projeção temporária; consulte o relatório de limpeza.')
        progress('EMPACOTAR_RESULTADOS')
        report.update(status='COMPLETE',input_files_sha256=checks,
                      note='Experimentos de diagnóstico; nenhuma nova partição é adotada automaticamente.')
        write_json(staging/'diagnostico.json',report)
        write_json(staging/'manifesto.json',{'schema':SCHEMA,'version':VERSION,'inputs':receipts,
                    'outputs_sha256':{p.name:sha(p) for p in staging.iterdir()}})
        package=base/'Resumo_Diagnostico_Leiden_GDS.zip';_package(staging,package)
        for name in ['Resumo_Diagnostico_Leiden_GDS_Falha.zip','Falha_Diagnostico_Leiden_GDS.json']:(base/name).unlink(missing_ok=True)
        print('[DIAGNÓSTICO GDS] Pacote:',package,flush=True)
        return {'status':'COMPLETE','package':str(package),'runs':len(results),'database_writes':0,
                'partitions_modified':False,'gds_graphs_created':report['gds_graphs_created'],
                'gds_graphs_removed':report['gds_graphs_removed']}
    except Exception as exc:
        error=_safe_error(exc,stage);drop_temporary();report.update(status='FAILED',error=error)
        write_json(staging/'diagnostico_falha.json',report)
        write_json(base/'Falha_Diagnostico_Leiden_GDS.json',report)
        package=base/'Resumo_Diagnostico_Leiden_GDS_Falha.zip';_package(staging,package)
        print('[DIAGNÓSTICO GDS] Pacote de falha:',package,flush=True)
        message='Diagnóstico interrompido em '+stage+': '+error['safe_reason']+' ['+error['error_type']+']'
        raise RuntimeError(message+'\nPacote de diagnóstico: '+str(package)) from None
    finally:
        if driver is not None:
            try:driver.close()
            except Exception:pass
        shutil.rmtree(staging,ignore_errors=True);lock.rmdir()
