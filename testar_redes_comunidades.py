"""Verificações de partições, modularidade, conectividade, concordância e retomada."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import numpy as np
import pandas as pd
from redes_comunidades import (configuracoes, canonizar_particao, comparar_particoes,
    avaliar_particao, tabela_comparacoes, gerar_figuras, detectar_comunidades)


def entradas():
    nodes = pd.DataFrame({'entity_group_id': list(range(6)), 'entity_group_name': list('ABCDEF'),
        'ent_label': ['PESSOA', 'ORGANIZACAO', 'LOCAL']*2, 'component_id': [0]*6,
        'pagerank': [1, 2, 3, 4, 5, 6]})
    pairs = pd.DataFrame({'source_id': [0, 0, 1, 2, 3, 3, 4], 'target_id': [1, 2, 2, 3, 4, 5, 5], 'weight': [1]*7})
    raw = pd.DataFrame({'entity_group_id': list(range(6)), 'community_id': [100]*3 + [200]*3})
    return nodes, pairs, canonizar_particao(raw, nodes.entity_group_id)


class ComunidadesTests(unittest.TestCase):
    def test_canonical_ids_and_complete_universe(self):
        nodes, _, p = entradas()
        self.assertEqual(p.community_id.tolist(), [0, 0, 0, 3, 3, 3])
        with self.assertRaises(ValueError):canonizar_particao(p.iloc[:5], nodes.entity_group_id)
        with self.assertRaises(ValueError):canonizar_particao(pd.concat([p, p.iloc[:1]]), nodes.entity_group_id)
        bad = p.copy();bad['community_id'] = bad.community_id.astype(float);bad.loc[0, 'community_id'] = .5
        with self.assertRaises(ValueError):canonizar_particao(bad, nodes.entity_group_id)

    def test_modularity_dense_independent(self):
        nodes, pairs, p = entradas()
        f, stats, top, summary = avaliar_particao(nodes, pairs, p, gcc_component_id=0)
        self.assertAlmostEqual(summary['weighted_modularity'], 5/14)
        self.assertEqual(stats.connected_pieces.tolist(), [1, 1])
        self.assertEqual(stats.boundary_weight.tolist(), [1, 1])
        self.assertTrue(np.allclose(stats.conductance, 1/7))
        a = np.zeros((6, 6))
        for row in pairs.itertuples(index=False):a[row.source_id, row.target_id] = a[row.target_id, row.source_id] = row.weight
        degree = a.sum(axis=1);labels = p.community_id.to_numpy()
        q = sum((a[i,j] - degree[i]*degree[j]/a.sum()) for i in range(6) for j in range(6) if labels[i]==labels[j])/a.sum()
        self.assertAlmostEqual(q, summary['weighted_modularity'])
        self.assertEqual(len(top), 6)

    def test_disconnected_community_is_flagged_preserved(self):
        nodes = pd.DataFrame({'entity_group_id': [0, 1, 2, 3], 'ent_label': ['PESSOA']*4,
            'component_id': [0, 0, 2, 2], 'pagerank': [1]*4})
        pairs = pd.DataFrame({'source_id': [0, 2], 'target_id': [1, 3], 'weight': [1, 1]})
        p = canonizar_particao(pd.DataFrame({'entity_group_id': [0, 1, 2, 3], 'community_id': [0]*4}), range(4))
        f, stats, _, summary = avaliar_particao(nodes, pairs, p, gcc_component_id=0)
        self.assertEqual(summary['disconnected_communities'], 1)
        self.assertEqual(summary['communities_spanning_original_components'], 1)
        self.assertEqual(stats.connected_pieces.iloc[0], 2)
        self.assertEqual(f.community_id.nunique(), 1)

    def test_partition_metrics_known(self):
        self.assertEqual(comparar_particoes([0,0,1,1], [7,7,9,9]), {'ari': 1., 'nmi': 1.})
        cross = comparar_particoes([0,0,1,1], [0,1,0,1])
        self.assertAlmostEqual(cross['ari'], -.5);self.assertAlmostEqual(cross['nmi'], 0)
        self.assertEqual(comparar_particoes([0]*4, [0,1,2,3]), {'ari': 0., 'nmi': 0.})
        self.assertEqual(comparar_particoes([0], [3]), {'ari': 1., 'nmi': 1.})
        with self.assertRaises(ValueError):comparar_particoes([], [])

    def test_partition_metrics_against_sklearn_when_available(self):
        try:
            from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score
        except ImportError:
            self.skipTest('scikit-learn é opcional para esta conferência externa.')
        rng = np.random.default_rng(42)
        for n in [2, 10, 100, 1000]:
            a, b = rng.integers(0, 5, n), rng.integers(0, 10, n)
            result = comparar_particoes(a, b)
            self.assertAlmostEqual(result['ari'], adjusted_rand_score(a, b), places=12)
            self.assertAlmostEqual(result['nmi'], normalized_mutual_info_score(a, b, average_method='arithmetic'), places=12)

    def test_config_parameters(self):
        runs = configuracoes([42,43,44])
        self.assertEqual(len(runs), 4)
        self.assertNotIn('randomSeed', runs['louvain']['config'])
        self.assertEqual(runs['leiden_seed_42']['config']['gamma'], 1.)
        for bad in [[], [42,42], [-1], [True], [1.2]]:
            with self.assertRaises(ValueError):configuracoes(bad)

    def test_comparisons_and_figures(self):
        nodes, pairs, p = entradas()
        _, stats, _, _ = avaliar_particao(nodes, pairs, p, gcc_component_id=0)
        partitions = {'louvain': p, 'leiden_seed_42': p}
        comparisons = tabela_comparacoes(partitions, nodes, 0)
        self.assertEqual(len(comparisons), 2)
        allstats = pd.concat([stats.assign(run_id=k) for k in partitions], ignore_index=True)
        with tempfile.TemporaryDirectory() as directory:
            catalog = gerar_figuras(Path(directory), allstats, comparisons, 'leiden_seed_42')
            self.assertEqual(len(catalog), 3)
            self.assertEqual(len(list(Path(directory).iterdir())), 9)

    def test_full_workflow_failure_resume_cache(self):
        nodes, pairs, partition = entradas()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ['s','p','n','c']:(root/name).mkdir()
            nodes.drop(columns='component_id').to_csv(root/'c/centralidades_nos.csv.gz', index=False)
            nodes[['entity_group_id','component_id']].to_csv(root/'s/metricas_nos.csv.gz', index=False)
            pairs.to_csv(root/'p/ponderada_nao_dirigida.csv.gz', index=False)
            loaded = (root/'s', {'snapshot_sha256':'s'}, root/'p', {'snapshot_sha256':'p',
                'graph_names':{'community':'g'}, 'summary':{'undirected_pairs':7}}, root/'n',
                {'snapshot_sha256':'n', 'summary':{'nodes':6}})
            driver = MagicMock()
            driver.session.return_value.__enter__.return_value.execute_read.return_value = [{'version':'simulated'}]
            calls = []
            def algorithm(session, name, kind, config):
                calls.append(kind)
                if len(calls)==2:raise RuntimeError('Interrupção simulada após o primeiro checkpoint.')
                return partition[['entity_group_id','community_id']], {'gds_version':'simulated', 'elapsed_seconds':.1}
            with patch('redes_comunidades.carregar_estrutura', return_value=loaded), \
                 patch('redes_comunidades.carregar_centralidades', return_value=(root/'c', {'snapshot_sha256':'c'})), \
                 patch('redes_comunidades._configuration', return_value=('uri','user','pw','db')), \
                 patch('redes_comunidades.verificar_projecao'), \
                 patch('redes_comunidades.executar_algoritmo', side_effect=algorithm):
                self.assertEqual(detectar_comunidades(root)['api_calls'], 0)
                with self.assertRaises(RuntimeError):
                    detectar_comunidades(root, executar_gds=True, sementes_leiden=(42,), driver_factory=lambda *a, **k:driver)
                result = detectar_comunidades(root, executar_gds=True, sementes_leiden=(42,), driver_factory=lambda *a, **k:driver)
                self.assertEqual(calls.count('louvain'), 1)
                self.assertEqual(result['run_count'], 2)
                cached = detectar_comunidades(root, executar_gds=True, sementes_leiden=(42,))
                self.assertEqual(result['output_directory'], cached['output_directory'])
                self.assertEqual(len(calls), 3)
                self.assertTrue(result['all_nodes_assigned_in_all_runs'])


if __name__ == '__main__':unittest.main(verbosity=2)
