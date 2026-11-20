"""Verificações de cobertura, identidades e denominadores documentais."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pandas as pd
import redes_cobertura as r


class CoberturaTests(unittest.TestCase):
    def setUp(self):
        self.n = pd.DataFrame([
            {'news_id': str(i), 'news_version_id': 'v'+str(i), 'source': 'G1',
             'publication_year': '2025', 'publication_date': '2025-01-02', 're_state': estado}
            for i, estado in enumerate(['SUCCESS', 'SUCCESS_ZERO', 'PARTIAL', 'PENDING', 'TOO_FEW_MENTIONS'])])
        self.e = pd.DataFrame([
            {'edge_id': 'e'+str(i), 'news_id': str(i), 'news_version_id': 'v'+str(i),
             'source': 'G1', 'publication_year': '2025', 'occurrence_count': '2'}
            for i in [0, 2]])

    def test_denominators_and_zero_success(self):
        n, a, f, s, c = r.preparar_tabelas(self.n, self.e)
        g = a.loc[a.source.eq('G1')].iloc[0]
        self.assertEqual(g.corpus_news, 5)
        self.assertEqual(g.re_completed_strict, 2)
        self.assertEqual(g.re_partial, 1)
        self.assertEqual(g.too_few_mentions, 1)
        self.assertEqual(g.re_other_states, 1)
        self.assertEqual(g.completed_without_retained_relations, 1)
        self.assertEqual(g.support_news, 2)
        self.assertEqual(g.retained_occurrences, 4)
        self.assertEqual(g.strict_completion_share, .4)
        self.assertTrue(a.loc[a.source.eq('CNN Brasil'), 'support_share'].isna().all())
        self.assertFalse(c.common_year_with_support.any())
        self.assertEqual(s.news_count.sum(), 5)

    def test_version_mismatch_rejected(self):
        self.e.loc[0, 'news_version_id'] = 'other'
        with self.assertRaises(ValueError): r.preparar_tabelas(self.n, self.e)

    def test_duplicate_evidence_rejected(self):
        with self.assertRaises(ValueError): r.preparar_tabelas(self.n, pd.concat([self.e, self.e]))

    def test_wrong_source_rejected(self):
        self.e.loc[0, 'source'] = 'CNN Brasil'
        with self.assertRaises(ValueError): r.preparar_tabelas(self.n, self.e)

    def test_success_zero_with_support_rejected(self):
        self.n.loc[0, 're_state'] = 'SUCCESS_ZERO'
        with self.assertRaises(ValueError): r.preparar_tabelas(self.n, self.e)

    def test_dry_run_writes_nothing_and_checks_edition(self):
        with TemporaryDirectory() as temp, patch.object(r, 'carregar_rede', return_value=(Path(temp), {'snapshot_sha256': 'a'*64})):
            out = r.gerar_cobertura(temp, assinatura_rede_esperada='a'*64)
            self.assertEqual(out['files_written'], 0)
            self.assertEqual(list(Path(temp).iterdir()), [])
            with self.assertRaises(ValueError): r.gerar_cobertura(temp, assinatura_rede_esperada='b'*64)


if __name__ == '__main__':
    unittest.main(verbosity=2)
