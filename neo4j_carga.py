"""Carga versionada de redes em um espaço de nomes separado dos dados anteriores."""
from pathlib import Path
from datetime import datetime, timezone
import json
import uuid
import zipfile
import pandas as pd
from redes_construcao import carregar_rede
from re_consolidacao import json_sha
from re_execucao import atomic_json
from neo4j_integracao import _configuration, _failure

VERSION='1.0.0'
NODE_LABEL='NewsAIEntity'
RELATION_TYPE='NEWSAI_RELATES_TO'
NODE_CONSTRAINT='CREATE CONSTRAINT newsai_entity_graph_id_v1 IF NOT EXISTS FOR (n:NewsAIEntity) REQUIRE (n.graph_tag, n.entity_group_id) IS UNIQUE'
EDGE_CONSTRAINT='CREATE CONSTRAINT newsai_relation_graph_id_v1 IF NOT EXISTS FOR ()-[r:NEWSAI_RELATES_TO]-() REQUIRE (r.graph_tag, r.edge_id) IS UNIQUE'
CHECK_CONSTRAINTS='SHOW CONSTRAINTS YIELD name, type, labelsOrTypes, properties RETURN name, type, labelsOrTypes, properties'
RUN_CONSTRAINT='CREATE CONSTRAINT newsai_network_tag_v1 IF NOT EXISTS FOR (n:NewsAINetwork) REQUIRE n.graph_tag IS UNIQUE'
GET_RUN='MATCH (n:NewsAINetwork {graph_tag:$tag}) RETURN properties(n) AS properties'
TARGET_COUNTS='''CALL () { MATCH (n:NewsAIEntity {graph_tag:$tag}) RETURN count(n) AS nodes }
    CALL () { MATCH ()-[r:NEWSAI_RELATES_TO {graph_tag:$tag}]->() RETURN count(r) AS edges }
    RETURN nodes, edges'''
INITIALIZE='''MERGE (n:NewsAINetwork {graph_tag:$tag})
    ON CREATE SET n.snapshot_sha256=$snapshot, n.payload_sha256=$payload,
        n.state='LOADING', n.created_at=$created_at, n.loader_version=$version
    RETURN properties(n) AS properties'''
NODES='''UNWIND $rows AS row
    MERGE (n:NewsAIEntity {graph_tag:$tag, entity_group_id:row.entity_group_id})
    SET n = row
    RETURN count(n) AS processed'''
EDGES='''UNWIND $rows AS row
    MATCH (s:NewsAIEntity {graph_tag:$tag, entity_group_id:row.source_group_id})
    MATCH (t:NewsAIEntity {graph_tag:$tag, entity_group_id:row.target_group_id})
    MERGE (s)-[r:NEWSAI_RELATES_TO {graph_tag:$tag, edge_id:row.edge_id}]->(t)
    SET r = row
    RETURN count(r) AS processed'''
READ_NODES='MATCH (n:NewsAIEntity {graph_tag:$tag}) RETURN properties(n) AS properties'
READ_EDGES='''MATCH (s)-[r:NEWSAI_RELATES_TO {graph_tag:$tag}]->(t)
    RETURN properties(r) AS properties, s.graph_tag AS source_tag,
        t.graph_tag AS target_tag, s.entity_group_id AS source_id,
        t.entity_group_id AS target_id, labels(s) AS source_labels, labels(t) AS target_labels'''
FINISH="MATCH (n:NewsAINetwork {graph_tag:$tag}) SET n.state='COMPLETE', n.validated_at=$validated_at RETURN n.state AS state"


def _frame(path):return pd.read_csv(path,dtype=str,keep_default_na=False)


def preparar_carga(folder, meta, examples=3):
    """Converte apenas os atributos aprovados; a proveniência completa permanece em tabelas."""
    folder=Path(folder);tag='newsai_'+meta['snapshot_sha256'][:20]
    nodes=_frame(folder/'nos.csv.gz');edges=_frame(folder/'arestas.csv.gz')
    news=_frame(folder/'noticias.csv.gz').sort_values(['publication_date','source','news_id'],kind='stable')
    if not news.news_id.is_unique or not nodes.entity_group_id.is_unique or not edges.edge_id.is_unique:
        raise ValueError('Identificadores duplicados nas entradas de carga.')
    samples={}
    for kind, name, key in [('nodes','nos_noticias.csv.gz','entity_group_id'),('edges','arestas_noticias.csv.gz','edge_id')]:
        support=_frame(folder/name)[[key,'news_id']].drop_duplicates()
        joined=support.merge(news[['news_id','title','link','publication_date','source']],on='news_id',validate='many_to_one')
        joined=joined.sort_values([key,'publication_date','source','news_id'],kind='stable').groupby(key,sort=False).head(examples)
        samples[kind]={str(identity):{'example_news_ids':g.news_id.tolist(),
            'example_titles':g.title.tolist(),'example_links':g.link.tolist()}
            for identity,g in joined.groupby(key,sort=False)}
    node_rows=[]
    for row in nodes.to_dict('records'):
        props={'graph_tag':tag,'entity_group_id':int(row['entity_group_id']),
            'name':row['entity_group_name'],'entity_label':row['ent_label'],
            'first_observed_date':row['first_observed_date'],'last_observed_date':row['last_observed_date'],
            'entity_review_required':row['entity_review_required'] in ['True','true','1'],
            'support_table':'nos_noticias.csv.gz','network_snapshot_sha256':meta['snapshot_sha256']}
        for key in ['mention_count','distinct_news_count','relation_news_count','review_mentions','distinct_source_count']:
            props[key]=int(row[key])
        props.update(samples['nodes'].get(row['entity_group_id'],{}));node_rows.append(props)
    edge_rows=[]
    for row in edges.to_dict('records'):
        weight=int(row['weight'])
        if weight<1 or row['source_id']==row['target_id'] or row['label']=='ident':
            raise ValueError('Peso ou relação incompatível com os critérios da rede.')
        props={'graph_tag':tag,'edge_id':row['edge_id'],
            'source_group_id':int(row['source_id']),'target_group_id':int(row['target_id']),
            'relation_label':row['label'],'relation_macro':row['relation_macro'],'weight':weight,
            'distance':1.0/weight,'first_observed_date':row['first_observed_date'],
            'last_observed_date':row['last_observed_date'],'support_table':'arestas_noticias.csv.gz',
            'network_snapshot_sha256':meta['snapshot_sha256']}
        for key in ['distinct_news_count','distinct_source_count','review_records','provisional_records','semantic_flag_records']:
            props[key]=int(row[key])
        props.update(samples['edges'].get(row['edge_id'],{}));edge_rows.append(props)
    ids={p['entity_group_id'] for p in node_rows}
    if any(p['source_group_id'] not in ids or p['target_group_id'] not in ids for p in edge_rows):
        raise ValueError('Extremo de aresta ausente dos nós.')
    if len(node_rows)!=meta['summary']['nodes'] or len(edge_rows)!=meta['summary']['edges']:
        raise ValueError('Contagens diferentes do manifesto.')
    if sum(p['weight'] for p in edge_rows)!=meta['summary']['weight_sum']:
        raise ValueError('Peso total diferente do manifesto.')
    payload={'tag':tag,'snapshot':meta['snapshot_sha256'],'nodes':node_rows,'edges':edge_rows}
    return payload


def _query(session, query, write=False, **params):
    method=session.execute_write if write else session.execute_read
    return method(lambda tx:[x.data() for x in tx.run(query,**params)])


def validar_banco(session, payload):
    """Compara todos os nós/arestas e seus atributos com a entrada, incluindo endpoints."""
    tag=payload['tag']
    expected_nodes={p['entity_group_id']:p for p in payload['nodes']}
    expected_edges={p['edge_id']:p for p in payload['edges']}
    rows=_query(session,READ_NODES,tag=tag);seen=set()
    for row in rows:
        props=row['properties'];key=props.get('entity_group_id')
        if key in seen or key not in expected_nodes or any(props.get(k)!=v for k,v in expected_nodes.get(key,{}).items()):
            raise ValueError('Nó duplicado, inesperado ou com atributos divergentes na nova edição.')
        seen.add(key)
    if seen!=set(expected_nodes):raise ValueError('Faltam nós na carga.')
    rows=_query(session,READ_EDGES,tag=tag);seen=set();total=0
    for row in rows:
        props=row['properties'];key=props.get('edge_id')
        if key in seen or key not in expected_edges or any(props.get(k)!=v for k,v in expected_edges.get(key,{}).items()):
            raise ValueError('Aresta duplicada, inesperada ou com atributos divergentes na nova edição.')
        if (row['source_tag']!=tag or row['target_tag']!=tag
                or row['source_id']!=props['source_group_id'] or row['target_id']!=props['target_group_id']
                or NODE_LABEL not in row['source_labels'] or NODE_LABEL not in row['target_labels']):
            raise ValueError('Extremo fora do espaço de nomes da edição.')
        seen.add(key);total+=props['weight']
    if seen!=set(expected_edges):raise ValueError('Faltam arestas na carga.')
    return {'nodes':len(expected_nodes),'edges':len(expected_edges),'weight_sum':total,
            'all_properties_verified':True,'self_loops':0,'identity_edges':0}


def importar_driver(driver, database, payload, batch_size=1000):
    """Carga em lotes retomáveis; não limpa dados ou restrições existentes."""
    if not isinstance(batch_size,int) or isinstance(batch_size,bool) or not 1<=batch_size<=10000:
        raise ValueError('Tamanho de lote deve estar entre 1 e 10000.')
    tag=payload['tag'];checksum=json_sha(payload)
    driver.verify_connectivity()
    with driver.session(database=database) as session:
        runs=_query(session,GET_RUN,tag=tag)
        if len(runs)>1:raise ValueError('Metadados duplicados para esta edição.')
        counts=_query(session,TARGET_COUNTS,tag=tag)[0]
        if not runs and (counts['nodes'] or counts['edges']):
            raise ValueError('Há dados no destino sem manifesto de carga. Nenhuma limpeza será realizada.')
        if runs:
            run=runs[0]['properties']
            if run.get('snapshot_sha256')!=payload['snapshot'] or run.get('payload_sha256')!=checksum:
                raise ValueError('O destino contém outra versão de dados ou atributos.')
            if run.get('state')=='COMPLETE':
                return {**validar_banco(session,payload),'reused_completed_load':True,'batches_written':0}
            if run.get('state')!='LOADING':raise ValueError('Estado de carga desconhecido.')
        for query in [NODE_CONSTRAINT,EDGE_CONSTRAINT,RUN_CONSTRAINT]:
            # DDL não deve usar retentativa de callback com efeitos externos.
            session.run(query).consume()
        constraints={row['name']:row for row in _query(session,CHECK_CONSTRAINTS)}
        for name,label,properties in [('newsai_entity_graph_id_v1',NODE_LABEL,['graph_tag','entity_group_id']),
                ('newsai_relation_graph_id_v1',RELATION_TYPE,['graph_tag','edge_id']),
                ('newsai_network_tag_v1','NewsAINetwork',['graph_tag'])]:
            row=constraints.get(name,{})
            if row.get('labelsOrTypes')!=[label] or row.get('properties')!=properties or 'UNIQUENESS' not in row.get('type',''):
                raise ValueError('Restrição ausente ou nome em conflito: '+name)
        stored=_query(session,INITIALIZE,write=True,tag=tag,snapshot=payload['snapshot'],payload=checksum,
            created_at=datetime.now(timezone.utc).isoformat(),version=VERSION)
        if len(stored)!=1 or stored[0]['properties'].get('payload_sha256')!=checksum:
            raise ValueError('Registro de carga incompatível.')
        batches=0
        for kind,query in [('nodes',NODES),('edges',EDGES)]:
            values=payload[kind]
            for start in range(0,len(values),batch_size):
                batch=values[start:start+batch_size]
                result=_query(session,query,write=True,tag=tag,rows=batch)
                if result[0]['processed']!=len(batch):raise ValueError('Lote com contagem incompleta.')
                batches+=1
                print(f'[NEO4J] {kind}: {min(start+batch_size,len(values)):,}/{len(values):,}',flush=True)
        result=validar_banco(session,payload)
        _query(session,FINISH,write=True,tag=tag,validated_at=datetime.now(timezone.utc).isoformat())
        return {**result,'reused_completed_load':False,'batches_written':batches}


def carregar_rede_neo4j(projeto, *, executar_carga=False, assinatura_rede_esperada=None,
                        batch_size=1000, driver_factory=None):
    root=Path(projeto).resolve();folder,meta=carregar_rede(root)
    if assinatura_rede_esperada and meta['snapshot_sha256']!=assinatura_rede_esperada:
        raise ValueError('A rede selecionada difere da edição esperada.')
    payload=preparar_carga(folder,meta)
    if not executar_carga:
        summary={'mode':'DRY_RUN','neo4j_connections':0,'database_writes':0,
            'graph_tag':payload['tag'],'nodes':len(payload['nodes']),'edges':len(payload['edges']),
            'weight_sum':sum(x['weight'] for x in payload['edges']),
            'node_label':NODE_LABEL,'relationship_type':RELATION_TYPE}
        print('[NEO4J]',json.dumps(summary));return summary
    lock=root/'resultados/neo4j/carga.lock';lock.parent.mkdir(parents=True,exist_ok=True)
    try:lock.mkdir()
    except FileExistsError:raise RuntimeError('Outra carga pode estar ativa. Confira o bloqueio antes de prosseguir.') from None
    driver=None
    try:
        atomic_json(lock/'owner.json',{'graph_tag':payload['tag'],'started_at':datetime.now(timezone.utc).isoformat()})
        uri,user,password,database=_configuration(root)
        if driver_factory is None:
            from neo4j import GraphDatabase
            driver_factory=GraphDatabase.driver
        driver=driver_factory(uri,auth=(user,password),connection_timeout=15,max_transaction_retry_time=10)
        result=importar_driver(driver,database,payload,batch_size=batch_size)
        if carregar_rede(root)[1]['snapshot_sha256']!=meta['snapshot_sha256']:
            raise ValueError('A rede ativa mudou durante a carga; não use esta carga como edição ativa.')
        report={'schema':'neo4j-network-load-1','version':VERSION,'database':database,
            'graph_tag':payload['tag'],'snapshot_sha256':payload['snapshot'],
            'payload_sha256':json_sha(payload),'node_label':NODE_LABEL,'relationship_type':RELATION_TYPE,
            'created_at_utc':datetime.now(timezone.utc).isoformat(),**result,
            'legacy_data_deleted':False,'legacy_constraints_removed':False,
            'gds_projections_created':0,'api_calls_ner_re':0}
        stamp=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
        path=lock.parent/('Carga_Neo4j_'+stamp+'.json');atomic_json(path,report)
        package=lock.parent/('Resumo_Carga_Neo4j_'+stamp+'.zip')
        with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:z.write(path,'carga_neo4j.json')
        print('[NEO4J]',json.dumps(report,ensure_ascii=False));print('[NEO4J] Pacote:',package)
        return {**report,'package':package}
    except (ValueError,RuntimeError):raise
    except Exception as exc:
        raise RuntimeError('Carga interrompida; lotes confirmados permanecem no destino. Diagnóstico: '+json.dumps(_failure(exc))) from None
    finally:
        if driver is not None:driver.close()
        (lock/'owner.json').unlink(missing_ok=True);lock.rmdir()
