"""Verificações da comparação, fórmulas e conferência independente."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pandas as pd
import fontes_estrutural as r


class ComparacaoTests(unittest.TestCase):
    def test_reciprocity_ignores_label_duplicates(self):
        edges = pd.DataFrame({'source_id': [1, 1, 2, 2], 'target_id': [2, 2, 1, 3]})
        result = r.reciprocidade(edges)
        self.assertEqual(result['distinct_directed_pairs'], 3)
        self.assertEqual(result['reciprocal_dyads'], 1)
        self.assertAlmostEqual(result['directed_pair_reciprocity'], 2/3)

    def test_jaccard_and_direction(self):
        x = {'a': {'nodes': {1,2}, 'directed_pairs': {(1,2)}},
             'b': {'nodes': {2,3}, 'directed_pairs': {(2,1)}}}
        out = r.comparar_conjuntos(x).set_index('element_type')
        self.assertAlmostEqual(out.loc['nodes', 'jaccard'], 1/3)
        self.assertEqual(out.loc['directed_pairs', 'intersection'], 0)

    def test_triangle_and_disconnected_component(self):
        nodes = pd.DataFrame({'entity_group_id': [1,2,3,4,5]})
        simple = pd.DataFrame({'source_id': [1,2,1,4], 'target_id': [2,3,3,5]})
        raw = r.calcular_referencia(nodes.entity_group_id, zip(simple.source_id, simple.target_id))
        result = r.verificar_metricas(raw, nodes, simple)[-1]
        self.assertEqual(result['triangles'], 1)
        self.assertEqual(result['connected_components'], 2)
        self.assertAlmostEqual(result['mean_local_clustering_degree_ge_two'], 1)
        self.assertAlmostEqual(result['density'], .4)
        self.assertAlmostEqual(result['largest_component_share'], .6)

    def test_mismatched_gds_result_rejected(self):
        nodes = pd.DataFrame({'entity_group_id': [1,2,3]})
        simple = pd.DataFrame({'source_id': [1,2], 'target_id': [2,3]})
        raw = r.calcular_referencia(nodes.entity_group_id, zip(simple.source_id, simple.target_id))
        raw.loc[0, 'degree'] = 2
        raw.loc[1, 'degree'] = 1
        with self.assertRaises(ValueError): r.verificar_metricas(raw, nodes, simple)

    def test_projection_query_uses_input_pairs_and_unit_weight(self):
        self.assertIn('UNWIND $rows', r.PROJETAR)
        self.assertIn('weight:1.0', r.PROJETAR)
        self.assertIn('undirectedRelationshipTypes', r.PROJETAR)
        self.assertNotIn('CREATE ', r.PROJETAR)

    def test_dry_run_no_connection_or_files(self):
        with TemporaryDirectory() as temp, patch.object(r, 'carregar_fontes', return_value=(Path(temp), {'start_date': '2025-01-01', 'end_date': '2025-12-31'})):
            result = r.comparar_estrutura_fontes(temp)
            self.assertEqual(result['neo4j_connections'], 0)
            self.assertEqual(result['files_written'], 0)
            self.assertEqual(list(Path(temp).iterdir()), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
