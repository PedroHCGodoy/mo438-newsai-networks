"""Verificações de empates, persistência e aquisição de vizinhos."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pandas as pd
import temporal_protagonismo as r


class ProtagonismoTests(unittest.TestCase):
    def frame(self):
        return pd.DataFrame({'entity_group_id':[1,2,3,4],
            'neighbor_degree':[3,2,2,1],'weighted_strength':[5,3,3,1],
            'distinct_news_count':[3,2,2,1],'relation_news_count':[2,1,1,1],
            'mention_count':[8,3,3,1],'ent_label':['LOCAL']*4})

    def test_rank_ties_and_exact_selection_are_separate(self):
        f=r.atribuir_rankings(self.frame());f['cutoff_year']=1994
        self.assertEqual(f.degree_rank.tolist(),[1,2,2,4])
        exact,inclusive=r.selecionar_top(f,2)
        self.assertEqual(exact.entity_group_id.tolist(),[1,2])
        self.assertEqual(set(inclusive.entity_group_id),{1,2,3})
        self.assertAlmostEqual(f.degree_share.sum(),1)

    def test_retention_and_jaccard_use_distinct_denominators(self):
        top=pd.DataFrame({'cutoff_year':[1994,1994,1995,1995], 'entity_group_id':[1,2,2,3]})
        row=r.persistencia(top,[1994,1995],'EXACT_K').iloc[0]
        self.assertEqual(row.retained,1);self.assertAlmostEqual(row.retention_share,.5)
        self.assertAlmostEqual(row.jaccard,1/3)

    def test_new_neighbors_match_pairs_and_reinforcement_is_separate(self):
        f=pd.DataFrame({'entity_group_id':[1,2,3],'degree':[2,2,2]})
        old=pd.DataFrame({'entity_group_id':[1,2],'degree':[1,1]})
        events=pd.DataFrame({'source_id':[1,2,1],'target_id':[3,3,2],
            'event_type':['NEW_PAIR','NEW_PAIR','REINFORCED_PAIR'],'added_occurrences':[1,1,7]})
        out=r.conferir_ganhos(f,old,events)
        self.assertEqual(out.new_neighbors.tolist(),[1,1,2])
        self.assertEqual(out.reinforcement_occurrences.tolist(),[7,7,0])
        self.assertEqual(out.new_neighbors_to_preexisting.tolist(),[0,0,2])

    def test_disagreement_between_degree_and_events_rejected(self):
        f=pd.DataFrame({'entity_group_id':[1,2],'degree':[2,1]})
        old=pd.DataFrame({'entity_group_id':[1,2],'degree':[1,1]})
        events=pd.DataFrame(columns=['source_id','target_id','event_type','added_occurrences'])
        with self.assertRaises(ValueError):r.conferir_ganhos(f,old,events)

    def test_initial_stock_is_marked(self):
        f=pd.DataFrame({'entity_group_id':[1,2],'degree':[1,1]})
        out=r.conferir_ganhos(f,None,pd.DataFrame(),baseline=True)
        self.assertTrue(out.is_baseline_stock.all())
        self.assertTrue(out.reinforcement_occurrences.isna().all())

    def test_dry_run_does_not_write_or_connect(self):
        with TemporaryDirectory() as td,\
            patch.object(r,'carregar_redes_temporais',return_value=(Path(td),{'snapshot_sha256':'t','network_snapshot_sha256':'n'})),\
            patch.object(r,'carregar_rede',return_value=(Path(td),{'snapshot_sha256':'n'})),\
            patch.object(r,'carregar_estrutura',return_value=(Path(td),{'snapshot_sha256':'e'})),\
            patch.object(r,'carregar_conexoes',return_value=(Path(td),{'snapshot_sha256':'c'})):
            result=r.analisar_protagonismo_temporal(td)
            self.assertEqual(result['neo4j_connections'],0)
            self.assertEqual(list(Path(td).iterdir()),[])


if __name__=='__main__':unittest.main(verbosity=2)
