"""Verificações de cobertura anual e acumulação com intervalos desiguais."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pandas as pd
import temporal_planejamento as r


class TemporalTests(unittest.TestCase):
    def setUp(self):
        self.n=pd.DataFrame({'news_id':['a','b','c'],'news_version_id':['v1','v2','v3'],
            'source':[r.FONTE]*3,'publication_year':['1994','1995','1996'],
            'publication_date_precision':['ANO']*3,'re_state':['SUCCESS','PENDING','SUCCESS']})
        self.a=pd.DataFrame({'edge_id':['x','y'],'source_id':['1','2'],'target_id':['2','3']})
        self.e=pd.DataFrame({'edge_id':['x','y'],'news_id':['a','c'],'news_version_id':['v1','v3'],
            'source':[r.FONTE]*2,'publication_year':['1994','1996'],'occurrence_count':['2','3']})

    def test_missing_re_does_not_imply_no_corpus(self):
        tables=r.calcular_cobertura(self.n,self.a,self.e,marcos=[1994,1996])
        annual=tables['cobertura_anual.csv'].set_index('publication_year')
        self.assertEqual(annual.loc[1995,'corpus_news'],1)
        self.assertEqual(annual.loc[1995,'support_news'],0)
        self.assertTrue(annual.loc[1995,'no_completed_re_in_year'])
        self.assertEqual(annual.loc[1995,'cumulative_nodes'],2)

    def test_intervening_years_and_distinct_cumulative_ids(self):
        table=r.calcular_cobertura(self.n,self.a,self.e,marcos=[1994,1996])['marcos_planejados.csv']
        last=table.iloc[-1]
        self.assertEqual(last.interval_calendar_years,2)
        self.assertEqual(last.interval_corpus_news,2)
        self.assertEqual(last.cumulative_nodes,3)
        self.assertEqual(last.cumulative_retained_occurrences,5)

    def test_partial_is_not_strict_completion(self):
        self.n.loc[0,'re_state']='PARTIAL'
        row=r.calcular_cobertura(self.n,self.a,self.e)['cobertura_anual.csv'].iloc[0]
        self.assertEqual(row.re_completed_strict,0)
        self.assertEqual(row.re_partial,1)
        self.assertEqual(row.support_news,1)

    def test_version_mismatch_rejected(self):
        self.e.loc[0,'news_version_id']='other'
        with self.assertRaises(ValueError):r.calcular_cobertura(self.n,self.a,self.e)

    def test_marcos_validation(self):
        for bad in [[1996,1994],[1994,1994],[2026]]:
            with self.assertRaises(ValueError):r.calcular_cobertura(self.n,self.a,self.e,marcos=bad)

    def test_dry_run_no_files(self):
        with TemporaryDirectory() as temp,patch.object(r,'carregar_rede',return_value=(Path(temp),{'snapshot_sha256':'a'*64})):
            out=r.planejar_evolucao_temporal(temp)
            self.assertEqual(out['snapshot_count'],32)
            self.assertTrue(out['include_intervening_years'])
            self.assertEqual(list(Path(temp).iterdir()),[])


if __name__=='__main__':unittest.main(verbosity=2)
