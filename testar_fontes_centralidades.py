"""Verificações de PageRank, rankings e proveniência documental."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import numpy as np
import pandas as pd
import fontes_centralidades as r
from redes_centralidades import pagerank_referencia


class ProtagonismoTests(unittest.TestCase):
    def frame(self, ids):
        return pd.DataFrame({'entity_group_id':ids,'entity_group_name':['Nome']*len(ids),
            'ent_label':['PESSOA']*len(ids),'neighbor_degree':[1]*len(ids),
            'weighted_strength':[2]*len(ids),'pagerank_share':[1/len(ids)]*len(ids)})

    def test_weighted_pagerank_with_dangling_nodes(self):
        edges=pd.DataFrame({'source_id':[1,1],'target_id':[2,3],'weight':[1,3]})
        score,_=pagerank_referencia([1,2,3],edges)
        np.testing.assert_allclose(score,[.15,.181875,.245625],rtol=1e-10)
        frame=pd.DataFrame({'entity_group_id':[1,2,3]})
        out,proof=r.validar_pagerank(frame,pd.DataFrame({'entity_group_id':[1,2,3],'pagerank':score}),edges)
        self.assertAlmostEqual(out.pagerank_share.sum(),1)
        self.assertTrue(proof['all_nodes_compared'])

    def test_wrong_pagerank_rejected(self):
        edges=pd.DataFrame({'source_id':[1],'target_id':[2],'weight':[1]})
        with self.assertRaises(ValueError):
            r.validar_pagerank(pd.DataFrame({'entity_group_id':[1,2]}),pd.DataFrame({'entity_group_id':[1,2],'pagerank':[1,1]}),edges)

    def test_ties_have_deterministic_top_limit(self):
        a=self.frame(list(range(1,23)));b=self.frame(list(range(2,24)))
        comparison,overlap=r.comparar_rankings({'cnn':a,'g1':b})
        self.assertTrue(comparison['rank'].eq(1).all())
        self.assertTrue(overlap.intersection.eq(19).all())
        self.assertTrue(overlap.size_a.eq(20).all())

    def test_absence_is_not_imputed(self):
        comparison,_=r.comparar_rankings({'cnn':self.frame([1]),'g1':self.frame([2])})
        self.assertEqual(len(comparison),6)
        self.assertEqual(set(comparison.loc[comparison.source_key.eq('cnn')].entity_group_id),{1})

    def test_news_support_identity_and_counts(self):
        f=pd.DataFrame({'entity_group_id':[1],'relation_news_count':[1]})
        nn=pd.DataFrame({'entity_group_id':[1],'news_id':['n'],'news_version_id':['v'],
            'mention_count':[2],'relation_participation_count':[3]})
        news=pd.DataFrame({'news_id':['n'],'news_version_id':['v'],'title':['Título'],'link':['https://exemplo']})
        out=r.noticias_suporte(f,nn,news)
        self.assertEqual(out.iloc[0].link,'https://exemplo')
        news.loc[0,'news_version_id']='other'
        with self.assertRaises(ValueError):r.noticias_suporte(f,nn,news)

    def test_dry_run_no_connection_or_files(self):
        with TemporaryDirectory() as temp,patch.object(r,'carregar_fontes',return_value=(Path(temp),{})),patch.object(r,'carregar_estrutura_fontes',return_value=(Path(temp),{})):
            out=r.analisar_centralidades_fontes(temp)
            self.assertEqual(out['files_written'],0)
            self.assertEqual(out['neo4j_connections'],0)
            self.assertEqual(list(Path(temp).iterdir()),[])


class ProjecaoTemporariaTests(unittest.TestCase):
    def executar(self, session, name='newsai_fontes_test_g1_directed_test', expected=None):
        return r.pagerank_projetado(session, name=name, expected_name=expected or name, tag='tag', database='neo4j',
            frame=pd.DataFrame({'entity_group_id':[1,2]}),
            edges=pd.DataFrame({'source_id':[1],'target_id':[2],'weight':[1]}), simple=pd.DataFrame())

    def session(self, fail_creation=False):
        class Result:
            def consume(self):pass
        class Session:
            def __init__(self):self.calls=[]
            def run(self,q,**params):
                self.calls.append((q,params))
                if fail_creation and q==r.PROJETAR:raise MemoryError('simulated')
                return Result()
        return Session()

    def test_release_after_success(self):
        session=self.session()
        with patch.object(r,'query',return_value=[{'exists':False}]),patch.object(r,'verificar_projecao',return_value={}),patch.object(r,'executar_pagerank',return_value=(pd.DataFrame(),{})):
            self.executar(session)
        self.assertIn('gds.graph.drop',session.calls[-1][0])
        self.assertEqual(len(session.calls),2)

    def test_release_after_algorithm_failure(self):
        session=self.session()
        with patch.object(r,'query',return_value=[{'exists':False}]),patch.object(r,'verificar_projecao',return_value={}),patch.object(r,'executar_pagerank',side_effect=ValueError('simulated')):
            with self.assertRaises(ValueError):self.executar(session)
        self.assertIn('gds.graph.drop',session.calls[-1][0])

    def test_attempt_release_after_projection_failure(self):
        session=self.session(fail_creation=True)
        with patch.object(r,'query',return_value=[{'exists':False}]):
            with self.assertRaises(MemoryError):self.executar(session)
        self.assertIn('gds.graph.drop',session.calls[-1][0])

    def test_reject_unrelated_name_before_query(self):
        session=self.session()
        with self.assertRaises(ValueError):self.executar(session,name='global_structural')
        self.assertEqual(session.calls,[])


if __name__=='__main__':
    unittest.main(verbosity=2)
