"""Comunidades ponderadas por fonte, estabilidade e comparação no universo comum."""
from pathlib import Path
from datetime import datetime, timezone
from itertools import combinations
from collections import Counter
import json
import shutil
import tempfile
import uuid
import zipfile
import pandas as pd
from fontes_estrutural import carregar_fontes, query
from fontes_centralidades import carregar_estrutura_fontes
from redes_fontes import FONTES
from redes_comunidades import configuracoes, canonizar_particao, avaliar_particao, executar_algoritmo, tabela_comparacoes, comparar_particoes, gerar_figuras
from redes_projecoes import verificar_projecao, valores_esperados, EXISTS
from re_consolidacao import sha, json_sha, write_csv, validate_manifest
from re_execucao import atomic_json
from neo4j_integracao import _configuration, _failure

VERSION = '1.0.0'
PROJETAR = '''UNWIND $rows AS row
MATCH (source:NewsAIEntity {graph_tag:$tag, entity_group_id:row.source_id})
MATCH (target:NewsAIEntity {graph_tag:$tag, entity_group_id:row.target_id})
WITH gds.graph.project($name, source, target,
 {sourceNodeProperties:{entity_group_id:source.entity_group_id},
  targetNodeProperties:{entity_group_id:target.entity_group_id},
  relationshipType:'SOURCE_COMMUNITY',
  relationshipProperties:{weight:toFloat(row.weight),distance:1.0/toFloat(row.weight)}},
 {readConcurrency:1,undirectedRelationshipTypes:['SOURCE_COMMUNITY']}) AS g
RETURN g.graphName AS graphName, g.nodeCount AS nodeCount, g.relationshipCount AS relationshipCount'''


def carregar_protagonismo(root, meta, estrutural):
    base = root/'resultados/comparacao_fontes/centralidades'
    pointer = json.loads((base/'atual.json').read_text(encoding='utf-8'))
    if Path(pointer['folder']).name != pointer['folder']: raise ValueError('Apontador de protagonismo inválido.')
    folder = base/pointer['folder']; cm = validate_manifest(folder)
    if cm['schema'] != 'source-entity-centralities-1' or cm['snapshot_sha256'] != pointer['snapshot_sha256']:
        raise ValueError('Edição de protagonismo incompatível.')
    if cm['source_networks_snapshot_sha256'] != meta['snapshot_sha256'] or cm['structural_snapshot_sha256'] != estrutural['snapshot_sha256']:
        raise ValueError('Protagonismo, estrutura e fontes pertencem a edições diferentes.')
    return folder, cm


def carregar_checkpoint(folder, assinatura, definition, node_ids):
    receipt = validate_manifest(folder)
    if receipt['analysis_snapshot_sha256'] != assinatura or receipt['run'] != definition:
        raise ValueError('Checkpoint de comunidade incompatível.')
    p = pd.read_csv(folder/'particao.csv.gz')
    canonical = canonizar_particao(p[['entity_group_id','raw_community_id']].rename(columns={'raw_community_id':'community_id'}),node_ids)
    if not canonical.community_id.equals(p.sort_values('entity_group_id').reset_index(drop=True).community_id):
        raise ValueError('IDs canônicos divergentes no checkpoint.')
    return canonical, receipt['execution']


def salvar_checkpoint(folder, assinatura, definition, partition, execution):
    folder.parent.mkdir(parents=True,exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='.particao_',dir=folder.parent))
    try:
        write_csv(temp,'particao.csv.gz',partition)
        atomic_json(temp/'manifesto.json',{'analysis_snapshot_sha256':assinatura,'run':definition,'execution':execution,
            'outputs_sha256':{'particao.csv.gz':sha(temp/'particao.csv.gz')}})
        validate_manifest(temp);temp.rename(folder)
    finally:
        if temp.exists():shutil.rmtree(temp)


def comparar_fontes(partitions, referencias):
    """ARI/NMI apenas em IDs comuns; Jaccard usa grupos completos por fonte."""
    comparisons=[];matches=[]
    for a,b in combinations(partitions,2):
        for run in referencias:
            left=partitions[a][run].set_index('entity_group_id').community_id
            right=partitions[b][run].set_index('entity_group_id').community_id
            common=left.index.intersection(right.index).sort_values()
            score=comparar_particoes(left.reindex(common),right.reindex(common)) if len(common) else {'ari':None,'nmi':None}
            comparisons.append({'source_a':a,'source_b':b,'run_id':run,'common_nodes':len(common),
                'nodes_a':len(left),'nodes_b':len(right),'scope':'SHARED_ENTITIES_ONLY',**score})
            counts_a=Counter(left);counts_b=Counter(right)
            intersections=Counter(zip(left.reindex(common),right.reindex(common)))
            candidates=[]
            for (ca,cb),n in intersections.items():
                candidates.append({'source_a':a,'source_b':b,'run_id':run,'community_a':int(ca),'community_b':int(cb),
                    'nodes_a':counts_a[ca],'nodes_b':counts_b[cb],'shared_nodes':n,
                    'jaccard':n/(counts_a[ca]+counts_b[cb]-n),
                    'share_a_in_b':n/counts_a[ca],'share_b_in_a':n/counts_b[cb]})
            if candidates:
                best=pd.DataFrame(candidates).sort_values(['community_a','jaccard','shared_nodes','community_b'],ascending=[True,False,False,True])
                matches.extend(best.drop_duplicates('community_a').to_dict('records'))
    return pd.DataFrame(comparisons),pd.DataFrame(matches,columns=['source_a','source_b','run_id','community_a','community_b','nodes_a','nodes_b','shared_nodes','jaccard','share_a_in_b','share_b_in_a'])


def detectar_comunidades_fontes(projeto, *, executar_gds=False, sementes_leiden=(42,43,44),
                                assinatura_rede_esperada=None, assinatura_fontes_esperada=None, driver_factory=None):
    root=Path(projeto).resolve();origem,meta=carregar_fontes(root,assinatura_rede_esperada)
    if assinatura_fontes_esperada and meta['snapshot_sha256']!=assinatura_fontes_esperada:
        raise ValueError('Redes por fonte diferentes da edição esperada.')
    estrutura,sm=carregar_estrutura_fontes(root,meta);centralidades,cm=carregar_protagonismo(root,meta,sm)
    runs=configuracoes(sementes_leiden);reference_leiden=next(k for k in runs if k.startswith('leiden'))
    if not executar_gds:
        return {'mode':'DRY_RUN','sources':list(FONTES.values()),'runs':runs,'reference_partition':'louvain',
            'reference_leiden':reference_leiden,'maximum_owned_projections':1,'neo4j_connections':0,'api_calls':0,'files_written':0}
    spec={'schema':'source-weighted-communities-1','version':VERSION,'code_sha256':sha(Path(__file__)),
        'community_code_sha256':sha(Path(avaliar_particao.__code__.co_filename)),
        'projection_code_sha256':sha(Path(verificar_projecao.__code__.co_filename)),
        'network_snapshot_sha256':meta['network_snapshot_sha256'],'source_networks_snapshot_sha256':meta['snapshot_sha256'],
        'structural_snapshot_sha256':sm['snapshot_sha256'],'centrality_snapshot_sha256':cm['snapshot_sha256'],
        'runs':runs,'reference_partition':'louvain','reference_leiden':reference_leiden,'modularity_resolution':1.0}
    assinatura=json_sha(spec);base=root/'resultados/comparacao_fontes/comunidades';base.mkdir(parents=True,exist_ok=True)
    destino=base/'instancias'/assinatura[:20];checkpoint=base/'execucoes'/assinatura[:20];lock=base/'execucao.lock'
    try:lock.mkdir()
    except FileExistsError:raise RuntimeError('Detecção de comunidades pode estar ativa; confira o bloqueio.') from None
    driver=None;temp=None;source_in_progress=None
    try:
        if destino.exists():
            salvo=validate_manifest(destino)
            if salvo['snapshot_sha256']!=assinatura:raise ValueError('Assinatura de saída incompatível.')
            resumo=salvo['summary']
        else:
            temp=Path(tempfile.mkdtemp(prefix='.comunidades_',dir=base))
            data={};all_partitions={};executions={};versions=set()
            for slug in FONTES:
                nodes=pd.read_csv(centralidades/(slug+'_centralidades.csv.gz'),keep_default_na=False)
                components=pd.read_csv(estrutura/(slug+'_metricas_nos.csv.gz'))[['entity_group_id','component_id']]
                nodes=nodes.merge(components,on='entity_group_id',validate='one_to_one')
                counts=nodes.groupby('component_id').size().sort_index().sort_values(ascending=False,kind='stable')
                pairs=pd.read_csv(origem/(slug+'_ponderada_nao_dirigida.csv.gz'))
                data[slug]=(nodes,pairs,int(counts.index[0]));all_partitions[slug]={};executions[slug]={}
                for run,definition in runs.items():
                    saved=checkpoint/slug/run
                    if saved.exists():
                        p,execution=carregar_checkpoint(saved,assinatura,definition,nodes.entity_group_id)
                        all_partitions[slug][run]=p;executions[slug][run]=execution;versions.add(execution['gds_version'])
                        print('[COMUNIDADES FONTES] CHECKPOINT —',slug,run,flush=True)
            if len(versions)>1:raise ValueError('Checkpoints possuem versões GDS diferentes.')
            if any(len(p)<len(runs) for p in all_partitions.values()):
                uri,user,password,database=_configuration(root)
                if driver_factory is None:
                    from neo4j import GraphDatabase
                    driver_factory=GraphDatabase.driver
                driver=driver_factory(uri,auth=(user,password),connection_timeout=15,max_transaction_retry_time=10)
                driver.verify_connectivity()
                with driver.session(database=database) as session:
                    version=query(session,'RETURN gds.version() AS version')[0]['version']
                    if versions and version not in versions:raise ValueError('A versão GDS mudou; revise os checkpoints antes de retomar.')
                    for slug,fonte in FONTES.items():
                        source_in_progress=fonte
                        if len(all_partitions[slug])==len(runs):continue
                        nodes,pairs,gcc=data[slug];name='newsai_fontes_'+meta['snapshot_sha256'][:12]+'_'+slug+'_community_'+assinatura[:8]
                        tag='newsai_'+meta['network_snapshot_sha256'][:20]
                        try:
                            existe=query(session,EXISTS,name=name)[0]['exists']
                            if not existe:
                                rows=[{'source_id':int(a),'target_id':int(b),'weight':int(w)} for a,b,w in zip(pairs.source_id,pairs.target_id,pairs.weight)]
                                session.run(PROJETAR,rows=rows,tag=tag,name=name).consume()
                            verification=verificar_projecao(session,name,database,tag,set(nodes.entity_group_id),valores_esperados('community',None,pairs))
                            for run,definition in runs.items():
                                if run in all_partitions[slug]:continue
                                raw,execution=executar_algoritmo(session,name,definition['algorithm'],definition['config'])
                                partition=canonizar_particao(raw,nodes.entity_group_id)
                                execution['projection']=verification
                                salvar_checkpoint(checkpoint/slug/run,assinatura,definition,partition,execution)
                                all_partitions[slug][run]=partition;executions[slug][run]=execution
                                print('[COMUNIDADES FONTES]',fonte,run,'—',partition.community_id.nunique(),'comunidades; partição salva.',flush=True)
                        finally:
                            try:
                                session.run('CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName',name=name).consume()
                                print('[COMUNIDADES FONTES] PROJEÇÃO LIBERADA —',fonte,flush=True)
                            except Exception as exc:print('[COMUNIDADES FONTES] LIBERAÇÃO PENDENTE —',json.dumps(_failure(exc)),flush=True)
            resumos=[];catalog=[]
            for slug,fonte in FONTES.items():
                nodes,pairs,gcc=data[slug];assignments=[];stats=[];tops=[];summaries=[]
                for run in runs:
                    f,s,t,total=avaliar_particao(nodes,pairs,all_partitions[slug][run],gcc_component_id=gcc)
                    for frame in [f,s,t]:frame.insert(0,'run_id',run)
                    assignments.append(f);stats.append(s);tops.append(t)
                    summaries.append({'source_key':slug,'source':fonte,'run_id':run,**total,
                        'algorithm_seconds':executions[slug][run]['elapsed_seconds']})
                baseline=canonizar_particao(nodes[['entity_group_id','component_id']].rename(columns={'component_id':'community_id'}),nodes.entity_group_id)
                baseline_total=avaliar_particao(nodes,pairs,baseline,gcc_component_id=gcc)[-1]
                comparisons=tabela_comparacoes(all_partitions[slug],nodes,gcc)
                stat=pd.concat(stats,ignore_index=True)
                for name,frame in [('particoes_nos.csv.gz',pd.concat(assignments,ignore_index=True)),('metricas_comunidades.csv.gz',stat),
                    ('entidades_destaque.csv.gz',pd.concat(tops,ignore_index=True)),('resumo_particoes.csv',pd.DataFrame(summaries)),('comparacao_particoes.csv',comparisons)]:
                    write_csv(temp,slug+'_'+name,frame)
                staging=temp/slug;staging.mkdir()
                cat=gerar_figuras(staging,stat,comparisons,reference_leiden)
                for p in staging.iterdir():p.rename(temp/(slug+'_'+p.name))
                staging.rmdir()
                expanded=pd.DataFrame([{'source_key':slug,'file':slug+'_'+row.figure+'.'+ext,
                    'objective':row.objective,'caption':row.caption}
                    for row in cat.itertuples(index=False) for ext in ['svg','png','pdf']])
                catalog.append(expanded)
                row={'source_key':slug,'source':fonte,'nodes':len(nodes),'undirected_pairs':len(pairs),
                    'component_partition_modularity':baseline_total['weighted_modularity'],'partitions':summaries}
                resumos.append(row);print('[COMUNIDADES FONTES] RESUMO —',json.dumps(row,ensure_ascii=False),flush=True)
            cross,matches=comparar_fontes(all_partitions,['louvain',reference_leiden])
            write_csv(temp,'comparacao_fontes_entidades_comuns.csv',cross);write_csv(temp,'correspondencias_comunidades.csv.gz',matches)
            write_csv(temp,'catalogo_figuras.csv',pd.concat(catalog,ignore_index=True));atomic_json(temp/'execucoes_gds.json',executions)
            resumo={'networks':resumos,'runs_per_source':len(runs),'total_runs':len(runs)*len(FONTES),
                'reference_partition':'louvain','reference_leiden':reference_leiden,'cross_source_comparisons':len(cross),
                'figure_files':len(pd.concat(catalog)),'all_nodes_assigned_in_all_runs':True,
                'database_writes':0,'api_calls':0,'gds_properties_mutated':0,'global_partitions_modified':False}
            (temp/'LEIA_ME.md').write_text(
                '# Comunidades por fonte\n\nProjeções ponderadas não dirigidas somam rótulos e ambos os sentidos. '
                'Uma fonte por vez; sua projeção é liberada ao final. Partições completas são salvas por execução e '
                'retomadas sem nova detecção quando compatíveis. Louvain é a referência; a primeira semente de Leiden '
                'é a referência visual predefinida. Todas as partições são preservadas.\n\n'
                'Modularidade é calculada na mesma convenção ponderada, resolução 1; a partição por componentes é '
                'referência de fragmentação, não teste contra modelo nulo. ARI/NMI dentro da fonte usam toda a rede e '
                'a restrição à maior componente de partições detectadas globalmente. Entre fontes, usam somente entidades comuns.\n\n'
                'Correspondências são os melhores candidatos por Jaccard para cada comunidade A com alguma entidade '
                'compartilhada em B; não são associação um a um nem equivalência temática. Comunidades sem interseção '
                'não aparecem nessa tabela. IDs iguais não estabelecem correspondência entre fontes ou partições.\n\n'
                'Modularidade ou concordância elevadas não garantem validade semântica. Conectividade interna é verificada '
                'e grupos desconectados são sinalizados, sem divisão ou correção automática. Notícias e visualizações '
                'de subgrafos devem fundamentar a interpretação temática posterior.\n',encoding='utf-8')
            atomic_json(temp/'manifesto.json',{**spec,'snapshot_sha256':assinatura,'summary':resumo,
                'created_at_utc':datetime.now(timezone.utc).isoformat(),
                'outputs_sha256':{p.name:sha(p) for p in sorted(temp.iterdir())}})
            validate_manifest(temp);destino.parent.mkdir(exist_ok=True);temp.rename(destino);temp=None
        atomic_json(base/'atual.json',{'folder':destino.relative_to(base).as_posix(),'snapshot_sha256':assinatura})
        pacote=base/('Resumo_Comunidades_Fontes_'+assinatura[:12]+'_'+uuid.uuid4().hex[:6]+'.zip')
        with zipfile.ZipFile(pacote,'w',zipfile.ZIP_DEFLATED) as z:
            for p in sorted(destino.iterdir()):z.write(p,p.name)
        print('[COMUNIDADES FONTES] Pacote:',pacote)
        return {**resumo,'output_directory':destino,'package':pacote,'snapshot_sha256':assinatura}
    except Exception as exc:
        falha={**_failure(exc),'source':source_in_progress}
        if 'Java heap space' in str(getattr(exc,'message',exc)):falha['cause']='JAVA_HEAP_SPACE'
        print('[COMUNIDADES FONTES] FALHA:',json.dumps(falha,ensure_ascii=False))
        raise RuntimeError('Detecção não concluída; entradas e checkpoints publicados permanecem preservados.') from None
    finally:
        try:
            if driver is not None:driver.close()
        finally:
            if temp is not None and temp.exists():shutil.rmtree(temp)
            lock.rmdir()
