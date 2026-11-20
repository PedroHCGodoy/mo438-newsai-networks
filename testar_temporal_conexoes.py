"""Testes de novidade, reforço, agregação temporal e suporte documental."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pandas as pd
import temporal_conexoes as r


def pares(rows):
    return pd.DataFrame(rows, columns=['pair_id', 'source_id', 'target_id', 'weight', 'distinct_news_count'])


class ConexoesTests(unittest.TestCase):
    def setUp(self):
        self.prev=pares([['a',1,2,2,1],['b',2,3,1,1]])
        self.curr=pares([['a',1,2,4,2],['b',2,3,1,1],['c',1,3,1,1],['d',1,4,1,1],['e',4,5,2,1]])

    def run_transition(self):
        return r.classificar_transicao({1,2,3},self.prev,{1,2,3,4,5},self.curr,1994,1995)

    def test_three_categories_and_reinforcement_are_disjoint(self):
        events,s=self.run_transition()
        self.assertEqual(s['new_pairs'],3)
        self.assertEqual([s[c] for c in ['new_new','old_new','old_old']],[1,1,1])
        self.assertEqual(s['reinforced_pairs'],1)
        self.assertEqual(s['unchanged_previous_pairs'],1)
        self.assertEqual(s['occurrences_existing_pairs'],2)
        self.assertEqual(s['occurrences_new_pairs'],4)
        self.assertEqual(events[events.pair_id.eq('a')].event_type.iloc[0],'REINFORCED_PAIR')

    def test_no_new_pairs_has_undefined_shares(self):
        e,s=r.classificar_transicao({1,2,3},self.prev,{1,2,3},self.prev,1994,1995)
        self.assertTrue(e.empty);self.assertEqual(s['new_pairs'],0)
        self.assertIsNone(s['share_new_new'])

    def test_disappearance_or_weight_decline_rejected(self):
        with self.assertRaises(ValueError):r.classificar_transicao({1,2,3},self.prev,{1,2,3},self.prev.iloc[:1],1994,1995)
        self.curr.loc[0,'weight']=1
        with self.assertRaises(ValueError):self.run_transition()

    def test_pair_id_cannot_change_endpoints(self):
        self.curr.loc[0,['source_id','target_id']]=[2,4]
        with self.assertRaises(ValueError):self.run_transition()

    def test_coarse_categories_cannot_be_summed_from_annual_categories(self):
        p0=pares([['a',1,2,1,1]])
        p1=pares([['a',1,2,1,1],['b',1,3,1,1]])
        p2=pares([['a',1,2,1,1],['b',1,3,1,1],['c',2,3,1,1]])
        _,annual=r.classificar_transicao({1,2,3},p1,{1,2,3},p2,1995,1996)
        _,coarse=r.classificar_transicao({1,2},p0,{1,2,3},p2,1994,1996)
        self.assertEqual(annual['old_old'],1)
        self.assertEqual(coarse['old_old'],0)
        self.assertEqual(coarse['old_new'],2)

    def test_document_support_reconstructs_each_pair_increment(self):
        events,_=self.run_transition()
        support=pd.DataFrame({'pair_id':['a','c','d','e'],'news_id':['n1']*4,
            'publication_year':[1995]*4,'occurrence_count':[2,1,1,2]})
        r.conferir_suporte(events,support,1994,1995)
        support.loc[0,'occurrence_count']=3
        with self.assertRaises(ValueError):r.conferir_suporte(events,support,1994,1995)

    def test_zero_denominator_is_not_reported_as_measured_zero_ratio(self):
        _,s=r.classificar_transicao({1,2,3},self.prev,{1,2,3},self.prev,1994,1995)
        coverage=pd.DataFrame({'publication_year':[1995],'corpus_news':[3],
            're_completed_strict':[0],'re_partial':[0],'support_news':[0],'retained_occurrences':[0]})
        out=r.adicionar_cobertura([s],coverage)
        self.assertFalse(out.network_evidence_available.iloc[0])
        self.assertTrue(pd.isna(out.new_new_per_support_news.iloc[0]))

    def test_dry_run_opens_no_network_and_writes_no_files(self):
        with TemporaryDirectory() as td,\
            patch.object(r,'carregar_redes_temporais',return_value=(Path(td),{'snapshot_sha256':'t','network_snapshot_sha256':'n'})),\
            patch.object(r,'carregar_rede',return_value=(Path(td),{'snapshot_sha256':'n'})),\
            patch.object(r,'carregar_estrutura',return_value=(Path(td),{})):
            out=r.analisar_formacao_conexoes(td)
            self.assertEqual(out['annual_transitions'],31)
            self.assertEqual(out['neo4j_connections'],0)
            self.assertEqual(list(Path(td).iterdir()),[])


if __name__=='__main__':unittest.main(verbosity=2)
