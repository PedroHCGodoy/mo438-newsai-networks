"""Projeções GDS versionadas de uma rede científica com proveniência preservada."""
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
import os
import shutil
import tempfile
import uuid
import zipfile
import pandas as pd
from redes_construcao import carregar_rede
from re_consolidacao import sha, json_sha, write_csv, validate_manifest
from re_execucao import atomic_json
from neo4j_carga import preparar_carga, validar_banco, GET_RUN
from neo4j_integracao import _configuration, _failure

VERSION='1.0.0'
KINDS=('directed','structural','community')
LIST_GRAPH='''CALL gds.graph.list($name) YIELD graphName, nodeCount, relationshipCount, database, memoryUsage
    RETURN graphName, nodeCount, relationshipCount, database, memoryUsage'''
EXISTS='CALL gds.graph.exists($name) YIELD exists RETURN exists'
STREAM_NODES='''CALL gds.graph.nodeProperty.stream($name, 'entity_group_id') YIELD nodeId, propertyValue
    RETURN propertyValue AS entity_group_id, gds.util.asNode(nodeId).graph_tag AS graph_tag'''
STREAM_PROPERTY='''CALL gds.graph.relationshipProperty.stream($name, $property)
    YIELD sourceNodeId, targetNodeId, propertyValue
    RETURN gds.util.asNode(sourceNodeId).entity_group_id AS source_id,
           gds.util.asNode(targetNodeId).entity_group_id AS target_id, propertyValue AS value'''
BASE_MATCH='''MATCH (s:NewsAIEntity {graph_tag:$tag})
    -[r:NEWSAI_RELATES_TO {graph_tag:$tag}]->(t:NewsAIEntity {graph_tag:$tag})'''
CANONICAL='''WITH r,
    CASE WHEN s.entity_group_id < t.entity_group_id THEN s ELSE t END AS source,
    CASE WHEN s.entity_group_id < t.entity_group_id THEN t ELSE s END AS target'''


def query_projecao(kind):
    if kind=='directed':
        rows=BASE_MATCH+'\nWITH s AS source, t AS target, toFloat(r.weight) AS weight, toFloat(r.distance) AS distance'
        options='{readConcurrency: 4}'
    elif kind in ['structural','community']:
        rows=BASE_MATCH+'\n'+CANONICAL
        if kind=='structural':rows+='\nWITH DISTINCT source, target\nWITH source, target, 1.0 AS weight, 1.0 AS distance'
        else:rows+='\nWITH source, target, sum(toFloat(r.weight)) AS weight\nWITH source, target, weight, 1.0/weight AS distance'
        options="{readConcurrency: 4, undirectedRelationshipTypes: ['NEWSAI_RELATES_TO']}"
    else:raise ValueError('Tipo de projeção desconhecido.')
    return rows+'''
    WITH gds.graph.project($name, source, target,
        {sourceNodeLabels: ['NewsAIEntity'], targetNodeLabels: ['NewsAIEntity'],
         sourceNodeProperties: {entity_group_id: source.entity_group_id},
         targetNodeProperties: {entity_group_id: target.entity_group_id},
         relationshipType: 'NEWSAI_RELATES_TO',
         relationshipProperties: {weight: weight, distance: distance}},
        '''+options+''') AS g
    RETURN g.graphName AS graphName, g.nodeCount AS nodeCount, g.relationshipCount AS relationshipCount'''


def _read(path):return pd.read_csv(path,dtype=str,keep_default_na=False)


def preparar_tabelas(edges, support):
    edges=edges.copy();support=support.copy()
    if not edges.edge_id.is_unique:raise ValueError('ID de aresta duplicado.')
    if not set(support.edge_id).issubset(set(edges.edge_id)):raise ValueError('Suporte com aresta desconhecida.')
    edges['source_id']=pd.to_numeric(edges.source_id,errors='raise').astype('int64')
    edges['target_id']=pd.to_numeric(edges.target_id,errors='raise').astype('int64')
    edges['weight']=pd.to_numeric(edges.weight,errors='raise').astype('int64')
    if edges.source_id.eq(edges.target_id).any() or edges.weight.lt(1).any():
        raise ValueError('Autolaço ou peso inválido na entrada.')
    edges['pair_source_id']=edges[['source_id','target_id']].min(axis=1)
    edges['pair_target_id']=edges[['source_id','target_id']].max(axis=1)
    pairs=edges.groupby(['pair_source_id','pair_target_id'],sort=True).agg(
        weight=('weight','sum'),typed_edge_count=('edge_id','size')).reset_index()
    pairs['pair_id']=[json_sha(['undirected-pair-v1',int(a),int(b)])
        for a,b in zip(pairs.pair_source_id,pairs.pair_target_id)]
    links=edges[['edge_id','pair_source_id','pair_target_id']].merge(
        pairs[['pair_source_id','pair_target_id','pair_id']],on=['pair_source_id','pair_target_id'],validate='many_to_one')
    news=support[['edge_id','news_id']].drop_duplicates().merge(links[['edge_id','pair_id']],on='edge_id',validate='many_to_one')
    counts=news.groupby('pair_id').news_id.nunique().rename('distinct_news_count').reset_index()
    pairs=pairs.merge(counts,on='pair_id',how='left',validate='one_to_one')
    if pairs.distinct_news_count.isna().any():raise ValueError('Par sem suporte documental.')
    pairs['distinct_news_count']=pairs.distinct_news_count.astype('int64')
    pairs=pairs.rename(columns={'pair_source_id':'source_id','pair_target_id':'target_id'})
    pairs['distance']=1.0/pairs.weight
    simple=pairs[['pair_id','source_id','target_id','distinct_news_count','typed_edge_count']].copy()
    simple['weight']=1;simple['distance']=1.0
    if int(pairs.weight.sum())!=int(edges.weight.sum()):raise ValueError('Peso perdido na projeção.')
    return {'simples_nao_dirigida.csv.gz':simple,'ponderada_nao_dirigida.csv.gz':pairs,
        'vinculos_arestas_projecoes.csv.gz':links}, edges


def preparar_projecoes(projeto, assinatura_rede_esperada=None):
    root=Path(projeto).resolve();network_folder,network=carregar_rede(root)
    if assinatura_rede_esperada and network['snapshot_sha256']!=assinatura_rede_esperada:
        raise ValueError('A rede ativa difere da edição esperada.')
    spec={'schema':'gds-network-projections-1','version':VERSION,
        'network_snapshot_sha256':network['snapshot_sha256'],'code_sha256':sha(Path(__file__)),
        'policies':{'directed':'preserve_typed_parallel_edges','structural':'one_unit_edge_per_unordered_pair',
            'community':'sum_record_weights_per_unordered_pair','news_support':'union_of_news_ids'},
        'inputs_sha256':{str((network_folder/n).relative_to(root)):sha(network_folder/n)
            for n in ['arestas.csv.gz','arestas_noticias.csv.gz','nos.csv.gz']}}
    signature=json_sha(spec);base=root/'dados/processados/redes/projecoes';base.mkdir(parents=True,exist_ok=True)
    folder=base/signature[:20]
    names={kind:'newsai_'+network['snapshot_sha256'][:20]+'_'+kind+'_'+signature[:8] for kind in KINDS}
    if folder.exists():
        meta=validate_manifest(folder)
        if meta['snapshot_sha256']!=signature:raise ValueError('Colisão de assinatura da projeção.')
    else:
        frames,edges=preparar_tabelas(_read(network_folder/'arestas.csv.gz'),_read(network_folder/'arestas_noticias.csv.gz'))
        pairs=len(frames['ponderada_nao_dirigida.csv.gz']);total=int(edges.weight.sum())
        summary={'nodes':network['summary']['nodes'],'typed_directed_edges':len(edges),
            'distinct_directed_pairs':len(edges[['source_id','target_id']].drop_duplicates()),
            'undirected_pairs':pairs,'record_weight_sum':total,
            'expected_gds_relationships':{'directed':len(edges),'structural':2*pairs,'community':2*pairs},
            'expected_gds_weight_sums':{'directed':total,'structural':2*pairs,'community':2*total}}
        temp=Path(tempfile.mkdtemp(prefix='.preparando_',dir=base))
        try:
            for name,frame in frames.items():write_csv(temp,name,frame)
            meta={**spec,'snapshot_sha256':signature,'graph_names':names,'summary':summary,
                'created_at_utc':datetime.now(timezone.utc).isoformat(),
                'outputs_sha256':{p.name:sha(p) for p in sorted(temp.iterdir())}}
            atomic_json(temp/'manifesto.json',meta);validate_manifest(temp)
            if carregar_rede(root)[1]['snapshot_sha256']!=network['snapshot_sha256']:
                raise ValueError('Rede ativa alterada durante a preparação.')
            os.rename(temp,folder)
        finally:
            if temp.exists():shutil.rmtree(temp)
    return folder,meta,network_folder,network


def _query(session,query,**params):
    return session.execute_read(lambda tx:[row.data() for row in tx.run(query,**params)])


def valores_esperados(kind, edges, pairs):
    values=defaultdict(list)
    data=edges if kind=='directed' else pairs
    for row in data.to_dict('records'):
        a,b=int(row['source_id']),int(row['target_id'])
        w=float(row['weight']) if kind!='structural' else 1.0
        values[(a,b)].append(w)
        if kind!='directed':values[(b,a)].append(w)
    return values


def conferir_valores(rows, expected, inverse=False):
    actual=defaultdict(list)
    for row in rows:
        value=float(row['value'])
        if not math.isfinite(value) or value<=0:raise ValueError('Valor projetado inválido.')
        actual[(int(row['source_id']),int(row['target_id']))].append(value)
    if set(actual)!=set(expected):raise ValueError('Topologia projetada diferente da entrada.')
    for key,vals in expected.items():
        reference=sorted(1.0/v if inverse else v for v in vals)
        observed=sorted(actual[key])
        if len(reference)!=len(observed) or any(not math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-12)
                                               for a,b in zip(reference,observed)):
            raise ValueError('Multiplicidade ou propriedade projetada diferente da entrada.')
    return sum(sum(v) for v in actual.values())


def verificar_projecao(session,name,database,tag,node_ids,expected):
    listing=_query(session,LIST_GRAPH,name=name)
    if len(listing)!=1:raise ValueError('Projeção ausente ou ambígua no catálogo GDS.')
    info=listing[0]
    expected_count=sum(len(v) for v in expected.values())
    if info['database']!=database or info['nodeCount']!=len(node_ids) or info['relationshipCount']!=expected_count:
        raise ValueError('Banco ou contagens diferentes da projeção esperada.')
    rows=_query(session,STREAM_NODES,name=name)
    if (len(rows)!=len(node_ids) or {int(r['entity_group_id']) for r in rows}!=node_ids
            or any(r['graph_tag']!=tag for r in rows)):
        raise ValueError('Nós projetados incompatíveis com a edição.')
    weight=conferir_valores(_query(session,STREAM_PROPERTY,name=name,property='weight'),expected)
    conferir_valores(_query(session,STREAM_PROPERTY,name=name,property='distance'),expected,inverse=True)
    return {**info,'weight_sum':weight,'all_nodes_checked':True,
        'all_relationship_endpoints_and_properties_checked':True}


def executar_projecoes(driver,database,payload,meta,edges,pairs):
    driver.verify_connectivity();results={}
    with driver.session(database=database) as session:
        runs=_query(session,GET_RUN,tag=payload['tag'])
        if (len(runs)!=1 or runs[0]['properties'].get('state')!='COMPLETE'
                or runs[0]['properties'].get('snapshot_sha256')!=payload['snapshot']
                or runs[0]['properties'].get('payload_sha256')!=json_sha(payload)):
            raise ValueError('A carga da rede deve estar completa e compatível antes de projetar.')
        validar_banco(session,payload)
        node_ids={p['entity_group_id'] for p in payload['nodes']}
        for kind in KINDS:
            name=meta['graph_names'][kind]
            exists=_query(session,EXISTS,name=name)[0]['exists']
            if not exists:
                # Projeção tem efeito no catálogo em memória: não retentar automaticamente a consulta.
                result=session.run(query_projecao(kind),tag=payload['tag'],name=name)
                result.consume()
            checked=verificar_projecao(session,name,database,payload['tag'],node_ids,
                valores_esperados(kind,edges,pairs))
            checked['reused_existing_projection']=bool(exists);results[kind]=checked
            print('[GDS]',kind,json.dumps(checked,ensure_ascii=False),flush=True)
    return results


def criar_projecoes_gds(projeto, *, executar_gds=False, assinatura_rede_esperada=None, driver_factory=None):
    root=Path(projeto).resolve()
    folder,meta,network_folder,network=preparar_projecoes(root,assinatura_rede_esperada)
    if not executar_gds:
        result={'mode':'DRY_RUN','neo4j_connections':0,'gds_graphs_created':0,
            **meta['summary'],'graph_names':meta['graph_names'],'output_directory':folder}
        print('[GDS]',json.dumps({k:v for k,v in result.items() if k!='output_directory'},ensure_ascii=False));return result
    output=root/'resultados/neo4j';output.mkdir(parents=True,exist_ok=True)
    lock=output/'projecoes.lock'
    try:lock.mkdir()
    except FileExistsError:raise RuntimeError('Outra criação de projeções pode estar ativa. Confira o bloqueio.') from None
    driver=None
    try:
        payload=preparar_carga(network_folder,network)
        edges=_read(network_folder/'arestas.csv.gz');pairs=_read(folder/'ponderada_nao_dirigida.csv.gz')
        uri,user,password,database=_configuration(root)
        if driver_factory is None:
            from neo4j import GraphDatabase
            driver_factory=GraphDatabase.driver
        driver=driver_factory(uri,auth=(user,password),connection_timeout=15,max_transaction_retry_time=10)
        results=executar_projecoes(driver,database,payload,meta,edges,pairs)
        if carregar_rede(root)[1]['snapshot_sha256']!=network['snapshot_sha256']:
            raise ValueError('A rede ativa mudou durante a projeção.')
        report={'schema':'gds-projections-validation-1','version':VERSION,
            'network_snapshot_sha256':network['snapshot_sha256'],
            'projection_snapshot_sha256':meta['snapshot_sha256'],
            'graph_tag':payload['tag'],'database':database,'graph_names':meta['graph_names'],
            'summary':meta['summary'],'projections':results,
            'database_data_modified':False,'existing_projections_removed':0,
            'gds_graphs_created':sum(not x['reused_existing_projection'] for x in results.values()),
            'created_at_utc':datetime.now(timezone.utc).isoformat()}
        stamp=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
        path=output/('Projecoes_GDS_'+stamp+'.json');atomic_json(path,report)
        atomic_json(root/'dados/processados/redes/projecoes/atual.json',{
            'folder':folder.name,'snapshot_sha256':meta['snapshot_sha256'],
            'network_snapshot_sha256':network['snapshot_sha256'],'validation_report':path.relative_to(root).as_posix(),'validation_report_sha256':sha(path)})
        package=output/('Resumo_Projecoes_GDS_'+stamp+'.zip')
        with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
            z.write(path,'projecoes_gds.json');z.write(folder/'manifesto.json','manifesto.json')
            for name in meta['outputs_sha256']:
                z.writestr('amostra_'+name.removesuffix('.gz'),_read(folder/name).head(30).to_csv(index=False))
        print('[GDS] Pacote:',package)
        return {**meta['summary'],'graph_names':meta['graph_names'],'projections':results,
            'output_directory':folder,'package':package}
    except (ValueError,RuntimeError):raise
    except Exception as exc:
        raise RuntimeError('Projeção interrompida; nenhuma remoção automática foi realizada. Diagnóstico: '+json.dumps(_failure(exc))) from None
    finally:
        if driver is not None:driver.close()
        lock.rmdir()


def carregar_projecoes(projeto):
    root=Path(projeto).resolve();base=root/'dados/processados/redes/projecoes'
    pointer=json.loads((base/'atual.json').read_text(encoding='utf-8'))
    if Path(pointer['folder']).name!=pointer['folder']:raise ValueError('Apontador inválido.')
    folder=base/pointer['folder'];meta=validate_manifest(folder)
    if pointer['snapshot_sha256']!=meta['snapshot_sha256']:raise ValueError('Assinatura de projeção incompatível.')
    if carregar_rede(root)[1]['snapshot_sha256']!=meta['network_snapshot_sha256']:
        raise ValueError('A rede ativa mudou. Atualize as projeções.')
    if any(sha(root/p)!=h for p,h in meta['inputs_sha256'].items()):raise ValueError('Entradas da projeção alteradas.')
    report_path=(root/pointer['validation_report']).resolve()
    if root not in report_path.parents or sha(report_path)!=pointer['validation_report_sha256']:
        raise ValueError('Recibo de validação ausente ou modificado.')
    report=json.loads(report_path.read_text(encoding='utf-8'))
    if report['projection_snapshot_sha256']!=meta['snapshot_sha256'] or report['graph_names']!=meta['graph_names']:
        raise ValueError('Recibo de validação incompatível.')
    return folder,meta
