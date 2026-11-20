"""Verificações de caminhos mínimos, retomada e integridade dos resultados."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from redes_distancias import (preparar_componente, conferir_algoritmo, processar_blocos,
                              resumir_blocos, ler_blocos, gerar_figuras, calcular_distancias)


class DistanciasTests(unittest.TestCase):
    def run_graph(self, n, edges):
        graph = np.zeros((n, n))
        for a, b in edges:
            graph[a, b] = graph[b, a] = 1
        graph = csr_matrix(graph)
        conferir_algoritmo(graph)
        with tempfile.TemporaryDirectory() as directory:
            blocks = processar_blocos(graph, np.arange(n) + 10, Path(directory), 'test', tamanho_bloco=2)
            return resumir_blocos(blocks, n, len(edges))

    def test_path_exact(self):
        rows, dist, s = self.run_graph(5, [(0, 1), (1, 2), (2, 3), (3, 4)])
        self.assertEqual((s['diameter'], s['radius'], s['average_distance']), (4, 2, 2))
        self.assertEqual(rows.eccentricity.tolist(), [4, 3, 2, 3, 4])
        self.assertEqual(dist.ordered_pairs.tolist(), [8, 6, 4, 2])

    def test_cycle_and_complete(self):
        for edges, diameter, radius, mean in [
            ([(0, 1), (1, 2), (2, 3), (3, 0)], 2, 2, 4/3),
            ([(a, b) for a in range(4) for b in range(a+1, 4)], 1, 1, 1)]:
            _, _, s = self.run_graph(4, edges)
            self.assertEqual(s['diameter'], diameter)
            self.assertEqual(s['radius'], radius)
            self.assertAlmostEqual(s['average_distance'], mean)

    def test_singleton(self):
        _, _, s = self.run_graph(1, [])
        self.assertEqual(s['diameter'], 0)
        self.assertEqual(s['radius'], 0)
        self.assertIsNone(s['average_distance'])

    def test_resume_and_tamper(self):
        graph = csr_matrix([[0, 1, 0], [1, 0, 1], [0, 1, 0]])
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            partial = processar_blocos(graph, [10, 11, 12], folder, 'x', max_fontes=1)
            _, _, s = resumir_blocos(partial, 3, 2)
            self.assertIsNone(s['average_distance'])
            self.assertIsNone(s['diameter'])
            first = next(folder.glob('bloco*'))
            original = first.read_bytes()
            full = processar_blocos(graph, [10, 11, 12], folder, 'x')
            self.assertEqual(first.read_bytes(), original)
            self.assertEqual(len(full), 2)
            with patch('scipy.sparse.csgraph.dijkstra', side_effect=AssertionError('recomputed')):
                self.assertEqual(len(processar_blocos(graph, [10, 11, 12], folder, 'x')), 2)
            payload = json.loads(first.read_text())
            payload['rows'][0]['distance_sum'] = 999
            first.write_text(json.dumps(payload))
            with self.assertRaises(ValueError):
                ler_blocos(folder, 'x', [10, 11, 12])

    def test_partition_and_tie_break(self):
        metrics = pd.DataFrame({'entity_group_id': [10, 11, 20, 21], 'degree': [1]*4,
                                'component_id': [10, 10, 20, 20]})
        pairs = pd.DataFrame({'source_id': [10, 20], 'target_id': [11, 21]})
        components = pd.DataFrame({'component_id': [20, 10], 'nodes': [2, 2]})
        selected, graph = preparar_componente(metrics, pairs, components)
        self.assertEqual(selected.entity_group_id.tolist(), [10, 11])
        self.assertEqual(graph.nnz, 2)
        bad = metrics.copy()
        bad.loc[0, 'component_id'] = 20
        with self.assertRaises(ValueError):
            preparar_componente(bad, pairs, components)
        with self.assertRaises(ValueError):
            preparar_componente(metrics, pd.concat([pairs, pairs]), components)

    def test_disconnected_fails(self):
        with self.assertRaises(ValueError):
            conferir_algoritmo(csr_matrix(np.zeros((2, 2))))

    def test_figures(self):
        rows, dist, _ = self.run_graph(3, [(0, 1), (1, 2)])
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.assertEqual(len(gerar_figuras(folder, dist, rows)), 2)
            self.assertEqual(len(list(folder.iterdir())), 6)

    def test_dry_run_and_parent_mismatch(self):
        structural = {'summary': {'largest_component_nodes': 5}}
        with patch('redes_distancias.carregar_estrutura', return_value=(None, structural, None, {}, None, {'snapshot_sha256': 'a'})):
            with tempfile.TemporaryDirectory() as directory:
                self.assertEqual(calcular_distancias(directory)['api_calls'], 0)
                self.assertEqual(list(Path(directory).iterdir()), [])
                with self.assertRaises(ValueError):
                    calcular_distancias(directory, assinatura_rede_esperada='b')

    def test_full_workflow_partial_complete_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            structural = root / 'structural'
            projection = root / 'projection'
            structural.mkdir()
            projection.mkdir()
            metrics = pd.DataFrame({'entity_group_id': [10, 11, 12], 'degree': [1, 2, 1],
                'component_id': [10, 10, 10], 'entity_group_name': ['A', 'B', 'C'], 'ent_label': ['PESSOA']*3})
            metrics.to_csv(structural / 'metricas_nos.csv.gz', index=False)
            pd.DataFrame({'component_id': [10], 'nodes': [3]}).to_csv(structural / 'componentes.csv', index=False)
            pd.DataFrame({'source_id': [10, 11], 'target_id': [11, 12]}).to_csv(
                projection / 'simples_nao_dirigida.csv.gz', index=False)
            loaded = (structural, {'snapshot_sha256': 's', 'summary': {'largest_component_nodes': 3}},
                      projection, {'snapshot_sha256': 'p'}, None, {'snapshot_sha256': 'n'})
            with patch('redes_distancias.carregar_estrutura', return_value=loaded):
                pilot = calcular_distancias(root, executar=True, max_fontes=1)
                self.assertEqual(pilot['status'], 'PARTIAL')
                self.assertFalse((root / 'resultados/distancias/atual.json').exists())
                final = calcular_distancias(root, executar=True)
                self.assertEqual(final['status'], 'COMPLETE')
                self.assertAlmostEqual(final['average_distance'], 4/3)
                self.assertEqual(final['diameter'], 2)
                self.assertEqual(final['radius'], 1)
                with patch('scipy.sparse.csgraph.dijkstra', side_effect=AssertionError('recomputed')):
                    cached = calcular_distancias(root, executar=True)
                self.assertEqual(cached['output_directory'], final['output_directory'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
