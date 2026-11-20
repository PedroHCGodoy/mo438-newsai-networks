"""Comparação estrutural das redes por fonte com conferência independente."""
from pathlib import Path
from datetime import datetime, timezone
from itertools import combinations
import json
import shutil
import tempfile
import time
import uuid
import zipfile
import pandas as pd
from redes_fontes import FONTES
from redes_construcao import carregar_rede
from redes_projecoes import verificar_projecao, valores_esperados, EXISTS
from redes_estrutural import executar_algoritmos, resumir_metricas, calcular_referencia
from neo4j_integracao import _configuration, _failure
from re_consolidacao import sha, json_sha, write_csv, validate_manifest
from re_execucao import atomic_json

VERSION = '1.0.0'
CORES = {'cnn': 'tab:blue', 'folha': 'tab:orange', 'g1': 'tab:green'}
PROJETAR = '''UNWIND $rows AS row
MATCH (source:NewsAIEntity {graph_tag:$tag, entity_group_id:row.source_id})
MATCH (target:NewsAIEntity {graph_tag:$tag, entity_group_id:row.target_id})
WITH gds.graph.project($name, source, target,
 {sourceNodeProperties:{entity_group_id:source.entity_group_id},
  targetNodeProperties:{entity_group_id:target.entity_group_id},
  relationshipType:'SOURCE_STRUCTURAL', relationshipProperties:{weight:1.0, distance:1.0}},
 {readConcurrency:4, undirectedRelationshipTypes:['SOURCE_STRUCTURAL']}) AS g
RETURN g.graphName AS graphName, g.nodeCount AS nodeCount, g.relationshipCount AS relationshipCount'''


def query(session, statement, **params):
    return session.execute_read(lambda tx: [r.data() for r in tx.run(statement, **params)])


def carregar_fontes(projeto, assinatura_rede_esperada=None):
    root = Path(projeto).resolve()
    if root.name == 'PROJECT_EXTRACAO':
        raise ValueError('Execute no projeto de análise.')
    base = root/'dados/processados/redes/fontes'
    pointer = json.loads((base/'atual.json').read_text(encoding='utf-8'))
    if Path(pointer['folder']).name != pointer['folder']:
        raise ValueError('Apontador de redes por fonte inválido.')
    folder = base/pointer['folder']; meta = validate_manifest(folder)
    if meta['schema'] != 'source-networks-1' or pointer['snapshot_sha256'] != meta['snapshot_sha256']:
        raise ValueError('Edição de redes por fonte incompatível.')
    _, rede = carregar_rede(root)
    if meta['network_snapshot_sha256'] != rede['snapshot_sha256']:
        raise ValueError('As redes por fonte pertencem a outra edição global.')
    if assinatura_rede_esperada and rede['snapshot_sha256'] != assinatura_rede_esperada:
        raise ValueError('A rede ativa difere da edição esperada.')
    return folder, meta


def comparar_conjuntos(conjuntos):
    linhas = []
    for a, b in combinations(conjuntos, 2):
        for tipo in conjuntos[a]:
            x, y = conjuntos[a][tipo], conjuntos[b][tipo]
            inter, uniao = len(x & y), len(x | y)
            linhas.append({'source_a': a, 'source_b': b, 'element_type': tipo,
                'size_a': len(x), 'size_b': len(y), 'intersection': inter, 'union': uniao,
                'jaccard': inter/uniao if uniao else None,
                'share_a_in_b': inter/len(x) if x else None,
                'share_b_in_a': inter/len(y) if y else None})
    return pd.DataFrame(linhas)


def reciprocidade(arestas):
    pares = {(int(a), int(b)) for a, b in zip(arestas.source_id, arestas.target_id)}
    if any(a == b for a, b in pares):
        raise ValueError('Autolaço na reciprocidade.')
    reciprocos = sum((b, a) in pares for a, b in pares)
    return {'distinct_directed_pairs': len(pares), 'reciprocated_directed_pairs': reciprocos,
            'reciprocal_dyads': reciprocos//2, 'directed_pair_reciprocity': reciprocos/len(pares) if pares else None}


def verificar_metricas(raw, nodes, simple):
    resultado = resumir_metricas(raw, len(simple))
    f = resultado[0]
    referencia = calcular_referencia(set(nodes.entity_group_id.astype(int)), zip(simple.source_id, simple.target_id)).set_index('entity_group_id').sort_index()
    observado = f.set_index('entity_group_id').sort_index()
    for col in ['degree', 'triangle_count', 'component_id']:
        if not observado[col].equals(referencia[col]):
            raise ValueError('Divergência entre GDS e conferência independente: ' + col)
    return resultado


def figuras(folder, tabela, distribuicoes, sobreposicao):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({'font.size': 10, 'svg.fonttype': 'none', 'pdf.fonttype': 42})
    catalogo = []
    def salvar(fig, nome, objetivo, legenda):
        fig.tight_layout()
        for ext in ['svg', 'png', 'pdf']:
            arquivo = nome+'.'+ext; fig.savefig(folder/arquivo, dpi=220, bbox_inches='tight')
            catalogo.append({'file': arquivo, 'objective': objetivo, 'caption': legenda})
        plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for slug, d in distribuicoes.items():
        positivo = d.loc[d.degree.gt(0)]
        ax.plot(positivo.degree, positivo.ccdf_ge_k, '.', markersize=4, color=CORES[slug], label=FONTES[slug])
    ax.set(xscale='log', yscale='log', xlabel='Grau k — vizinhos distintos', ylabel='P(K ≥ k)')
    ax.legend(frameon=False); ax.grid(alpha=.2, which='both')
    salvar(fig, '01_graus_fontes', 'Comparar a heterogeneidade dos graus.',
           'CCDFs empíricas das projeções simples não dirigidas no mesmo período. Eixos logarítmicos; não são testes de lei de potência. As diferenças de cobertura e tamanho permanecem relevantes.')
    fig, axes = plt.subplots(2, 2, figsize=(10, 7))
    for ax, (campo, titulo) in zip(axes.flat, [('mean_degree', 'Grau médio'), ('density', 'Densidade'),
            ('largest_component_share', 'Fração de nós na maior componente'),
            ('mean_local_clustering_degree_ge_two', 'Clusterização local média — grau ≥ 2')]):
        ax.bar([FONTES[k] for k in tabela.source_key], pd.to_numeric(tabela[campo], errors='coerce'), color=[CORES[k] for k in tabela.source_key])
        ax.set_title(titulo); ax.tick_params(axis='x', labelrotation=15)
        if campo in ['density']: ax.ticklabel_format(axis='y', style='sci', scilimits=(0, 0))
        ax.grid(axis='y', alpha=.2)
    salvar(fig, '02_metricas_fontes', 'Comparar conectividade e fechamento das vizinhanças.',
           'Métricas na projeção simples não dirigida. A média de clusterização mostrada considera nós de grau ≥ 2; a transitividade é informada separadamente na tabela. Densidade não controla diferenças de tamanho.')
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.4))
    slugs = list(FONTES)
    for ax, tipo, titulo in zip(axes, ['nodes', 'undirected_pairs'], ['Entidades compartilhadas', 'Pares não dirigidos compartilhados']):
        matrix = np.eye(3)
        for row in sobreposicao.loc[sobreposicao.element_type.eq(tipo)].itertuples():
            i, j = slugs.index(row.source_a), slugs.index(row.source_b); matrix[i, j] = matrix[j, i] = row.jaccard
        im = ax.imshow(matrix, vmin=0, vmax=1, cmap='Blues')
        ax.set_xticks(range(3), [FONTES[k] for k in slugs], rotation=25, ha='right')
        ax.set_yticks(range(3), [FONTES[k] for k in slugs]); ax.set_title(titulo)
        for i in range(3):
            for j in range(3): ax.text(j, i, f'{matrix[i,j]:.3f}', ha='center', va='center', color='white' if matrix[i,j]>.6 else 'black')
        fig.colorbar(im, ax=ax, fraction=.046, pad=.04, label='Jaccard')
    salvar(fig, '03_sobreposicao_fontes', 'Examinar os elementos comuns e exclusivos das fontes.',
           'Jaccard é a interseção dividida pela união dos conjuntos. Nós usam IDs globais resolvidos; pares não dirigidos ignoram rótulos e direção. A diagonal vale 1. Similaridade estrutural não comprova concordância editorial.')
    return pd.DataFrame(catalogo)


def comparar_estrutura_fontes(projeto, *, executar_gds=False, assinatura_rede_esperada=None,
                             assinatura_fontes_esperada=None, driver_factory=None):
    root = Path(projeto).resolve(); origem, meta = carregar_fontes(root, assinatura_rede_esperada)
    if assinatura_fontes_esperada and meta['snapshot_sha256'] != assinatura_fontes_esperada:
        raise ValueError('As redes por fonte diferem da edição esperada.')
    if not executar_gds:
        return {'mode': 'DRY_RUN', 'sources': list(FONTES.values()), 'start_date': meta['start_date'],
                'end_date': meta['end_date'], 'algorithms': ['degree', 'triangleCount', 'wcc'],
                'neo4j_connections': 0, 'database_writes': 0, 'api_calls': 0, 'files_written': 0}
    spec = {'schema': 'source-structural-comparison-1', 'version': VERSION, 'code_sha256': sha(Path(__file__)),
            'source_networks_snapshot_sha256': meta['snapshot_sha256'], 'network_snapshot_sha256': meta['network_snapshot_sha256'],
            'structural_code_sha256': sha(Path(resumir_metricas.__code__.co_filename)),
            'projection_code_sha256': sha(Path(verificar_projecao.__code__.co_filename)),
            'start_date': meta['start_date'], 'end_date': meta['end_date'], 'concurrency': 4}
    assinatura = json_sha(spec); base = root/'resultados/comparacao_fontes/estrutural';base.mkdir(parents=True, exist_ok=True)
    destino = base/assinatura[:20]; lock = base/'analise.lock'
    try: lock.mkdir()
    except FileExistsError: raise RuntimeError('Comparação pode estar ativa. Confira o bloqueio antes de retomar.') from None
    driver = None; temp = None
    try:
        if destino.exists():
            salvo = validate_manifest(destino)
            if salvo['snapshot_sha256'] != assinatura: raise ValueError('Assinatura de resultados incompatível.')
            resumo = salvo['summary']
        else:
            uri, user, password, database = _configuration(root)
            if driver_factory is None:
                from neo4j import GraphDatabase
                driver_factory = GraphDatabase.driver
            driver = driver_factory(uri, auth=(user, password), connection_timeout=15, max_transaction_retry_time=10)
            driver.verify_connectivity()
            temp = Path(tempfile.mkdtemp(prefix='.comparando_', dir=base))
            resumos = []; sets = {}; distribuicoes = {}; execucao = {}; nomes = {}
            with driver.session(database=database) as session:
                gds_version = query(session, 'RETURN gds.version() AS version')
                for slug, fonte in FONTES.items():
                    def ler(nome): return pd.read_csv(origem/(slug+'_'+nome), dtype=str, keep_default_na=False)
                    nos, simples, arestas = ler('nos.csv.gz'), ler('simples_nao_dirigida.csv.gz'), ler('arestas.csv.gz')
                    ids = set(nos.entity_group_id.astype(int)); nome = 'newsai_fontes_'+meta['snapshot_sha256'][:12]+'_'+slug+'_struct_'+assinatura[:8]
                    tag = 'newsai_'+meta['network_snapshot_sha256'][:20]; nomes[slug] = nome
                    existe = query(session, EXISTS, name=nome)[0]['exists']
                    if not existe:
                        linhas = [{'source_id': int(a), 'target_id': int(b)} for a, b in zip(simples.source_id, simples.target_id)]
                        session.run(PROJETAR, rows=linhas, tag=tag, name=nome).consume()
                    info = verificar_projecao(session, nome, database, tag, ids, valores_esperados('structural', arestas, simples))
                    raw, estimates, tempos = executar_algoritmos(session, nome)
                    f, componentes, graus, tamanhos, clustering, metricas = verificar_metricas(raw, nos, simples)
                    nos['entity_group_id'] = nos.entity_group_id.astype(int)
                    f = f.merge(nos[['entity_group_id', 'entity_group_name', 'ent_label']], on='entity_group_id', validate='one_to_one')
                    fonte_base = next(x for x in meta['summary']['networks'] if x['source_key'] == slug)
                    total = {**fonte_base, **metricas, **reciprocidade(arestas), 'independent_topology_verified': True}
                    resumos.append(total); distribuicoes[slug] = graus
                    for arquivo, tabela in [('metricas_nos.csv.gz', f), ('componentes.csv', componentes),
                        ('distribuicao_graus.csv', graus), ('tamanhos_componentes.csv', tamanhos), ('clusterizacao.csv', clustering)]:
                        write_csv(temp, slug+'_'+arquivo, tabela)
                    sets[slug] = {'nodes': ids,
                        'undirected_pairs': {tuple(sorted((int(a), int(b)))) for a,b in zip(simples.source_id, simples.target_id)},
                        'directed_pairs': {(int(a), int(b)) for a,b in zip(arestas.source_id, arestas.target_id)},
                        'typed_directed_edges': set(arestas.edge_id)}
                    execucao[slug] = {'projection': info, 'projection_reused': bool(existe), 'estimates': estimates, 'algorithm_times_s': tempos}
                    print('[COMPARAÇÃO]', json.dumps(total, ensure_ascii=False), flush=True)
            tabela = pd.DataFrame(resumos); sobreposicao = comparar_conjuntos(sets)
            write_csv(temp, 'comparacao_estrutural.csv', tabela); write_csv(temp, 'sobreposicao_fontes.csv', sobreposicao)
            write_csv(temp, 'catalogo_figuras.csv', figuras(temp, tabela, distribuicoes, sobreposicao))
            atomic_json(temp/'execucao_gds.json', {'database': database, 'gds_version': gds_version, 'graph_names': nomes, 'runs': execucao})
            resumo = {'networks': resumos, 'overlap_rows': len(sobreposicao), 'figure_files': 9,
                'all_node_metrics_independently_verified': True, 'database_writes': 0, 'api_calls': 0,
                'global_network_modified': False, 'community_detection_computed': False, 'distance_metrics_computed': False}
            (temp/'LEIA_ME.md').write_text(
                '# Comparação estrutural\n\nGraus, componentes e triângulos foram calculados no GDS em projeções '
                'simples não dirigidas com peso unitário e confrontados integralmente com uma implementação independente. '
                'As projeções derivam das tabelas por fonte, usando nós identificados na edição global carregada no Neo4j. '
                'Nenhum nó ou relacionamento persistente foi criado ou alterado. As projeções GDS são objetos em memória.\n\n'
                'A reciprocidade usa pares dirigidos distintos, ignorando rótulos e pesos. Ela é a fração de pares que '
                'possuem o par reverso. Rótulos inversos e a expansão de relações podem elevar essa medida; '
                'ela não é evidência de reciprocidade social ou editorial.\n\n'
                'A média principal de clusterização usa grau ≥ 2. A média de todos os nós inclui zeros para grau < 2. '
                'A transitividade é 3T dividido pelas triplas conectadas. A densidade é 2M/[N(N−1)]. '
                'A maior componente é escolhida por tamanho e, em empate, pelo menor ID canônico.\n\n'
                'As diferenças de volume, composição e cobertura de RE permanecem limitações. Não se conclui que '
                'maior número de nós ou arestas implica maior diversidade, qualidade ou complexidade jornalística. '
                'As figuras de graus são descritivas; não ajustam lei de potência.\n', encoding='utf-8')
            atomic_json(temp/'manifesto.json', {**spec, 'snapshot_sha256': assinatura, 'summary': resumo,
                'created_at_utc': datetime.now(timezone.utc).isoformat(),
                'outputs_sha256': {p.name: sha(p) for p in sorted(temp.iterdir())}})
            validate_manifest(temp); temp.rename(destino);temp = None
        atomic_json(base/'atual.json', {'folder': destino.name, 'snapshot_sha256': assinatura})
        pacote = base/('Resumo_Comparacao_Estrutural_'+assinatura[:12]+'_'+uuid.uuid4().hex[:6]+'.zip')
        with zipfile.ZipFile(pacote, 'w', zipfile.ZIP_DEFLATED) as z:
            for p in sorted(destino.iterdir()): z.write(p, p.name)
        print('[COMPARAÇÃO] Pacote:', pacote)
        return {**resumo, 'output_directory': destino, 'package': pacote, 'snapshot_sha256': assinatura}
    except Exception as exc:
        print('[COMPARAÇÃO] FALHA:', json.dumps(_failure(exc)))
        raise RuntimeError('Comparação não concluída. Confira o código da falha; os dados científicos de entrada permanecem preservados.') from None
    finally:
        try:
            if driver is not None: driver.close()
        finally:
            if temp is not None and temp.exists(): shutil.rmtree(temp)
            lock.rmdir()
