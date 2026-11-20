"""Testes de recorte acumulado, proveniência, retomada e transições."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pandas as pd
import temporal_redes as r


class RedesTemporaisTests(unittest.TestCase):
    def setUp(self):
        self.n = pd.DataFrame([
            {'news_id': str(i), 'news_version_id': 'v'+str(i), 'source': fonte,
             'publication_year': ano, 'publication_date': ano+'-01-01',
             'publication_date_precision': 'DIA', 're_state': 'SUCCESS', 'link': 'https://exemplo/'+str(i)}
            for i, (fonte, ano) in enumerate([(r.FONTE,'1994'),(r.FONTE,'1995'),('G1','1994'),(r.FONTE,'2026')])])
        self.v = pd.DataFrame([{'entity_group_id':str(i),'entity_group_name':'Nome'+str(i),'ent_label':'PESSOA'} for i in [1,2]])
        self.a = pd.DataFrame([{'edge_id':'x','source_id':'1','target_id':'2','label':'autor_de','relation_macro':'outra','weight':'100'}])
        self.e = self.n.copy().assign(edge_id='x',occurrence_count=['2','3','90','5'],
            review_records='0',provisional_records='0',semantic_flag_records='0')
        self.nn = pd.concat([self.n.assign(entity_group_id=str(i),mention_count='1',review_mentions='0',
            relation_participation_count=['2','3','90','5']) for i in [1,2]],ignore_index=True)
        self.inputs = dict(zip(r.ENTRADAS,[self.n,self.v,self.a,self.nn,self.e]))

    def build(self, year):
        return r.construir_fonte(*(self.inputs[n] for n in r.ENTRADAS),fonte=r.FONTE,
            inicio=pd.Timestamp('1994-01-01'),fim=pd.Timestamp(f'{year}-12-31'))

    def test_annual_cumulative_scope_and_provenance(self):
        t94,s94=self.build(1994);t95,s95=self.build(1995)
        self.assertEqual(s94['weight_sum'],2)
        self.assertEqual(s95['weight_sum'],5)
        self.assertEqual(set(t95['noticias.csv.gz'].news_id),{'0','1'})
        self.assertEqual(t95['nos.csv.gz'].weighted_strength.sum(),10)
        audit=r.validar_transicao(t94,t95,1995)
        self.assertEqual(audit['new_nodes'],0)
        self.assertEqual(t95['arestas.csv.gz'].distinct_news_count.iloc[0],2)

    def test_declining_weight_rejected(self):
        t,_=self.build(1994);changed={k:v.copy() for k,v in t.items()}
        changed['arestas.csv.gz']['weight']=1
        with self.assertRaises(ValueError):r.validar_transicao(t,changed,1995)

    def test_changed_canonical_name_rejected(self):
        t,_=self.build(1994);changed={k:v.copy() for k,v in t.items()}
        changed['nos.csv.gz'].loc[0,'entity_group_name']='Outro'
        with self.assertRaises(ValueError):r.validar_transicao(t,changed,1995)

    def test_dry_run_creates_nothing(self):
        with TemporaryDirectory() as td,patch.object(r,'carregar_rede',return_value=(Path(td),{'snapshot_sha256':'a'*64})):
            self.assertEqual(r.construir_redes_temporais(td)['snapshot_count'],32)
            self.assertEqual(list(Path(td).iterdir()),[])

    def test_full_series_resume_and_modified_output_rejected(self):
        with TemporaryDirectory() as td:
            root=Path(td);src=root/'entrada';src.mkdir()
            for name,df in self.inputs.items():r.write_csv(src,name,df)
            meta={'snapshot_sha256':'a'*64}
            with patch.object(r,'carregar_rede',return_value=(src,meta)):
                first=r.construir_redes_temporais(root,executar=True)
                self.assertEqual(first['new_snapshots_this_run'],32)
                folder,_=r.carregar_redes_temporais(root,'a'*64)
                original=r.construir_fonte
                with patch.object(r,'construir_fonte',wraps=original) as build:
                    build.__code__=original.__code__
                    second=r.construir_redes_temporais(root,executar=True)
                    self.assertEqual(second['reused_snapshots_this_run'],32)
                    self.assertEqual(build.call_count,0)
                with (folder/'1994/nos.csv.gz').open('ab') as f:f.write(b'alterado')
                with self.assertRaises(ValueError):r.carregar_redes_temporais(root)


if __name__=='__main__':unittest.main(verbosity=2)
