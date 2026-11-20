"""Verificações do conjunto de risco, zeros, referências e degenerescência."""
import unittest
import numpy as np
import pandas as pd
from temporal_vantagem import (ANOS, preparar_painel, rho_descritivo,
                              resumir_faixas, estudar_casos)


def exemplo():
    rows, coverage = [], []
    for year in ANOS:
        ids = [1, 2] if year == 1994 else [1, 2, 3]
        degrees = [1, 1] if year == 1994 else [2, 1, 1]
        for entity, degree in zip(ids, degrees):
            baseline = year == 1994
            previous = 0 if baseline else (1 if year == 1995 and entity != 3 else (0 if year == 1995 else degree))
            gain = degree-previous
            rows.append({'entity_group_id': entity, 'entity_group_name': str(entity), 'ent_label': 'LOCAL',
                'cutoff_year': year, 'degree': degree, 'previous_degree': previous, 'new_neighbors': gain,
                'is_baseline_stock': baseline, 'new_neighbors_to_new': None if baseline else int(year == 1995 and entity == 1),
                'new_neighbors_to_preexisting': None if baseline else int(year == 1995 and entity == 3),
                'reinforcement_occurrences': None if baseline else 0, 'annual_mention_news': int(gain > 0),
                'annual_relation_news': int(gain > 0)})
        coverage.append({'publication_year': year, 'cumulative_nodes': len(ids), 'cumulative_undirected_pairs': sum(degrees)//2,
            'strict_completion_share': 0. if year == 2021 else 1., 'support_news': 1 if year == 1995 else 0,
            'no_completed_re_in_year': year == 2021, 'corpus_news': 1, 're_completed_strict': int(year != 2021), 're_partial': 0})
    return pd.DataFrame(rows), pd.DataFrame(coverage)


class AnaliseTemporalTests(unittest.TestCase):
    def test_zeros_baseline_and_entrants(self):
        d,c=exemplo(); p,a=preparar_painel(d,c)
        self.assertEqual(len(p),92); self.assertEqual(len(a),31)
        g=p.loc[p.cutoff_year.eq(1995)]
        self.assertEqual(set(g.entity_group_id),{1,2})
        self.assertEqual(g.loc[g.entity_group_id.eq(2),'new_neighbors'].iloc[0],0)
        self.assertTrue(p.cutoff_year.ge(1995).all())
        self.assertEqual(a.loc[a.cutoff_year.eq(1995),'all_node_gains'].iloc[0],2)

    def test_references_and_no_gain_year(self):
        d,c=exemplo(); p,_=preparar_painel(d,c)
        g=p.loc[p.cutoff_year.eq(1995)]
        np.testing.assert_allclose(g.uniform_reference_gain,[.5,.5])
        np.testing.assert_allclose(g.degree_reference_gain,[.5,.5])
        b=resumir_faixas(p)
        self.assertAlmostEqual(b.loc[b.cutoff_year.eq(1995),'observed_gain_share'].sum(),1)
        self.assertTrue(b.loc[b.cutoff_year.eq(2021),'normalized_gain_mean'].isna().all())

    def test_rank_ties_and_constant(self):
        self.assertAlmostEqual(rho_descritivo([1,1,2,3],[0,0,1,2]),1)
        self.assertIsNone(rho_descritivo([1,2,3],[0,0,0]))
        self.assertIsNone(rho_descritivo([1,1,1],[0,1,2]))
        with self.assertRaises(ValueError):rho_descritivo([1,2],[0,np.nan])

    def test_reject_changed_previous_and_gain_components(self):
        d,c=exemplo(); d.loc[(d.cutoff_year==1995)&(d.entity_group_id==1),'previous_degree']=0
        with self.assertRaises(ValueError):preparar_painel(d,c)
        d,c=exemplo(); d.loc[(d.cutoff_year==1995)&(d.entity_group_id==1),'new_neighbors_to_new']=0
        with self.assertRaises(ValueError):preparar_painel(d,c)

    def test_duplicate_and_disappearing_nodes(self):
        d,c=exemplo()
        with self.assertRaises(ValueError):preparar_painel(pd.concat([d,d.iloc[:1]]),c)
        d,c=exemplo(); d=d.loc[~(d.cutoff_year.eq(1996)&d.entity_group_id.eq(2))]
        with self.assertRaises(ValueError):preparar_painel(d,c)

    def test_case_is_separate_and_comparator_includes_it(self):
        d,c=exemplo(); p,_=preparar_painel(d,c); cases=estudar_casos(p,[1,2])
        self.assertEqual(set(cases.entity_group_id),{1,2})
        self.assertTrue(cases.comparison_nodes.ge(1).all())
        with self.assertRaises(ValueError):estudar_casos(p,[999])


if __name__=='__main__':unittest.main(verbosity=2)
