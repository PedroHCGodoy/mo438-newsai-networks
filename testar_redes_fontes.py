"""Verificações de recálculo por fonte e preservação da proveniência."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pandas as pd
import redes_fontes as r


class FontesTests(unittest.TestCase):
    def setUp(self):
        self.news = pd.DataFrame([
            {'news_id': str(i), 'news_version_id': 'v'+str(i), 'source': fonte,
             'publication_year': ano, 'publication_date': ano+'-01-01',
             'publication_date_precision': 'DIA', 're_state': 'SUCCESS', 'link': 'https://exemplo/'+str(i)}
            for i, (fonte, ano) in enumerate([('G1', '2025'), ('CNN Brasil', '2025'), ('G1', '2024')])])
        self.nodes = pd.DataFrame([{'entity_group_id': str(i), 'entity_group_name': 'Nome', 'ent_label': 'PESSOA'} for i in [1, 2]])
        self.edges = pd.DataFrame([{'edge_id': 'x', 'source_id': '1', 'target_id': '2', 'label': 'autor_de', 'relation_macro': 'outra', 'weight': '100'}])
        self.evidence = self.news.copy()
        self.evidence['edge_id'] = 'x'
        self.evidence['occurrence_count'] = ['3', '7', '90']
        for col in r.FLAGS: self.evidence[col] = '0'
        self.nn = pd.concat([self.news.assign(entity_group_id=str(i), mention_count='1', review_mentions='0',
                            relation_participation_count=['3', '7', '90']) for i in [1, 2]], ignore_index=True)

    def build(self):
        return r.construir_fonte(self.news, self.nodes, self.edges, self.nn, self.evidence,
                                fonte='G1', inicio=pd.Timestamp('2025-01-01'), fim=pd.Timestamp('2025-12-31'))

    def test_source_and_time_weights_not_global(self):
        tables, summary = self.build()
        self.assertEqual(summary['weight_sum'], 3)
        self.assertEqual(summary['selected_news'], 1)
        self.assertEqual(tables['arestas.csv.gz'].iloc[0].edge_id, 'x')
        self.assertEqual(set(tables['nos.csv.gz'].entity_group_id), {'1', '2'})
        self.assertEqual(tables['nos.csv.gz'].weighted_strength.sum(), 6)
        self.assertEqual(tables['nos.csv.gz'].mention_count.sum(), 2)
        self.assertEqual(tables['ponderada_nao_dirigida.csv.gz'].weight.sum(), 3)
        self.assertEqual(tables['simples_nao_dirigida.csv.gz'].weight.sum(), 1)
        self.assertEqual(tables['noticias.csv.gz'].iloc[0].link, 'https://exemplo/0')

    def test_input_frames_unchanged(self):
        frames = [self.news, self.nodes, self.edges, self.nn, self.evidence]
        copies = [x.copy(deep=True) for x in frames]
        self.build()
        for a, b in zip(frames, copies): pd.testing.assert_frame_equal(a, b)

    def test_different_version_rejected(self):
        self.evidence.loc[0, 'news_version_id'] = 'other'
        with self.assertRaises(ValueError): self.build()

    def test_self_loop_rejected(self):
        self.edges.loc[0, 'target_id'] = '1'
        with self.assertRaises(ValueError): self.build()

    def test_duplicate_evidence_rejected(self):
        self.evidence = pd.concat([self.evidence, self.evidence])
        with self.assertRaises(ValueError): self.build()

    def test_imprecise_date_rejected(self):
        self.news.loc[0, 'publication_date_precision'] = 'ANO'
        with self.assertRaises(ValueError): self.build()

    def test_node_participation_mismatch_rejected(self):
        self.nn.loc[0, 'relation_participation_count'] = '4'
        with self.assertRaises(ValueError): self.build()

    def test_dry_run_and_wrong_snapshot(self):
        with TemporaryDirectory() as temp, patch.object(r, 'carregar_rede', return_value=(Path(temp), {'snapshot_sha256': 'a'*64})):
            out = r.construir_redes_fontes(temp, assinatura_rede_esperada='a'*64)
            self.assertEqual(out['files_written'], 0)
            self.assertEqual(list(Path(temp).iterdir()), [])
            with self.assertRaises(ValueError): r.construir_redes_fontes(temp, assinatura_rede_esperada='b'*64)


if __name__ == '__main__':
    unittest.main(verbosity=2)
