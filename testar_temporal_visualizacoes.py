"""Seleção temporal, evidência por corte e incorporação segura de dados."""
import unittest
import json
import pandas as pd
from temporal_visualizacoes import selecionar_vista, conferir_evidencias, json_seguro, destaques_automaticos


def dados():
    nodes=pd.DataFrame({'entity_group_id':[1,2,3,4], 'degree':[3,2,2,1]})
    pairs=pd.DataFrame({'source_id':[1,1,1,2], 'target_id':[2,3,4,3],
        'weight':[1,2,3,99], 'pair_id':['a','b','c','d'], 'distinct_news_count':[1,1,1,1]})
    return nodes,pairs


class VistasTemporaisTests(unittest.TestCase):
    def test_automatic_leaders_include_boundary_ties(self):
        nodes=pd.DataFrame({'entity_group_id':list(range(1,19)), 'degree':[100-i for i in range(14)]+[70,70,70,10]})
        selected=destaques_automaticos(nodes)
        self.assertEqual(len(selected),17)
        self.assertEqual(set(selected.entity_group_id),set(range(1,18)))
        self.assertEqual(len(destaques_automaticos(nodes.iloc[:7])),7)

    def test_top_degree_and_ties(self):
        n,e=selecionar_vista(*dados(),max_nos=2,max_pares=5)
        self.assertEqual(n.entity_group_id.tolist(),[1,2])
        self.assertEqual(e.pair_id.tolist(),['a'])

    def test_focus_and_priority(self):
        n,e=selecionar_vista(*dados(),foco=1,max_nos=4,max_pares=2)
        self.assertIn(1,set(n.entity_group_id))
        self.assertEqual(e.pair_id.tolist(),['c','b'])
        n,e=selecionar_vista(*dados(),foco=4,max_nos=1,max_pares=2)
        self.assertEqual(n.entity_group_id.tolist(),[4]);self.assertTrue(e.empty)

    def test_absent_focus_is_not_imputed(self):
        n,e=selecionar_vista(*dados(),foco=55)
        self.assertTrue(n.empty and e.empty)

    def test_publication_cutoff_and_weight(self):
        pairs=pd.DataFrame({'pair_id':['p'],'weight':[2],'distinct_news_count':[1]})
        evidence=pd.DataFrame({'pair_id':['p','p'],'news_id':['n1','n2'],'publication_year':[1994,2000],'occurrence_count':[2,3]})
        news=pd.DataFrame({'news_id':['n1','n2']})
        conferir_evidencias(pairs,evidence,news,1994)
        with self.assertRaises(ValueError):conferir_evidencias(pairs,evidence,news,2000)
        with self.assertRaises(ValueError):conferir_evidencias(pairs,evidence,news.iloc[1:],1994)

    def test_reject_self_loop_and_duplicates(self):
        n,p=dados();p.loc[0,'target_id']=1
        with self.assertRaises(ValueError):selecionar_vista(n,p)
        n,p=dados()
        with self.assertRaises(ValueError):selecionar_vista(n,pd.concat([p,p.iloc[:1]]))

    def test_script_data_roundtrip(self):
        payload={'title':'</script><img src=x onerror=alert(1)> & “IA”'}
        encoded=json_seguro(payload)
        self.assertNotIn('<',encoded);self.assertEqual(json.loads(encoded),payload)
        with self.assertRaises(ValueError):json_seguro({'x':float('nan')})


if __name__=='__main__':unittest.main(verbosity=2)
