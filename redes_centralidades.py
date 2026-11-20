"""Conectividade, força e PageRank ponderado das entidades de uma rede versionada."""
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import shutil
import tempfile
import time
import uuid
import zipfile
import numpy as np
import pandas as pd
from redes_distancias import carregar_estrutura
from redes_projecoes import verificar_projecao, valores_esperados
from re_consolidacao import sha, json_sha, write_csv, validate_manifest
from re_execucao import atomic_json
from neo4j_integracao import _configuration, _failure

VERSION = '1.0.0'
PAGERANK_CONFIG = {'relationshipWeightProperty': 'weight', 'maxIterations': 100,
                   'dampingFactor': 0.85, 'tolerance': 1e-7, 'concurrency': 4}
TYPE_COLORS = {'PESSOA': '#4C78A8', 'ORGANIZACAO': '#F58518', 'LOCAL': '#54A24B'}
TYPE_NAMES = {'PESSOA': 'Pessoa', 'ORGANIZACAO': 'Organização', 'LOCAL': 'Local'}
RANK_METRICS = ['neighbor_degree', 'typed_degree', 'weighted_strength', 'pagerank']


def calcular_conectividade(nodes, edges, simple, structural):
    """Conta arestas, vizinhos e ocorrências sem multiplicação de entradas e saídas."""
    f = nodes.copy()
    f['entity_group_id'] = pd.to_numeric(f.entity_group_id, errors='raise').astype('int64')
    if f.empty or not f.entity_group_id.is_unique:
        raise ValueError('Universo de nós vazio ou duplicado.')
    f = f.sort_values('entity_group_id').set_index('entity_group_id')
    e = edges.copy()
    for key in ['source_id', 'target_id', 'weight']:
        values = pd.to_numeric(e[key], errors='raise')
        if not np.isfinite(values).all() or not values.eq(np.floor(values)).all():
            raise ValueError('Extremo ou peso não inteiro ou não finito.')
        e[key] = values.astype('int64')
    if (not e.edge_id.is_unique or e.source_id.eq(e.target_id).any() or e.weight.le(0).any()
            or not set(e.source_id).union(e.target_id).issubset(f.index)):
        raise ValueError('Aresta duplicada, autolaço, peso não positivo ou extremo desconhecido.')
    for direction, column in [('in', 'target_id'), ('out', 'source_id')]:
        grouped = e.groupby(column)
        f[direction + '_typed_degree'] = grouped.size().reindex(f.index, fill_value=0).astype('int64')
        f[direction + '_strength'] = grouped.weight.sum().reindex(f.index, fill_value=0).astype('int64')
    directed_pairs = e[['source_id', 'target_id']].drop_duplicates()
    for direction, column in [('in', 'target_id'), ('out', 'source_id')]:
        f[direction + '_neighbors'] = directed_pairs.groupby(column).size().reindex(f.index, fill_value=0).astype('int64')
    pair_set = {(min(a, b), max(a, b)) for a, b in directed_pairs.itertuples(index=False, name=None)}
    observed = [(int(a), int(b)) for a, b in zip(simple.source_id, simple.target_id)]
    if len(set(observed)) != len(observed) or set(observed) != pair_set:
        raise ValueError('Arestas dirigidas e projeção simples incompatíveis.')
    neighbors = pd.concat([simple.source_id.astype('int64'), simple.target_id.astype('int64')]).value_counts()
    f['neighbor_degree'] = neighbors.reindex(f.index, fill_value=0).astype('int64')
    s = structural.copy()
    s['entity_group_id'] = s.entity_group_id.astype('int64')
    if not s.entity_group_id.is_unique or set(s.entity_group_id) != set(f.index):
        raise ValueError('Universo estrutural incompatível.')
    reference = s.set_index('entity_group_id').degree.astype('int64').reindex(f.index)
    if not f.neighbor_degree.equals(reference):
        raise ValueError('Graus de vizinhança diferentes da caracterização estrutural.')
    f['typed_degree'] = f.in_typed_degree + f.out_typed_degree
    f['weighted_strength'] = f.in_strength + f.out_strength
    f['neighbor_degree_centrality'] = f.neighbor_degree / (len(f) - 1) if len(f) > 1 else 0.0
    totals = {'nodes': len(f), 'typed_directed_edges': len(e), 'undirected_pairs': len(simple),
              'distinct_directed_pairs': len(directed_pairs), 'record_weight_sum': int(e.weight.sum()),
              'in_typed_degree_sum': int(f.in_typed_degree.sum()),
              'out_typed_degree_sum': int(f.out_typed_degree.sum()),
              'typed_degree_sum': int(f.typed_degree.sum()), 'neighbor_degree_sum': int(f.neighbor_degree.sum()),
              'in_strength_sum': int(f.in_strength.sum()), 'out_strength_sum': int(f.out_strength.sum()),
              'weighted_strength_sum': int(f.weighted_strength.sum()),
              'zero_out_strength_nodes': int(f.out_strength.eq(0).sum())}
    if (totals['in_typed_degree_sum'] != len(e) or totals['out_typed_degree_sum'] != len(e)
            or totals['in_strength_sum'] != totals['record_weight_sum']
            or totals['out_strength_sum'] != totals['record_weight_sum']
            or totals['neighbor_degree_sum'] != 2 * len(simple)):
        raise ValueError('Identidades globais de graus ou forças não atendidas.')
    return f.reset_index(), totals


def pagerank_referencia(nodes, edges, *, damping=0.85, tolerance=1e-12, max_iterations=1000):
    """Iteração independente na escala nativa do GDS, sem redistribuição de sumidouros."""
    ids = list(map(int, nodes))
    if len(set(ids)) != len(ids):
        raise ValueError('IDs duplicados no PageRank de referência.')
    lookup = {x: i for i, x in enumerate(ids)}
    source = np.array([lookup[int(x)] for x in edges.source_id], dtype=np.int64)
    target = np.array([lookup[int(x)] for x in edges.target_id], dtype=np.int64)
    weight = edges.weight.to_numpy(dtype=float)
    out = np.bincount(source, weights=weight, minlength=len(ids))
    transition = weight / out[source]
    score = np.ones(len(ids))
    for iteration in range(1, max_iterations + 1):
        updated = (1 - damping) + damping * np.bincount(target, weights=score[source] * transition, minlength=len(ids))
        delta = float(np.max(np.abs(updated - score)))
        score = updated
        if delta < tolerance:
            return score, {'iterations': iteration, 'max_step_change': delta,
                           'tolerance': tolerance, 'converged': True}
    raise ValueError('A referência local de PageRank não convergiu.')


def validar_pagerank(frame, raw, edges):
    observed = raw.copy()
    if observed.empty or not observed.entity_group_id.is_unique:
        raise ValueError('PageRank vazio ou com IDs duplicados.')
    observed['entity_group_id'] = observed.entity_group_id.astype('int64')
    if set(observed.entity_group_id) != set(frame.entity_group_id):
        raise ValueError('Universo do PageRank diferente da rede.')
    values = observed.set_index('entity_group_id').pagerank.reindex(frame.entity_group_id).to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any() or values.sum() <= 0:
        raise ValueError('Escores PageRank inválidos.')
    reference, convergence = pagerank_referencia(frame.entity_group_id, edges)
    difference = np.abs(values - reference)
    if not np.allclose(values, reference, rtol=1e-5, atol=1e-5):
        raise ValueError('PageRank GDS diverge da referência local. Confira configuração, versão e convergência.')
    result = frame.copy()
    result['pagerank'] = values
    result['pagerank_share'] = values / values.sum()
    proof = {'all_nodes_compared': True, 'reference': convergence,
             'max_absolute_difference': float(difference.max()),
             'relative_l1_difference': float(difference.sum() / reference.sum()),
             'comparison_rtol': 1e-5, 'comparison_atol': 1e-5,
             'raw_score_sum': float(values.sum()), 'share_sum': float(result.pagerank_share.sum()),
             'gds_stream_reports_iteration_count': False}
    return result, proof


def executar_pagerank(session, name):
    def query(q, **params):
        return session.execute_read(lambda tx: [row.data() for row in tx.run(q, **params)])
    version = query('RETURN gds.version() AS version')
    estimate = query('''CALL gds.pageRank.stream.estimate($name, $config)
        YIELD nodeCount, relationshipCount, bytesMin, bytesMax, requiredMemory
        RETURN nodeCount, relationshipCount, bytesMin, bytesMax, requiredMemory''', name=name, config=PAGERANK_CONFIG)
    clock = time.perf_counter()
    rows = query('''CALL gds.pageRank.stream($name, $config) YIELD nodeId, score
        RETURN gds.util.asNode(nodeId).entity_group_id AS entity_group_id, score AS pagerank''',
        name=name, config=PAGERANK_CONFIG)
    elapsed = time.perf_counter() - clock
    print(f'[CENTRALIDADES] PageRank: {len(rows):,} nós; {elapsed:.2f}s.', flush=True)
    return pd.DataFrame(rows), {'memory_estimate': estimate, 'pagerank_seconds': elapsed,
                               'gds_version': version[0]['version'],
                               'configuration': PAGERANK_CONFIG}


def gerar_rankings(frame):
    f = frame.copy()
    for metric in RANK_METRICS:
        f['rank_' + metric] = f[metric].rank(method='min', ascending=False).astype('int64')
    ranks = []
    for metric in RANK_METRICS:
        ordered = f.sort_values([metric, 'entity_group_id'], ascending=[False, True], kind='stable')
        for scope, part in [('ALL', ordered)] + [(label, ordered.loc[ordered.ent_label.eq(label)]) for label in TYPE_COLORS]:
            part = part.head(20).copy()
            part.insert(0, 'metric', metric)
            part.insert(1, 'scope', scope)
            part.insert(2, 'display_order', np.arange(1, len(part) + 1))
            ranks.append(part)
    return f, pd.concat(ranks, ignore_index=True)


def gerar_figuras(folder, frame):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    import textwrap
    plt.rcParams.update({'font.size': 10, 'svg.fonttype': 'none', 'pdf.fonttype': 42})
    catalog = []
    for metric, xlabel, objective in [
        ('neighbor_degree', 'Vizinhos distintos (projeção simples)', 'Identificar entidades com maior diversidade de conexões diretas.'),
        ('weighted_strength', 'Força total (ocorrências relacionais incidentes)', 'Identificar entidades com maior frequência relacional agregada.'),
        ('pagerank', 'PageRank ponderado (escala nativa do GDS)', 'Identificar entidades favorecidas pela estrutura dirigida e ponderada das relações.')]:
        fig, axes = plt.subplots(1, 3, figsize=(15, 6.2))
        for ax, label in zip(axes, ['ORGANIZACAO', 'PESSOA', 'LOCAL']):
            part = frame.loc[frame.ent_label.eq(label)].sort_values(
                [metric, 'entity_group_id'], ascending=[False, True]).head(5).iloc[::-1]
            names = ['\n'.join(textwrap.wrap(str(name), 25)) for name in part.entity_group_name]
            ax.barh(np.arange(len(part)), part[metric], color=TYPE_COLORS[label])
            ax.set_yticks(np.arange(len(part)), names)
            ax.set_title(TYPE_NAMES[label])
            ax.set_xlabel(xlabel, fontsize=9)
            ax.grid(axis='x', alpha=.18)
            if metric != 'pagerank':
                ax.xaxis.set_major_formatter(FuncFormatter(lambda v, pos: f'{v:,.0f}'.replace(',', '.')))
        fig.suptitle('Entidades em destaque por tipo — ' + xlabel.split(' (')[0])
        fig.tight_layout()
        name = 'top5_por_tipo_' + metric
        for ext in ['svg', 'png', 'pdf']:
            fig.savefig(folder / f'{name}.{ext}', dpi=200)
        plt.close(fig)
        catalog.append({'figure': name, 'objective': objective,
            'caption': 'Cinco entidades por tipo, ordenadas pela métrica; empates por ID. Escalas horizontais por painel. '
                       'A direção das relações semânticas e a cobertura de extração condicionam a interpretação.'})
    return pd.DataFrame(catalog)


def analisar_centralidades(projeto, *, executar_gds=False, assinatura_rede_esperada=None, driver_factory=None):
    root = Path(projeto).resolve()
    s_folder, s_meta, p_folder, p_meta, n_folder, n_meta = carregar_estrutura(root)
    if assinatura_rede_esperada and n_meta['snapshot_sha256'] != assinatura_rede_esperada:
        raise ValueError('A rede ativa difere da edição esperada.')
    if not executar_gds:
        result = {'mode': 'DRY_RUN', 'nodes': n_meta['summary']['nodes'],
                  'typed_directed_edges': n_meta['summary']['edges'],
                  'graph_name': p_meta['graph_names']['directed'], 'neo4j_connections': 0, 'api_calls': 0,
                  'pagerank_configuration': PAGERANK_CONFIG, 'independent_pagerank_verification': True}
        print('[CENTRALIDADES]', json.dumps(result, ensure_ascii=False))
        return result
    spec = {'schema': 'entity-centralities-1', 'version': VERSION, 'code_sha256': sha(Path(__file__)),
            'network_snapshot_sha256': n_meta['snapshot_sha256'],
            'projection_snapshot_sha256': p_meta['snapshot_sha256'],
            'structural_snapshot_sha256': s_meta['snapshot_sha256'], 'pagerank_configuration': PAGERANK_CONFIG,
            'pagerank_comparison': {'rtol': 1e-5, 'atol': 1e-5}}
    signature = json_sha(spec)
    base = root / 'resultados/centralidades'
    base.mkdir(parents=True, exist_ok=True)
    target = base / signature[:20]
    lock = base / 'execucao.lock'
    try:
        lock.mkdir()
    except FileExistsError:
        raise RuntimeError('Outra análise de centralidades pode estar ativa. Confira o bloqueio.') from None
    driver, temp = None, None
    try:
        if target.exists():
            meta = validate_manifest(target)
            if meta['snapshot_sha256'] != signature:
                raise ValueError('Colisão de assinatura de centralidades.')
            print('[CENTRALIDADES] Resultado completo conferido; sem repetir algoritmos.')
        else:
            nodes = pd.read_csv(n_folder / 'nos.csv.gz', keep_default_na=False)
            edges = pd.read_csv(n_folder / 'arestas.csv.gz', keep_default_na=False)
            simple = pd.read_csv(p_folder / 'simples_nao_dirigida.csv.gz')
            structural = pd.read_csv(s_folder / 'metricas_nos.csv.gz')
            frame, summary = calcular_conectividade(nodes, edges, simple, structural)
            uri, user, password, database = _configuration(root)
            if driver_factory is None:
                from neo4j import GraphDatabase
                driver_factory = GraphDatabase.driver
            driver = driver_factory(uri, auth=(user, password), connection_timeout=15, max_transaction_retry_time=10)
            driver.verify_connectivity()
            with driver.session(database=database) as session:
                verificar_projecao(session, p_meta['graph_names']['directed'], database,
                    'newsai_' + n_meta['snapshot_sha256'][:20], set(map(int, frame.entity_group_id)),
                    valores_esperados('directed', edges, None))
                raw, execution = executar_pagerank(session, p_meta['graph_names']['directed'])
            frame, proof = validar_pagerank(frame, raw, edges)
            frame, ranks = gerar_rankings(frame)
            correlations = frame[RANK_METRICS + ['relation_news_count', 'mention_count']].corr(method='spearman')
            correlations.index.name = 'metric'
            summary.update({'pagerank_sum': float(frame.pagerank.sum()),
                'pagerank_share_sum': float(frame.pagerank_share.sum()), 'pagerank_max': float(frame.pagerank.max()),
                'all_pagerank_nodes_verified': True, 'pagerank_gds_seconds': execution['pagerank_seconds'],
                'betweenness_computed': False, 'closeness_computed': False, 'community_detection_computed': False,
                'api_calls': 0, 'database_writes': 0})
            temp = Path(tempfile.mkdtemp(prefix='.calculando_', dir=base))
            write_csv(temp, 'centralidades_nos.csv.gz', frame)
            write_csv(temp, 'rankings.csv', ranks)
            write_csv(temp, 'correlacoes_spearman.csv', correlations.reset_index())
            write_csv(temp, 'resumo_metricas.csv', pd.DataFrame([{'metric': k, 'value': v} for k, v in summary.items()]))
            write_csv(temp, 'catalogo_figuras.csv', gerar_figuras(temp, frame))
            atomic_json(temp / 'execucao_gds.json', execution)
            atomic_json(temp / 'verificacao_pagerank.json', proof)
            import matplotlib
            atomic_json(temp / 'ambiente.json', {'numpy': np.__version__, 'pandas': pd.__version__,
                'matplotlib': matplotlib.__version__, 'neo4j_database': database})
            (temp / 'LEIA_ME.md').write_text('# Centralidades das entidades\n\n'
                'Grau de vizinhança conta vizinhos distintos. Grau por arestas conta relações tipadas agregadas. '
                'Força soma ocorrências relacionais, podendo incluir várias ocorrências da mesma notícia. '
                'PageRank usa direção e pesos com amortecimento 0,85, até 100 iterações e tolerância 1e-7. '
                'A coluna pagerank preserva a escala nativa; pagerank_share divide pelo total observado. '
                'Ela não é a probabilidade estacionária de uma variante com redistribuição de sumidouros.\n\n'
                'A direção de cada rótulo semântico condiciona os escores. Protagonismo estrutural não demonstra '
                'influência social ou causalidade. Correlações são descritivas, sem testes de significância. '
                'Nomes são rótulos; entity_group_id é a chave para cruzar as notícias nas tabelas da rede. '
                'A cobertura de extração e as pendências de resolução de entidades devem acompanhar a interpretação.\n', encoding='utf-8')
            meta = {**spec, 'snapshot_sha256': signature, 'summary': summary,
                    'created_at_utc': datetime.now(timezone.utc).isoformat(),
                    'outputs_sha256': {p.name: sha(p) for p in sorted(temp.iterdir())}}
            atomic_json(temp / 'manifesto.json', meta)
            validate_manifest(temp)
            if carregar_estrutura(root)[1]['snapshot_sha256'] != s_meta['snapshot_sha256']:
                raise ValueError('As entradas ativas mudaram durante a análise.')
            os.rename(temp, target)
            temp = None
        atomic_json(base / 'atual.json', {'folder': target.name, 'snapshot_sha256': signature})
        package = base / f'Resumo_Centralidades_{signature[:12]}_{uuid.uuid4().hex[:6]}.zip'
        with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as z:
            for path in sorted(target.iterdir()):
                z.write(path, path.name)
        print('[CENTRALIDADES]', json.dumps(meta['summary'], ensure_ascii=False))
        print('[CENTRALIDADES] Pacote:', package)
        return {**meta['summary'], 'output_directory': target, 'package': package, 'snapshot_sha256': signature}
    except (ValueError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError('Análise interrompida. Confira dependências e GDS. Diagnóstico: ' + json.dumps(_failure(exc))) from None
    finally:
        if driver is not None:
            driver.close()
        if temp is not None:
            shutil.rmtree(temp, ignore_errors=True)
        lock.rmdir()


def carregar_centralidades(projeto):
    root = Path(projeto).resolve()
    _, s_meta, _, p_meta, _, n_meta = carregar_estrutura(root)
    base = root / 'resultados/centralidades'
    pointer = json.loads((base / 'atual.json').read_text(encoding='utf-8'))
    if Path(pointer['folder']).name != pointer['folder']:
        raise ValueError('Apontador de centralidades inválido.')
    folder = base / pointer['folder']
    meta = validate_manifest(folder)
    if (pointer['snapshot_sha256'] != meta['snapshot_sha256'] or
        n_meta['snapshot_sha256'] != meta['network_snapshot_sha256'] or
        p_meta['snapshot_sha256'] != meta['projection_snapshot_sha256'] or
        s_meta['snapshot_sha256'] != meta['structural_snapshot_sha256']):
        raise ValueError('As centralidades ativas pertencem a outra versão das entradas.')
    return folder, meta
