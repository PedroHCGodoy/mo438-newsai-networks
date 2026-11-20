"""Inspeção de conexão, esquema e catálogo Neo4j sem mutações no banco."""
from pathlib import Path
from datetime import datetime, timezone
from importlib.metadata import version, PackageNotFoundError
from urllib.parse import urlsplit
import json
import re
import uuid
import zipfile
from redes_construcao import carregar_rede
from re_execucao import atomic_json

VERSION = '1.0.0'
QUERIES = {
    'components': 'CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition',
    'database_counts': 'MATCH (n) RETURN count(n) AS nodes',
    'relationship_count': 'MATCH ()-[r]->() RETURN count(r) AS relationships',
    'existing_networks': '''MATCH (n)
        WHERE n:Entity OR n:NewsAIEntity
        RETURN coalesce(toString(n.graph_tag), '__SEM_GRAPH_TAG__') AS graph_tag,
               labels(n) AS labels, count(n) AS nodes
        ORDER BY nodes DESC LIMIT 100''',
    'constraints': 'SHOW CONSTRAINTS YIELD name, type, entityType, labelsOrTypes, properties RETURN name, type, entityType, labelsOrTypes, properties',
    'indexes': 'SHOW INDEXES YIELD name, type, state, entityType, labelsOrTypes, properties RETURN name, type, state, entityType, labelsOrTypes, properties',
    'target_nodes': 'MATCH (n) WHERE n.graph_tag = $graph_tag RETURN labels(n) AS labels, count(n) AS nodes',
    'target_relationships': 'MATCH ()-[r]->() WHERE r.graph_tag = $graph_tag RETURN type(r) AS type, count(r) AS relationships',
    'gds_version': 'RETURN gds.version() AS version',
    'gds_procedures': "SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'gds.' RETURN name ORDER BY name",
    'gds_functions': "SHOW FUNCTIONS YIELD name WHERE name STARTS WITH 'gds.' RETURN name ORDER BY name",
    'gds_graphs': 'CALL gds.graph.list() YIELD graphName, nodeCount, relationshipCount RETURN graphName, nodeCount, relationshipCount ORDER BY graphName LIMIT 100',
}


def _failure(exc):
    # Não propaga mensagens que possam conter credenciais, endereços ou parâmetros.
    code = getattr(exc, 'code', None)
    if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', code):
        code = None
    return {'error_type': type(exc).__name__, 'neo4j_code': code}


def _read(session, name, **parameters):
    query = QUERIES[name]
    return session.execute_read(lambda tx: [row.data() for row in tx.run(query, **parameters)])


def inspecionar_driver(driver, database, graph_tag):
    """Todas as consultas são fixas e executadas em transações de leitura."""
    driver.verify_connectivity()
    report = {'connection': 'OK', 'database': database, 'target_graph_tag': graph_tag,
              'database_writes': 0, 'schema_writes': 0, 'gds_graphs_created': 0,
              'gds_graphs_removed': 0, 'queries': {}}
    with driver.session(database=database, default_access_mode='READ') as session:
        for name in QUERIES:
            try:
                report['queries'][name] = {'status': 'OK', 'rows': _read(session, name, graph_tag=graph_tag)
                                          if name.startswith('target_') else _read(session, name)}
            except Exception as exc:
                report['queries'][name] = {'status': 'UNAVAILABLE', **_failure(exc)}
    q = report['queries']
    target_counts = [sum(row.get(key, 0) for row in q[name].get('rows', []))
        for name,key in [('target_nodes','nodes'),('target_relationships','relationships')]]
    report['target_has_existing_data'] = any(target_counts)
    names = {row['name'] for name in ['gds_procedures','gds_functions']
             for row in q[name].get('rows', [])}
    report['gds_capabilities'] = {
        'version_query_ok': q['gds_version']['status'] == 'OK',
        'projection': 'gds.graph.project' in names,
        'pagerank': 'gds.pageRank.stream' in names,
        'wcc': any(n.startswith('gds.wcc.') for n in names),
        'louvain': any(n.startswith('gds.louvain.') for n in names),
        'leiden': any(n.startswith('gds.leiden.') for n in names),
    }
    report['inspection_complete'] = all(q[name]['status']=='OK' for name in [
        'components','database_counts','relationship_count','existing_networks',
        'constraints','indexes','target_nodes','target_relationships'])
    report['load_executed'] = False
    return report


def _configuration(root):
    try:
        from dotenv import dotenv_values
    except ImportError:
        raise RuntimeError('Dependência ausente: instale python-dotenv neste ambiente Jupyter.') from None
    path = Path(root)/'.env'
    if not path.is_file():raise FileNotFoundError('Arquivo .env ausente na pasta do projeto.')
    env = dotenv_values(path, interpolate=False)
    uri = env.get('NEO4J_URI') or ''
    user = env.get('NEO4J_USER') or env.get('NEO4J_USERNAME') or ''
    password = env.get('NEO4J_PASSWORD') or ''
    database = env.get('NEO4J_DATABASE') or 'neo4j'
    if not uri or not user or not password:
        raise ValueError('Configure NEO4J_URI, NEO4J_USER (ou NEO4J_USERNAME) e NEO4J_PASSWORD no .env local.')
    try:
        parsed = urlsplit(uri)
        invalid = (parsed.scheme not in ['bolt','bolt+s','bolt+ssc','neo4j','neo4j+s','neo4j+ssc']
                   or not parsed.hostname or parsed.username is not None or parsed.password is not None)
    except ValueError:
        invalid = True
    if invalid:raise ValueError('NEO4J_URI inválida; mantenha usuário e senha em variáveis separadas.')
    return uri, user, password, database


def verificar_ambiente_neo4j(projeto, *, assinatura_rede_esperada=None, driver_factory=None):
    """Confere a rede de entrada e o banco. Não importa, remove ou altera grafos."""
    root = Path(projeto).resolve()
    folder, network = carregar_rede(root)
    if assinatura_rede_esperada and network['snapshot_sha256'] != assinatura_rede_esperada:
        raise ValueError('A rede selecionada difere da versão esperada para esta edição.')
    uri, user, password, database = _configuration(root)
    if driver_factory is None:
        try:
            from neo4j import GraphDatabase
        except ImportError:
            raise RuntimeError('Dependência ausente: instale o driver Python neo4j neste ambiente Jupyter.') from None
        driver_factory = GraphDatabase.driver
    driver = None
    try:
        driver = driver_factory(uri, auth=(user,password), connection_timeout=15,
                                max_transaction_retry_time=5)
        report = inspecionar_driver(driver, database, 'newsai_'+network['snapshot_sha256'][:20])
    except Exception as exc:
        failure = _failure(exc)
        raise RuntimeError('Não foi possível conferir a conexão Neo4j. Verifique se a instância está iniciada, '
            'o banco selecionado e as credenciais locais. Diagnóstico: '+json.dumps(failure)) from None
    finally:
        if driver is not None:driver.close()
    report.update({'schema':'neo4j-environment-check-1','version':VERSION,
        'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'network_snapshot_sha256':network['snapshot_sha256'],
        'expected_network_summary':network['summary'],
        'api_calls_ner_re':0, 'memory_capacity_checked':False,
        'note':'Consulta de inventário apenas; ausência de escrita nesta etapa não confirma compatibilidade da carga.'})
    for package in ['neo4j','pandas','python-dotenv']:
        try:report.setdefault('python_packages',{})[package]=version(package)
        except PackageNotFoundError:report.setdefault('python_packages',{})[package]='NOT_INSTALLED'
    output = root/'resultados/neo4j';output.mkdir(parents=True,exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
    report_file = output/('Conferencia_Neo4j_'+stamp+'.json')
    atomic_json(report_file,report)
    package = output/('Resumo_Ambiente_Neo4j_'+stamp+'.zip')
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:z.write(report_file,'conferencia_neo4j.json')
    summary = {k:report[k] for k in ['connection','database','target_graph_tag','inspection_complete',
        'target_has_existing_data','gds_capabilities','database_writes','load_executed']}
    print('[NEO4J]',json.dumps(summary,ensure_ascii=False))
    for name,result in report['queries'].items():
        if result['status']!='OK':print('[NEO4J] Consulta indisponível:',name,result)
    print('[NEO4J] Pacote:',package)
    return {**summary,'package':package,'report':report_file}
