"""Distâncias geodésicas exatas, em blocos retomáveis, na maior componente."""
from pathlib import Path
from collections import deque
from datetime import datetime, timezone
import json
import os
import platform
import shutil
import tempfile
import time
import uuid
import zipfile
import numpy as np
import pandas as pd
from redes_construcao import carregar_rede
from redes_projecoes import carregar_projecoes
from re_consolidacao import sha, json_sha, write_csv, validate_manifest
from re_execucao import atomic_json

VERSION = '1.0.0'


def carregar_estrutura(projeto):
    root = Path(projeto).resolve()
    network_folder, network = carregar_rede(root)
    projection_folder, projection = carregar_projecoes(root)
    base = root / 'resultados/estrutural'
    pointer = json.loads((base / 'atual.json').read_text(encoding='utf-8'))
    if Path(pointer['folder']).name != pointer['folder']:
        raise ValueError('Apontador estrutural inválido.')
    folder = base / pointer['folder']
    meta = validate_manifest(folder)
    if pointer['snapshot_sha256'] != meta['snapshot_sha256']:
        raise ValueError('Assinatura estrutural incompatível.')
    if (meta['network_snapshot_sha256'] != network['snapshot_sha256'] or
            meta['projection_snapshot_sha256'] != projection['snapshot_sha256']):
        raise ValueError('A rede ou projeção mudou. Atualize a caracterização estrutural.')
    return folder, meta, projection_folder, projection, network_folder, network


def preparar_componente(metrics, pairs, components):
    """Verifica toda a topologia e seleciona uma maior componente por ID canônico."""
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components
    frame = metrics.copy()
    if frame.empty or not frame.entity_group_id.is_unique:
        raise ValueError('Universo de nós vazio ou com IDs duplicados.')
    for key in ['entity_group_id', 'degree', 'component_id']:
        values = pd.to_numeric(frame[key], errors='raise')
        if not np.isfinite(values).all() or not values.eq(np.floor(values)).all():
            raise ValueError('Identificador ou grau inválido.')
        frame[key] = values.astype('int64')
    frame = frame.sort_values('entity_group_id').reset_index(drop=True)
    ids = frame.entity_group_id.to_numpy()
    index = {int(x): i for i, x in enumerate(ids)}
    a, b, seen = [], [], set()
    for x, y in zip(pairs.source_id, pairs.target_id):
        x, y = int(x), int(y)
        pair = tuple(sorted((x, y)))
        if x == y or x not in index or y not in index or pair in seen:
            raise ValueError('Extremo inválido, autolaço ou par repetido.')
        seen.add(pair)
        a.extend([index[x], index[y]])
        b.extend([index[y], index[x]])
    graph = csr_matrix((np.ones(len(a)), (a, b)), shape=(len(ids), len(ids)))
    graph.sort_indices()
    if not np.array_equal(np.diff(graph.indptr), frame.degree.to_numpy()):
        raise ValueError('Graus diferentes da caracterização estrutural.')
    _, labels = connected_components(graph, directed=False)
    minima = {}
    for i, label in enumerate(labels):
        minima[int(label)] = min(int(ids[i]), minima.get(int(label), int(ids[i])))
    canonical = np.array([minima[int(x)] for x in labels], dtype=np.int64)
    if not np.array_equal(canonical, frame.component_id.to_numpy()):
        raise ValueError('Componentes diferentes da caracterização estrutural.')
    actual = frame.groupby('component_id').size().rename('nodes').reset_index()
    expected = components[['component_id', 'nodes']].astype('int64')
    if not actual.sort_values('component_id').reset_index(drop=True).equals(
            expected.sort_values('component_id').reset_index(drop=True)):
        raise ValueError('Tabela de componentes incompatível.')
    selected = actual.sort_values(['nodes', 'component_id'], ascending=[False, True]).iloc[0]
    mask = canonical == int(selected.component_id)
    gcc = graph[mask][:, mask].tocsr()
    if (gcc != gcc.T).nnz or (gcc.data != 1).any():
        raise ValueError('A matriz da componente deve ser simétrica e unitária.')
    return frame.loc[mask].reset_index(drop=True), gcc


def bfs_referencia(graph, source):
    """Busca em largura independente para conferir todas as distâncias de uma fonte."""
    result = np.full(graph.shape[0], -1, dtype=np.int64)
    result[source] = 0
    queue = deque([source])
    while queue:
        i = queue.popleft()
        for j in graph.indices[graph.indptr[i]:graph.indptr[i + 1]]:
            if result[j] < 0:
                result[j] = result[i] + 1
                queue.append(int(j))
    return result


def conferir_algoritmo(graph):
    from scipy.sparse.csgraph import dijkstra
    candidates = sorted({0, graph.shape[0] - 1, int(np.argmax(np.diff(graph.indptr)))})
    for source in candidates:
        observed = dijkstra(graph, directed=False, indices=source, unweighted=True)
        reference = bfs_referencia(graph, source)
        if (reference < 0).any() or not np.array_equal(observed, reference):
            raise ValueError('Divergência entre Dijkstra e busca em largura.')
    return candidates


def ler_blocos(folder, signature, ids):
    blocks, end = [], 0
    for path in sorted(folder.glob('bloco_*.json')):
        block = json.loads(path.read_text(encoding='utf-8'))
        checksum = block.pop('payload_sha256', None)
        if checksum != json_sha(block) or block['snapshot_sha256'] != signature:
            raise ValueError('Bloco alterado ou de outra versão: ' + path.name)
        count = len(block['rows'])
        if count < 1 or block['start'] != end or block['stop'] != end + count:
            raise ValueError('Sequência de blocos inválida.')
        expected_ids = list(map(int, ids[end:end + count]))
        if expected_ids != [r['entity_group_id'] for r in block['rows']]:
            raise ValueError('Fontes incompatíveis com os blocos salvos.')
        if sum(block['histogram']) != count * (len(ids) - 1):
            raise ValueError('Contagem de pares incompatível no bloco.')
        if sum(i * x for i, x in enumerate(block['histogram'])) != sum(r['distance_sum'] for r in block['rows']):
            raise ValueError('Soma das distâncias incompatível no bloco.')
        blocks.append(block)
        end += count
    return blocks


def processar_blocos(graph, ids, folder, signature, *, tamanho_bloco=32, max_fontes=None):
    """Persiste cada bloco antes de iniciar o seguinte. Fontes salvas são reutilizadas."""
    from scipy.sparse.csgraph import dijkstra
    if isinstance(tamanho_bloco, bool) or not isinstance(tamanho_bloco, int) or tamanho_bloco < 1:
        raise ValueError('tamanho_bloco deve ser inteiro positivo.')
    if max_fontes is not None and (isinstance(max_fontes, bool) or not isinstance(max_fontes, int) or max_fontes < 1):
        raise ValueError('max_fontes deve ser None ou inteiro positivo.')
    n = len(ids)
    folder.mkdir(parents=True, exist_ok=True)
    blocks = ler_blocos(folder, signature, ids)
    done = sum(len(b['rows']) for b in blocks)
    stop = n if max_fontes is None else min(n, done + max_fontes)
    print(f'[DISTÂNCIAS] Retomada: {done:,}/{n:,} fontes; até {stop - done:,} novas fontes nesta execução.')
    for start in range(done, stop, tamanho_bloco):
        end = min(start + tamanho_bloco, stop)
        clock = time.perf_counter()
        distances = dijkstra(graph, directed=False, indices=np.arange(start, end), unweighted=True,
                             return_predecessors=False)
        if not np.isfinite(distances).all() or not np.equal(distances, np.floor(distances)).all():
            raise ValueError('Distância não finita ou não inteira na componente conexa.')
        histogram = np.bincount(distances.astype(np.int64).ravel()).tolist()
        if histogram[0] != end - start:
            raise ValueError('Apenas as diagonais podem ter distância zero.')
        histogram[0] = 0
        rows = []
        for offset, row in enumerate(distances):
            if row[start + offset] != 0 or (row == 0).sum() != 1:
                raise ValueError('Diagonal ou quantidade de destinos inválida.')
            farthest = int(np.argmax(row))
            rows.append({'entity_group_id': int(ids[start + offset]), 'reachable_others': n - 1,
                         'distance_sum': int(row.sum()), 'eccentricity': int(row.max()),
                         'farthest_entity_group_id': int(ids[farthest])})
        del distances
        block = {'snapshot_sha256': signature, 'start': start, 'stop': end, 'rows': rows,
                 'histogram': histogram, 'elapsed_seconds': time.perf_counter() - clock,
                 'created_at_utc': datetime.now(timezone.utc).isoformat()}
        block['payload_sha256'] = json_sha(block)
        atomic_json(folder / f'bloco_{start:08d}_{end:08d}.json', block)
        block.pop('payload_sha256')
        blocks.append(block)
        seconds = sum(b['elapsed_seconds'] for b in blocks)
        eta = seconds / end * (n - end)
        print(f'[DISTÂNCIAS] {end:,}/{n:,} fontes salvas; bloco: {block["elapsed_seconds"]:.2f}s; '
              f'tempo restante indicativo: {eta / 60:.1f} min.', flush=True)
    return blocks


def resumir_blocos(blocks, n, edges):
    rows = pd.DataFrame([row for b in blocks for row in b['rows']])
    histogram = np.zeros(max(len(b['histogram']) for b in blocks), dtype=np.int64)
    for block in blocks:
        histogram[:len(block['histogram'])] += block['histogram']
    done = len(rows)
    complete = done == n
    diameter_lower = int(rows.eccentricity.max())
    radius_upper = int(rows.eccentricity.min())
    summary = {'status': 'COMPLETE' if complete else 'PARTIAL', 'gcc_nodes': n, 'gcc_edges': edges,
               'sources_completed': done, 'ordered_pairs_evaluated': int(histogram.sum()),
               'expected_ordered_pairs': n * (n - 1), 'distance_unit': 'number_of_edges',
               'average_distance': float(rows.distance_sum.sum() / (n * (n - 1))) if complete and n > 1 else None,
               'diameter': diameter_lower if complete else None,
               'radius': radius_upper if complete else None,
               'diameter_lower_bound': diameter_lower,
               'diameter_upper_bound': min(n - 1, 2 * radius_upper),
               'radius_lower_bound': (diameter_lower + 1) // 2,
               'radius_upper_bound': radius_upper,
               'computation_seconds': sum(b['elapsed_seconds'] for b in blocks),
               'exact_all_sources': complete, 'api_calls': 0, 'neo4j_connections': 0}
    if complete:
        if histogram.sum() != n * (n - 1) or (histogram % 2).any():
            raise ValueError('Simetria ou contagem dos pares inválida.')
        if n > 1 and histogram[1] != 2 * edges:
            raise ValueError('Pares a distância um diferentes de 2M da componente.')
        if int(histogram @ np.arange(len(histogram))) != int(rows.distance_sum.sum()):
            raise ValueError('Soma global das distâncias inconsistente.')
        summary['diameter_upper_bound'] = summary['diameter']
        summary['radius_lower_bound'] = summary['radius']
    rows['mean_distance_to_others'] = rows.distance_sum / (n - 1) if n > 1 else np.nan
    distribution = pd.DataFrame({'distance': np.arange(len(histogram)), 'ordered_pairs': histogram})
    distribution = distribution.loc[distribution.distance > 0].copy()
    distribution['fraction'] = distribution.ordered_pairs / max(1, int(histogram.sum()))
    return rows, distribution, summary


def gerar_figuras(folder, distribution, rows):
    import matplotlib.pyplot as plt
    catalog = []
    counts = rows.groupby('eccentricity').size()
    for name, x, y, color, xlabel, ylabel, objective in [
        ('01_distancias_gcc', distribution.distance, distribution.fraction, 'tab:orange',
         'Distância geodésica (arestas)', 'Fração dos pares distintos da componente',
         'Caracterizar a separação entre vértices na maior componente; pares ordenados, sem diagonais.'),
        ('02_excentricidades_gcc', counts.index, counts.values, 'tab:blue',
         'Excentricidade (arestas)', 'Número de vértices',
         'Examinar a distribuição das maiores distâncias por vértice; extremos definem raio e diâmetro.')]:
        fig, ax = plt.subplots(figsize=(7, 4.3))
        ax.bar(x, y, color=color)
        ax.set(xlabel=xlabel, ylabel=ylabel)
        ax.set_xticks(list(x))
        ax.grid(axis='y', alpha=.2)
        fig.tight_layout()
        for ext in ['svg', 'png', 'pdf']:
            fig.savefig(folder / f'{name}.{ext}', dpi=200)
        plt.close(fig)
        catalog.append({'figure': name, 'objective_and_caption': objective, 'scope': 'GCC', 'exact': True})
    return pd.DataFrame(catalog)


def calcular_distancias(projeto, *, executar=False, max_fontes=None, tamanho_bloco=32,
                        assinatura_rede_esperada=None):
    root = Path(projeto).resolve()
    s_folder, s_meta, p_folder, p_meta, _, n_meta = carregar_estrutura(root)
    if assinatura_rede_esperada and n_meta['snapshot_sha256'] != assinatura_rede_esperada:
        raise ValueError('A rede ativa difere da edição esperada.')
    if not executar:
        result = {'mode': 'DRY_RUN', 'gcc_nodes': s_meta['summary']['largest_component_nodes'],
                  'api_calls': 0, 'neo4j_connections': 0, 'max_new_sources': max_fontes,
                  'block_size': tamanho_bloco, 'method': 'exact_unweighted_all_sources',
                  'distance_matrix_block_mib': tamanho_bloco * s_meta['summary']['largest_component_nodes'] * 8 / 2**20}
        print('[DISTÂNCIAS]', json.dumps(result, ensure_ascii=False))
        return result
    try:
        import scipy
        import matplotlib
    except ImportError:
        raise RuntimeError('Instale scipy e matplotlib no kernel do notebook antes de executar.') from None
    spec = {'schema': 'gcc-distances-1', 'version': VERSION,
            'code_sha256': sha(Path(__file__)), 'network_snapshot_sha256': n_meta['snapshot_sha256'],
            'projection_snapshot_sha256': p_meta['snapshot_sha256'],
            'structural_snapshot_sha256': s_meta['snapshot_sha256'], 'scipy_version': scipy.__version__,
            'method': 'scipy.sparse.csgraph.dijkstra', 'unweighted': True, 'directed': False,
            'source_order': 'entity_group_id ascending', 'gcc_tie_break': 'minimum canonical component ID'}
    signature = json_sha(spec)
    base = root / 'resultados/distancias'
    base.mkdir(parents=True, exist_ok=True)
    lock = base / 'execucao.lock'
    try:
        lock.mkdir()
    except FileExistsError:
        raise RuntimeError('Outra execução de distâncias pode estar ativa. Confira o bloqueio antes de retomar.') from None
    temp = None
    try:
        folder = base / 'execucoes' / signature[:20]
        checkpoint = folder / 'blocos'
        folder.mkdir(parents=True, exist_ok=True)
        if (folder / 'especificacao.json').exists():
            if json.loads((folder / 'especificacao.json').read_text(encoding='utf-8')) != spec:
                raise ValueError('A especificação salva é incompatível.')
        else:
            atomic_json(folder / 'especificacao.json', spec)
        target = base / 'instancias' / signature[:20]
        if target.exists():
            meta = validate_manifest(target)
            if meta['snapshot_sha256'] != signature:
                raise ValueError('Colisão de versão de distâncias.')
            print('[DISTÂNCIAS] Resultado completo conferido; nenhum caminho será recalculado.')
        else:
            metrics = pd.read_csv(s_folder / 'metricas_nos.csv.gz')
            pairs = pd.read_csv(p_folder / 'simples_nao_dirigida.csv.gz')
            components = pd.read_csv(s_folder / 'componentes.csv')
            nodes, graph = preparar_componente(metrics, pairs, components)
            n = len(nodes)
            if n != s_meta['summary']['largest_component_nodes']:
                raise ValueError('Tamanho da maior componente incompatível.')
            bfs_sources = conferir_algoritmo(graph)
            blocks = processar_blocos(graph, nodes.entity_group_id.to_numpy(), checkpoint, signature,
                                     tamanho_bloco=tamanho_bloco, max_fontes=max_fontes)
            rows, distribution, summary = resumir_blocos(blocks, n, graph.nnz // 2)
            rows = rows.merge(nodes[['entity_group_id', 'entity_group_name', 'ent_label']],
                              on='entity_group_id', validate='one_to_one')
            summary['independent_bfs_sources_checked'] = len(bfs_sources)
            summary['estimated_remaining_compute_seconds'] = summary['computation_seconds'] / len(rows) * (n - len(rows))
            temp = Path(tempfile.mkdtemp(prefix='.salvando_', dir=base))
            write_csv(temp, 'distancias_por_fonte.csv.gz', rows)
            write_csv(temp, 'distribuicao_distancias.csv', distribution)
            write_csv(temp, 'resumo_metricas.csv', pd.DataFrame([{'metric': k, 'value': v} for k, v in summary.items()]))
            if summary['status'] == 'COMPLETE':
                write_csv(temp, 'catalogo_figuras.csv', gerar_figuras(temp, distribution, rows))
            atomic_json(temp / 'ambiente.json', {'python': platform.python_version(), 'scipy': scipy.__version__,
                'numpy': np.__version__, 'pandas': pd.__version__, 'matplotlib': matplotlib.__version__,
                'independent_bfs_entity_ids': [int(nodes.entity_group_id.iloc[x]) for x in bfs_sources]})
            note = ('As métricas são exatas sobre todos os vértices da maior componente. '
                    'Distância média exclui diagonais; raio e diâmetro são mínimo e máximo das excentricidades.'
                    if summary['status'] == 'COMPLETE' else
                    'Execução parcial em ordem determinística, sem amostragem aleatória. Não constitui estimativa '
                    'da distância média global. Os limites de raio/diâmetro são provisórios; retome para concluir.')
            (temp / 'LEIA_ME.md').write_text('# Distâncias na maior componente\n\n' + note +
                '\n\nDistância medida em número de arestas na projeção simples não dirigida e não ponderada. '
                'As demais componentes não entram nestas métricas. Alcance estrutural não é prova de influência '
                'ou causalidade e depende da cobertura das extrações. Pesos das relações não são comprimentos.\n', encoding='utf-8')
            meta = {**spec, 'snapshot_sha256': signature, 'summary': summary,
                    'created_at_utc': datetime.now(timezone.utc).isoformat(),
                    'outputs_sha256': {p.name: sha(p) for p in sorted(temp.iterdir())}}
            atomic_json(temp / 'manifesto.json', meta)
            validate_manifest(temp)
            if carregar_estrutura(root)[1]['snapshot_sha256'] != s_meta['snapshot_sha256']:
                raise ValueError('As entradas ativas mudaram durante a execução.')
            if summary['status'] == 'COMPLETE':
                target.parent.mkdir(parents=True, exist_ok=True)
                os.rename(temp, target)
            else:
                target = base / 'parciais' / (signature[:12] + '_' + uuid.uuid4().hex[:8])
                target.parent.mkdir(parents=True, exist_ok=True)
                os.rename(temp, target)
            temp = None
        if meta['summary']['status'] == 'COMPLETE':
            atomic_json(base / 'atual.json', {'folder': target.relative_to(base).as_posix(), 'snapshot_sha256': signature})
        package = base / f'Resumo_Distancias_{signature[:12]}_{uuid.uuid4().hex[:6]}.zip'
        with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as z:
            for path in sorted(target.iterdir()):
                z.write(path, path.name)
        print('[DISTÂNCIAS]', json.dumps(meta['summary'], ensure_ascii=False))
        print('[DISTÂNCIAS] Pacote:', package)
        return {**meta['summary'], 'output_directory': target, 'checkpoint_directory': checkpoint,
                'package': package, 'snapshot_sha256': signature}
    finally:
        if temp is not None:
            shutil.rmtree(temp, ignore_errors=True)
        lock.rmdir()
