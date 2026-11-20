"""Detecção ponderada de comunidades, comparação de partições e auditoria topológica."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
from itertools import combinations
import json
import math
import os
import shutil
import tempfile
import time
import uuid
import zipfile
import numpy as np
import pandas as pd
from redes_distancias import carregar_estrutura
from redes_centralidades import carregar_centralidades, TYPE_COLORS, TYPE_NAMES
from redes_projecoes import verificar_projecao, valores_esperados
from re_consolidacao import sha, json_sha, write_csv, validate_manifest
from re_execucao import atomic_json
from neo4j_integracao import _configuration, _failure

VERSION = '1.0.0'


def configuracoes(sementes):
    seeds = list(sementes)
    if (not seeds or len(set(seeds)) != len(seeds) or
            any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in seeds)):
        raise ValueError('Informe sementes inteiras não negativas, distintas e não vazias.')
    common = {'relationshipWeightProperty': 'weight', 'tolerance': 1e-4,
              'consecutiveIds': True, 'includeIntermediateCommunities': False, 'concurrency': 1}
    runs = {'louvain': {'algorithm': 'louvain', 'config': {**common, 'maxLevels': 20, 'maxIterations': 20}}}
    for seed in seeds:
        runs[f'leiden_seed_{seed}'] = {'algorithm': 'leiden', 'config': {
            **common, 'maxLevels': 10, 'gamma': 1.0, 'theta': .01, 'randomSeed': seed}}
    return runs


def canonizar_particao(raw, node_ids):
    f = raw.copy()
    for key in ['entity_group_id', 'community_id']:
        values = pd.to_numeric(f[key], errors='raise')
        if not np.isfinite(values).all() or not values.eq(np.floor(values)).all() or values.lt(0).any():
            raise ValueError('Partição com identificador inválido.')
        f[key] = values.astype('int64')
    if (not f.entity_group_id.is_unique or set(f.entity_group_id) != set(map(int, node_ids))):
        raise ValueError('A partição deve atribuir exatamente uma comunidade a todos os nós.')
    f = f[['entity_group_id', 'community_id']].rename(columns={'community_id': 'raw_community_id'})
    canonical = f.groupby('raw_community_id').entity_group_id.min()
    f['community_id'] = f.raw_community_id.map(canonical).astype('int64')
    return f.sort_values('entity_group_id').reset_index(drop=True)


def comparar_particoes(left, right):
    """ARI e NMI aritmética, sem matriz densa de contingência."""
    a, b = list(left), list(right)
    if len(a) != len(b) or not a:
        raise ValueError('Partições vazias ou com tamanhos diferentes.')
    n = len(a)
    ca, cb, joint = Counter(a), Counter(b), Counter(zip(a, b))
    choose = lambda counts: sum(x * (x - 1) // 2 for x in counts)
    if n < 2:
        return {'ari': 1.0, 'nmi': 1.0}
    nij, ai, bj = choose(joint.values()), choose(ca.values()), choose(cb.values())
    expected = ai * bj / (n * (n - 1) / 2)
    denominator = (ai + bj) / 2 - expected
    ari = (nij - expected) / denominator if denominator else 1.0
    ha = -sum((x / n) * math.log(x / n) for x in ca.values())
    hb = -sum((x / n) * math.log(x / n) for x in cb.values())
    mi = sum((x / n) * math.log(x * n / (ca[i] * cb[j])) for (i, j), x in joint.items())
    nmi = 2 * mi / (ha + hb) if ha + hb else 1.0
    return {'ari': float(np.clip(ari, -1, 1)), 'nmi': float(np.clip(nmi, 0, 1))}


def avaliar_particao(nodes, pairs, partition, *, gcc_component_id):
    """Modularidade padrão ponderada, condutância e conexidade de todos os grupos."""
    f = nodes.merge(partition, on='entity_group_id', validate='one_to_one')
    if len(f) != len(nodes) or not f.entity_group_id.is_unique:
        raise ValueError('Partição e atributos de nós incompatíveis.')
    if not set(f.ent_label).issubset(TYPE_COLORS):
        raise ValueError('Tipo de entidade fora do universo PESSOA/ORGANIZACAO/LOCAL.')
    ids = list(map(int, f.entity_group_id))
    community = dict(zip(ids, map(int, f.community_id)))
    parent = {i: i for i in ids}
    def find(a):
        while a != parent[a]:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[max(a, b)] = min(a, b)
    strength, internal, boundary, edge_count = Counter(), Counter(), Counter(), Counter()
    total_weight = 0.0
    seen = set()
    for a, b, weight in zip(pairs.source_id, pairs.target_id, pairs.weight):
        a, b, weight = int(a), int(b), float(weight)
        if (a not in community or b not in community or a == b or not np.isfinite(weight)
                or weight <= 0 or tuple(sorted((a, b))) in seen):
            raise ValueError('Projeção ponderada inválida.')
        seen.add(tuple(sorted((a, b))))
        x, y = community[a], community[b]
        total_weight += weight
        strength[x] += weight
        strength[y] += weight
        if x == y:
            internal[x] += weight
            edge_count[x] += 1
            union(a, b)
        else:
            boundary[x] += weight
            boundary[y] += weight
    if total_weight <= 0:
        raise ValueError('Modularidade indefinida sem peso relacional positivo.')
    f['internal_piece_id'] = [find(i) for i in ids]
    groups = f.groupby('community_id')
    stats = groups.size().rename('nodes').reset_index()
    for name, values in [('strength_sum', strength), ('internal_weight', internal),
                         ('boundary_weight', boundary), ('internal_pairs', edge_count)]:
        stats[name] = stats.community_id.map(values).fillna(0)
    stats['connected_pieces'] = stats.community_id.map(groups.internal_piece_id.nunique()).astype('int64')
    stats['original_components'] = stats.community_id.map(groups.component_id.nunique()).astype('int64')
    gcc_counts = f.loc[f.component_id.eq(gcc_component_id)].groupby('community_id').size()
    stats['gcc_nodes'] = stats.community_id.map(gcc_counts).fillna(0).astype('int64')
    stats['node_share'] = stats.nodes / len(f)
    stats['modularity_contribution'] = stats.internal_weight / total_weight - (stats.strength_sum / (2 * total_weight))**2
    denom = np.minimum(stats.strength_sum, 2 * total_weight - stats.strength_sum)
    stats['conductance'] = np.divide(stats.boundary_weight.to_numpy(float), denom.to_numpy(float),
        out=np.full(len(stats), np.nan), where=denom.to_numpy() > 0)
    stats['internal_density'] = np.divide(2 * stats.internal_pairs.to_numpy(float),
        (stats.nodes * (stats.nodes - 1)).to_numpy(float), out=np.zeros(len(stats)), where=stats.nodes.to_numpy() > 1)
    for label in TYPE_COLORS:
        counts = f.loc[f.ent_label.eq(label)].groupby('community_id').size()
        stats['nodes_' + label] = stats.community_id.map(counts).fillna(0).astype('int64')
    stats = stats.sort_values(['nodes', 'community_id'], ascending=[False, True]).reset_index(drop=True)
    stats.insert(0, 'size_order', np.arange(1, len(stats) + 1))
    top = f.sort_values(['community_id', 'pagerank', 'entity_group_id'], ascending=[True, False, True])
    top = top.groupby('community_id', sort=False).head(5).copy()
    top['order_within_community'] = top.groupby('community_id').cumcount() + 1
    summary = {'nodes': len(f), 'communities': len(stats), 'weighted_modularity': float(stats.modularity_contribution.sum()),
        'largest_community_nodes': int(stats.nodes.max()), 'singleton_communities': int(stats.nodes.eq(1).sum()),
        'disconnected_communities': int(stats.connected_pieces.gt(1).sum()),
        'communities_spanning_original_components': int(stats.original_components.gt(1).sum()),
        'total_unmirrored_weight': total_weight, 'gcc_communities': int(f.loc[f.component_id.eq(gcc_component_id)].community_id.nunique())}
    if not -1 - 1e-10 <= summary['weighted_modularity'] <= 1 + 1e-10:
        raise ValueError('Modularidade padrão fora do intervalo admissível.')
    if not np.allclose(stats.strength_sum, 2 * stats.internal_weight + stats.boundary_weight):
        raise ValueError('Contabilidade de pesos internos e externos inconsistente.')
    return f, stats, top, summary


def executar_algoritmo(session, graph_name, algorithm, config):
    if algorithm not in ['louvain', 'leiden']:
        raise ValueError('Algoritmo não permitido.')
    def query(q, **params):
        return session.execute_read(lambda tx: [row.data() for row in tx.run(q, **params)])
    version = query('RETURN gds.version() AS version')[0]['version']
    estimate = query(f'''CALL gds.{algorithm}.stream.estimate($name, $config)
        YIELD nodeCount, relationshipCount, bytesMin, bytesMax, requiredMemory
        RETURN nodeCount, relationshipCount, bytesMin, bytesMax, requiredMemory''', name=graph_name, config=config)
    clock = time.perf_counter()
    rows = query(f'''CALL gds.{algorithm}.stream($name, $config) YIELD nodeId, communityId
        RETURN gds.util.asNode(nodeId).entity_group_id AS entity_group_id, communityId AS community_id''',
        name=graph_name, config=config)
    return pd.DataFrame(rows), {'gds_version': version, 'elapsed_seconds': time.perf_counter() - clock,
        'memory_estimate': estimate, 'config': config, 'algorithm': algorithm,
        'gds_modularity_reported': False, 'modularity_computed_locally': True,
        'gds_level_count_available': False}


def tabela_comparacoes(partitions, nodes, gcc_id):
    records = []
    ids = list(nodes.entity_group_id)
    mask = nodes.component_id.eq(gcc_id).to_numpy()
    labels = {k: v.set_index('entity_group_id').community_id.reindex(ids).to_numpy() for k, v in partitions.items()}
    for a, b in combinations(labels, 2):
        for scope, selected in [('ALL', np.ones(len(ids), dtype=bool)), ('GCC', mask)]:
            records.append({'partition_a': a, 'partition_b': b, 'scope': scope,
                            'nodes': int(selected.sum()), **comparar_particoes(labels[a][selected], labels[b][selected])})
    return pd.DataFrame(records)


def gerar_figuras(folder, stats, comparisons, reference_leiden):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size': 10, 'svg.fonttype': 'none', 'pdf.fonttype': 42})
    catalog = []
    def save(fig, name, objective, caption):
        fig.tight_layout()
        for ext in ['svg', 'png', 'pdf']:
            fig.savefig(folder / f'{name}.{ext}', dpi=200)
        plt.close(fig)
        catalog.append({'figure': name, 'objective': objective, 'caption': caption})
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for run, color, display in [('louvain', 'tab:blue', 'Louvain'), (reference_leiden, 'tab:orange', 'Leiden de referência')]:
        sizes = stats.loc[stats.run_id.eq(run)].groupby('nodes').size().sort_index()
        ax.step(sizes.index, sizes.iloc[::-1].cumsum().iloc[::-1] / sizes.sum(), where='pre', label=display, color=color)
    ax.set(xscale='log', yscale='log', xlabel='Tamanho da comunidade (nós)', ylabel='Fração de comunidades com tamanho ≥ s')
    ax.legend();ax.grid(alpha=.15)
    save(fig, '01_tamanhos_comunidades', 'Comparar a heterogeneidade dos tamanhos das comunidades.',
         'CCDF dos tamanhos, em escala logarítmica; inclui componentes desconectadas. Não é teste de lei de potência.')
    fig, axes = plt.subplots(1, 2, figsize=(13, 7.5))
    for ax, run, title in zip(axes, ['louvain', reference_leiden], ['Louvain', 'Leiden de referência']):
        part = stats.loc[stats.run_id.eq(run)].head(15).iloc[::-1]
        left = np.zeros(len(part))
        for label in ['ORGANIZACAO', 'PESSOA', 'LOCAL']:
            values = part['nodes_' + label].to_numpy()
            ax.barh(np.arange(len(part)), values, left=left, color=TYPE_COLORS[label], label=TYPE_NAMES[label])
            left += values
        ax.set_yticks(np.arange(len(part)), [f'C{int(c)}' for c in part.community_id])
        ax.set(xlabel='Número de entidades', title=title)
        ax.legend(loc='upper center', bbox_to_anchor=(.5, -.09), ncol=3, fontsize=9)
        ax.grid(axis='x', alpha=.15)
    save(fig, '02_composicao_maiores_comunidades', 'Caracterizar a composição das quinze maiores comunidades por tipo.',
         'Contagens de grupos resolvidos, não de menções. IDs C são canônicos dentro de cada partição; IDs iguais não garantem grupos equivalentes.')
    names = list(stats.run_id.drop_duplicates())
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.5))
    for ax, metric in zip(axes, ['ari', 'nmi']):
        matrix = np.eye(len(names))
        for row in comparisons.loc[comparisons.scope.eq('GCC')].itertuples(index=False):
            a, b = names.index(row.partition_a), names.index(row.partition_b)
            matrix[a, b] = matrix[b, a] = getattr(row, metric)
        im = ax.imshow(matrix, vmin=-1 if metric == 'ari' else 0, vmax=1, cmap='Blues')
        labels = [n.replace('leiden_seed_', 'Leiden s') for n in names]
        ax.set_xticks(range(len(names)), labels, rotation=45, ha='right')
        ax.set_yticks(range(len(names)), labels);ax.set_title(metric.upper() + ' — maior componente')
        for i in range(len(names)):
            for j in range(len(names)):
                ax.text(j, i, f'{matrix[i,j]:.3f}', ha='center', va='center', color='white' if matrix[i,j] > .6 else 'black')
        fig.colorbar(im, ax=ax, shrink=.7)
    save(fig, '03_concordancia_gcc', 'Comparar algoritmos e sensibilidade às sementes na maior componente.',
         'Partições obtidas na rede inteira, restringidas aos nós da GCC para comparação. Não são novas detecções na GCC; concordância não demonstra verdade semântica.')
    return pd.DataFrame(catalog)


def detectar_comunidades(projeto, *, executar_gds=False, sementes_leiden=(42, 43, 44),
                         assinatura_rede_esperada=None, driver_factory=None):
    root = Path(projeto).resolve()
    runs = configuracoes(sementes_leiden)
    s_folder, s_meta, p_folder, p_meta, n_folder, n_meta = carregar_estrutura(root)
    c_folder, c_meta = carregar_centralidades(root)
    if assinatura_rede_esperada and n_meta['snapshot_sha256'] != assinatura_rede_esperada:
        raise ValueError('A rede ativa difere da edição esperada.')
    if not executar_gds:
        result = {'mode': 'DRY_RUN', 'nodes': n_meta['summary']['nodes'],
            'undirected_pairs': p_meta['summary']['undirected_pairs'], 'graph_name': p_meta['graph_names']['community'],
            'runs': runs, 'neo4j_connections': 0, 'api_calls': 0, 'reference_partition': 'louvain'}
        print('[COMUNIDADES]', json.dumps(result, ensure_ascii=False));return result
    spec = {'schema': 'weighted-community-analysis-1', 'version': VERSION, 'code_sha256': sha(Path(__file__)),
        'network_snapshot_sha256': n_meta['snapshot_sha256'], 'projection_snapshot_sha256': p_meta['snapshot_sha256'],
        'structural_snapshot_sha256': s_meta['snapshot_sha256'], 'centrality_snapshot_sha256': c_meta['snapshot_sha256'],
        'runs': runs, 'reference_partition': 'louvain', 'reference_leiden': next(k for k in runs if k.startswith('leiden')),
        'modularity_resolution': 1.0, 'nmi_normalization': 'arithmetic'}
    signature = json_sha(spec)
    base = root / 'resultados/comunidades';base.mkdir(parents=True, exist_ok=True)
    target = base / 'instancias' / signature[:20]
    checkpoint = base / 'execucoes' / signature[:20]
    lock = base / 'execucao.lock'
    try:lock.mkdir()
    except FileExistsError:raise RuntimeError('Outra análise de comunidades pode estar ativa. Confira o bloqueio.') from None
    driver, temp = None, None
    try:
        if target.exists():
            meta = validate_manifest(target)
            if meta['snapshot_sha256'] != signature:raise ValueError('Colisão de assinatura de comunidades.')
            print('[COMUNIDADES] Resultado completo conferido; sem repetir detecção.')
        else:
            nodes = pd.read_csv(c_folder / 'centralidades_nos.csv.gz', keep_default_na=False)
            structural = pd.read_csv(s_folder / 'metricas_nos.csv.gz')
            nodes = nodes.merge(structural[['entity_group_id', 'component_id']], on='entity_group_id', validate='one_to_one')
            if len(nodes) != n_meta['summary']['nodes']:raise ValueError('Universo de nós incompatível.')
            counts = nodes.groupby('component_id').size().sort_index().sort_values(ascending=False, kind='stable')
            gcc_id = int(counts.index[0])
            pairs = pd.read_csv(p_folder / 'ponderada_nao_dirigida.csv.gz')
            partitions, executions = {}, {}
            for run in runs:
                saved = checkpoint / run
                if saved.exists():
                    receipt = validate_manifest(saved)
                    if receipt['analysis_snapshot_sha256'] != signature or receipt['run'] != runs[run]:
                        raise ValueError('Checkpoint de comunidade incompatível.')
                    frame = pd.read_csv(saved / 'particao.csv.gz')
                    canonical = canonizar_particao(frame.rename(columns={'community_id': 'saved_id', 'raw_community_id': 'community_id'}), nodes.entity_group_id)
                    if not np.array_equal(canonical.community_id, frame.sort_values('entity_group_id').community_id):
                        raise ValueError('IDs canônicos alterados no checkpoint.')
                    partitions[run], executions[run] = frame, receipt['execution']
                    print('[COMUNIDADES] Checkpoint conferido:', run)
            if len(partitions) < len(runs):
                uri, user, password, database = _configuration(root)
                if driver_factory is None:
                    from neo4j import GraphDatabase
                    driver_factory = GraphDatabase.driver
                driver = driver_factory(uri, auth=(user, password), connection_timeout=15, max_transaction_retry_time=10)
                driver.verify_connectivity()
                with driver.session(database=database) as session:
                    def read(q):return session.execute_read(lambda tx: [r.data() for r in tx.run(q)])
                    version = read('RETURN gds.version() AS version')[0]['version']
                    if any(e['gds_version'] != version for e in executions.values()):
                        raise ValueError('A versão GDS mudou durante a série. Preserve os checkpoints e revise a configuração.')
                    verificar_projecao(session, p_meta['graph_names']['community'], database,
                        'newsai_' + n_meta['snapshot_sha256'][:20], set(map(int, nodes.entity_group_id)),
                        valores_esperados('community', None, pairs))
                    for run, definition in runs.items():
                        if run in partitions:continue
                        raw, execution = executar_algoritmo(session, p_meta['graph_names']['community'],
                            definition['algorithm'], definition['config'])
                        frame = canonizar_particao(raw, nodes.entity_group_id)
                        saved = checkpoint / run;saved.parent.mkdir(parents=True, exist_ok=True)
                        staging = Path(tempfile.mkdtemp(prefix='.salvando_', dir=saved.parent))
                        try:
                            write_csv(staging, 'particao.csv.gz', frame)
                            atomic_json(staging / 'manifesto.json', {'analysis_snapshot_sha256': signature,
                                'run': definition, 'execution': execution,
                                'outputs_sha256': {'particao.csv.gz': sha(staging / 'particao.csv.gz')}})
                            os.rename(staging, saved)
                        finally:
                            if staging.exists():shutil.rmtree(staging)
                        partitions[run], executions[run] = frame, execution
                        print(f'[COMUNIDADES] {run}: {len(frame):,} nós; {frame.community_id.nunique():,} comunidades; '
                              f'{execution["elapsed_seconds"]:.2f}s; partição salva.', flush=True)
            all_assignments, all_stats, all_top, summaries = [], [], [], []
            for run in runs:
                assignments, stats, top, summary = avaliar_particao(nodes, pairs, partitions[run], gcc_component_id=gcc_id)
                for frame in [assignments, stats, top]:frame.insert(0, 'run_id', run)
                all_assignments.append(assignments);all_stats.append(stats);all_top.append(top)
                summaries.append({'run_id': run, **summary, 'algorithm_seconds': executions[run]['elapsed_seconds']})
            baseline = pd.DataFrame({'entity_group_id': nodes.entity_group_id, 'community_id': nodes.component_id})
            _, _, _, baseline_summary = avaliar_particao(nodes, pairs, canonizar_particao(baseline, nodes.entity_group_id), gcc_component_id=gcc_id)
            comparisons = tabela_comparacoes(partitions, nodes, gcc_id)
            stats, top = pd.concat(all_stats, ignore_index=True), pd.concat(all_top, ignore_index=True)
            assignments = pd.concat(all_assignments, ignore_index=True)
            temp = Path(tempfile.mkdtemp(prefix='.calculando_', dir=base))
            for name, frame in [('particoes_nos.csv.gz', assignments), ('metricas_comunidades.csv.gz', stats),
                ('entidades_destaque_comunidades.csv.gz', top), ('resumo_particoes.csv', pd.DataFrame(summaries)),
                ('comparacao_particoes.csv', comparisons)]:write_csv(temp, name, frame)
            write_csv(temp, 'catalogo_figuras.csv', gerar_figuras(temp, stats, comparisons, spec['reference_leiden']))
            atomic_json(temp / 'execucoes_gds.json', executions)
            atomic_json(temp / 'referencia_componentes.json', baseline_summary)
            (temp / 'LEIA_ME.md').write_text('# Comunidades ponderadas\n\n'
                'Referência: Louvain. Leiden é comparação complementar; a primeira semente configurada é a referência '
                'visual, sem seleção posterior pelo maior valor de modularidade. Todas as partições são preservadas.\n\n'
                'A projeção soma frequências relacionais por par, ignorando rótulo e direção apenas nesta análise. '
                'A modularidade é calculada localmente na mesma convenção ponderada e resolução 1. '
                'A modularidade da partição por componentes é uma referência de fragmentação, não um modelo nulo amostrado.\n\n'
                'ARI/NMI comparam partições, não validam seus temas. A comparação GCC restringe partições detectadas '
                'globalmente; não reexecuta os algoritmos apenas na GCC. Verifique conectividade, composição e '
                'notícias de suporte antes de atribuir interpretação temática. Grupos desconectados são sinalizados '
                'e preservados, sem divisão automática. A rede de notícias tem cobertura de extração incompleta.\n', encoding='utf-8')
            summary = {'nodes': len(nodes), 'undirected_pairs': len(pairs), 'run_count': len(runs),
                'reference_partition': 'louvain', 'reference_leiden': spec['reference_leiden'], 'partitions': summaries,
                'component_partition_modularity': baseline_summary['weighted_modularity'],
                'gcc_nodes': int(counts.iloc[0]), 'all_nodes_assigned_in_all_runs': True,
                'api_calls': 0, 'database_writes': 0, 'gds_properties_mutated': 0}
            meta = {**spec, 'snapshot_sha256': signature, 'summary': summary,
                'created_at_utc': datetime.now(timezone.utc).isoformat(),
                'outputs_sha256': {p.name: sha(p) for p in sorted(temp.iterdir())}}
            atomic_json(temp / 'manifesto.json', meta);validate_manifest(temp)
            if carregar_centralidades(root)[1]['snapshot_sha256'] != c_meta['snapshot_sha256']:
                raise ValueError('As entradas ativas mudaram durante a detecção.')
            target.parent.mkdir(parents=True, exist_ok=True);os.rename(temp, target);temp = None
        atomic_json(base / 'atual.json', {'folder': target.relative_to(base).as_posix(), 'snapshot_sha256': signature})
        package = base / f'Resumo_Comunidades_{signature[:12]}_{uuid.uuid4().hex[:6]}.zip'
        with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as z:
            for path in sorted(target.iterdir()):z.write(path, path.name)
        print('[COMUNIDADES]', json.dumps(meta['summary'], ensure_ascii=False));print('[COMUNIDADES] Pacote:', package)
        return {**meta['summary'], 'output_directory': target, 'package': package, 'snapshot_sha256': signature}
    except (ValueError, RuntimeError):raise
    except Exception as exc:
        raise RuntimeError('Detecção interrompida; partições concluídas foram preservadas. Diagnóstico: ' + json.dumps(_failure(exc))) from None
    finally:
        if driver is not None:driver.close()
        if temp is not None:shutil.rmtree(temp, ignore_errors=True)
        lock.rmdir()


def carregar_comunidades(projeto):
    root = Path(projeto).resolve();_, centrality = carregar_centralidades(root)
    base = root / 'resultados/comunidades'
    pointer = json.loads((base / 'atual.json').read_text(encoding='utf-8'))
    folder = (base / pointer['folder']).resolve()
    if base.resolve() not in folder.parents:raise ValueError('Apontador de comunidades inválido.')
    meta = validate_manifest(folder)
    if (pointer['snapshot_sha256'] != meta['snapshot_sha256'] or
            centrality['snapshot_sha256'] != meta['centrality_snapshot_sha256']):
        raise ValueError('As comunidades ativas pertencem a outra versão das entradas.')
    return folder, meta
