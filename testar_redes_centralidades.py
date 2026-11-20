"""Verificações de conectividade, PageRank, rankings e reutilização de resultados."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock, MagicMock
import numpy as np
import pandas as pd
from redes_centralidades import (calcular_conectividade, pagerank_referencia, validar_pagerank,
    gerar_rankings, gerar_figuras, executar_pagerank, analisar_centralidades)


def entradas():
    nodes = pd.DataFrame({'entity_group_id': [10, 11, 12], 'entity_group_name': ['A', 'B', 'C'],
        'ent_label': ['PESSOA', 'ORGANIZACAO', 'LOCAL'], 'mention_count': [5, 3, 1],
        'relation_news_count': [3, 2, 1]})
    edges = pd.DataFrame({'edge_id': ['a', 'b', 'c', 'd'], 'source_id': [10, 10, 11, 11],
        'target_id': [11, 11, 10, 12], 'weight': [2, 3, 7, 1]})
    simple = pd.DataFrame({'source_id': [10, 11], 'target_id': [11, 12]})
    structural = pd.DataFrame({'entity_group_id': [10, 11, 12], 'degree': [1, 2, 1]})
    return nodes, edges, simple, structural


class CentralidadesTests(unittest.TestCase):
    def test_parallel_and_reciprocal_edges(self):
        f, summary = calcular_conectividade(*entradas())
        self.assertEqual(f.typed_degree.tolist(), [3, 4, 1])
        self.assertEqual(f.neighbor_degree.tolist(), [1, 2, 1])
        self.assertEqual(f.weighted_strength.tolist(), [12, 13, 1])
        self.assertEqual(f.in_neighbors.tolist(), [1, 1, 1])
        self.assertEqual(f.out_neighbors.tolist(), [1, 2, 0])
        self.assertEqual(summary['weighted_strength_sum'], 26)

    def test_invalid_inputs(self):
        for column, value in [('weight', -1), ('weight', .5), ('source_id', 999), ('target_id', 10)]:
            nodes, edges, simple, structural = entradas()
            edges[column] = edges[column].astype(float)
            edges.loc[0, column] = value
            with self.assertRaises(ValueError):
                calcular_conectividade(nodes, edges, simple, structural)

    def test_pagerank_chain_and_sinks(self):
        e = pd.DataFrame({'source_id': [10, 11], 'target_id': [11, 12], 'weight': [2, 5]})
        score, proof = pagerank_referencia([10, 11, 12], e)
        np.testing.assert_allclose(score, [.15, .2775, .385875], atol=1e-12)
        self.assertTrue(proof['converged'])
        self.assertLess(score.sum(), 3)

    def test_pagerank_validation_and_universe(self):
        nodes, edges, simple, structural = entradas()
        f, _ = calcular_conectividade(nodes, edges, simple, structural)
        score, _ = pagerank_referencia(f.entity_group_id, edges)
        raw = pd.DataFrame({'entity_group_id': f.entity_group_id, 'pagerank': score}).iloc[::-1]
        result, proof = validar_pagerank(f, raw, edges)
        self.assertAlmostEqual(result.pagerank_share.sum(), 1)
        self.assertTrue(proof['all_nodes_compared'])
        raw.loc[0, 'pagerank'] += 1
        with self.assertRaises(ValueError):
            validar_pagerank(f, raw, edges)
        with self.assertRaises(ValueError):
            validar_pagerank(f, raw.iloc[:2], edges)

    def test_rank_ties_and_colors_figures(self):
        nodes, edges, simple, structural = entradas()
        frame, _ = calcular_conectividade(nodes, edges, simple, structural)
        frame['pagerank'] = [.2, .2, .3]
        f, ranks = gerar_rankings(frame)
        self.assertEqual(f.rank_pagerank.tolist(), [2, 2, 1])
        self.assertEqual(ranks.loc[(ranks.metric=='pagerank') & (ranks.scope=='ALL'), 'entity_group_id'].tolist(), [12, 10, 11])
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(len(gerar_figuras(Path(directory), f)), 3)
            self.assertEqual(len(list(Path(directory).iterdir())), 9)

    def test_single_gds_algorithm_call(self):
        class Row:
            def __init__(self, d): self.d = d
            def data(self): return self.d
        queries = []
        class Tx:
            def run(self, q, **params):
                queries.append(q)
                if 'gds.version()' in q:
                    return [Row({'version': 'simulated'})]
                return [Row({'nodeCount': 3})] if '.estimate(' in q else [Row({'entity_group_id': 10, 'pagerank': .15})]
        session = Mock()
        session.execute_read.side_effect = lambda callback: callback(Tx())
        rows, execution = executar_pagerank(session, 'g')
        self.assertEqual(len(rows), 1)
        self.assertEqual(sum('CALL gds.pageRank.stream(' in q for q in queries), 1)
        self.assertEqual(sum('.estimate(' in q for q in queries), 1)

    def test_dry_run_no_files(self):
        loaded = (None, {}, None, {'graph_names': {'directed': 'g'}}, None,
                  {'snapshot_sha256': 'n', 'summary': {'nodes': 3, 'edges': 4}})
        with tempfile.TemporaryDirectory() as directory:
            with patch('redes_centralidades.carregar_estrutura', return_value=loaded):
                result = analisar_centralidades(directory)
                self.assertEqual(result['api_calls'], 0)
                self.assertEqual(list(Path(directory).iterdir()), [])
                with self.assertRaises(ValueError):
                    analisar_centralidades(directory, assinatura_rede_esperada='x')

    def test_full_workflow_and_cached_reuse(self):
        nodes, edges, simple, structural = entradas()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            n, p, s = [root / x for x in ['n', 'p', 's']]
            for folder in [n, p, s]: folder.mkdir()
            nodes.to_csv(n / 'nos.csv.gz', index=False)
            edges.to_csv(n / 'arestas.csv.gz', index=False)
            simple.to_csv(p / 'simples_nao_dirigida.csv.gz', index=False)
            structural.to_csv(s / 'metricas_nos.csv.gz', index=False)
            loaded = (s, {'snapshot_sha256': 's'}, p,
                {'snapshot_sha256': 'p', 'graph_names': {'directed': 'g'}}, n, {'snapshot_sha256': 'n'})
            score, _ = pagerank_referencia(nodes.entity_group_id, edges)
            raw = pd.DataFrame({'entity_group_id': nodes.entity_group_id, 'pagerank': score})
            driver = MagicMock()
            with patch('redes_centralidades.carregar_estrutura', return_value=loaded), \
                 patch('redes_centralidades._configuration', return_value=('uri', 'user', 'pw', 'neo4j')), \
                 patch('redes_centralidades.verificar_projecao'), \
                 patch('redes_centralidades.executar_pagerank', return_value=(raw, {'pagerank_seconds': .1})) as run:
                first = analisar_centralidades(root, executar_gds=True, driver_factory=lambda *a, **k: driver)
                second = analisar_centralidades(root, executar_gds=True)
                self.assertEqual(run.call_count, 1)
                self.assertEqual(first['output_directory'], second['output_directory'])
                self.assertTrue(first['all_pagerank_nodes_verified'])
                self.assertEqual(first['database_writes'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
