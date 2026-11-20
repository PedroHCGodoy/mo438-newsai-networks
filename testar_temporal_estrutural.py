"""Verificações das razões temporais e do ciclo de vida das projeções."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock
import numpy as np
import pandas as pd
import temporal_estrutural as r


class EstruturaTemporalTests(unittest.TestCase):
    def data(self):
        n=len(r.ANOS)
        t=pd.DataFrame({'cutoff_year':r.ANOS,'nodes':np.arange(n)+2,
            'simple_undirected_edges':np.arange(n)+1,'typed_directed_edges':np.arange(n)+1,
            'weight_sum':np.arange(n)+1,'support_news':np.arange(n)+1,
            're_completed_strict':np.arange(n)+1,'re_partial':0,
            'largest_component_share':.5,'mean_degree':1.,'transitivity':0.})
        c=pd.DataFrame({'publication_year':r.ANOS,'corpus_news':2,'re_completed_strict':1,
            're_partial':0,'support_news':1,'retained_occurrences':1,'strict_completion_share':.5})
        return t,c

    def test_denominators_are_explicit_and_increment_sum_matches(self):
        t,c=self.data();out=r.calcular_crescimento(t,c)
        self.assertEqual(out.new_nodes.sum(),t.nodes.iloc[-1])
        self.assertEqual(out.new_nodes_per_corpus_news.iloc[1],.5)
        self.assertEqual(out.new_nodes_per_support_news.iloc[1],1.)
        self.assertTrue(pd.isna(out.delta_gcc_percentage_points.iloc[0]))

    def test_missing_support_is_not_zero_per_support_ratio(self):
        t,c=self.data();c.loc[1,['support_news','retained_occurrences','re_completed_strict']]=0
        t.loc[1,'weight_sum']=1;t.loc[2:,'weight_sum']-=1
        for col in ['nodes','simple_undirected_edges','typed_directed_edges']:
            t.loc[1:,col]-=1
        out=r.calcular_crescimento(t,c)
        self.assertFalse(out.network_evidence_available_in_year.iloc[1])
        self.assertTrue(pd.isna(out.new_nodes_per_support_news.iloc[1]))

    def test_wrong_occurrence_increment_rejected(self):
        t,c=self.data();c.loc[4,'retained_occurrences']=8
        with self.assertRaises(ValueError):r.calcular_crescimento(t,c)

    def test_incomplete_series_rejected(self):
        t,c=self.data()
        with self.assertRaises(ValueError):r.calcular_crescimento(t.iloc[:-1],c)

    def test_decreasing_topology_rejected(self):
        t,c=self.data();t.loc[3,'nodes']=1
        with self.assertRaises(ValueError):r.calcular_crescimento(t,c)

    def test_projection_is_read_only_and_sequential(self):
        self.assertIn('readConcurrency:1',r.PROJETAR)
        self.assertIn('weight:1.0',r.PROJETAR)
        self.assertNotIn('CREATE ',r.PROJETAR)

    def test_projection_released_when_algorithm_fails(self):
        session=MagicMock();nodes=pd.DataFrame({'entity_group_id':[1,2]})
        pairs=pd.DataFrame({'source_id':[1],'target_id':[2],'weight':[1]})
        edges=pairs.assign(edge_id='x')
        with patch.object(r,'verificar_projecao',return_value={}),\
             patch.object(r,'valores_esperados',return_value={}),\
             patch.object(r,'executar_algoritmos',side_effect=RuntimeError('falha controlada')),\
             patch.object(r,'query',return_value=[{'exists':True}]):
            with self.assertRaises(RuntimeError):r.calcular_corte(session,'owned_graph','neo4j','tag',nodes,pairs,edges)
        drop=[c for c in session.run.call_args_list if 'gds.graph.drop' in c.args[0]]
        self.assertEqual(len(drop),1);self.assertEqual(drop[0].kwargs['name'],'owned_graph')

    def test_dry_run_no_files_no_connection(self):
        with TemporaryDirectory() as td,\
             patch.object(r,'carregar_redes_temporais',return_value=(Path(td),{'network_snapshot_sha256':'x','snapshot_sha256':'y'})),\
             patch.object(r,'carregar_rede',return_value=(Path(td),{'snapshot_sha256':'x'})),\
             patch.object(r,'_configuration',side_effect=AssertionError('Não conectar')):
            out=r.analisar_estrutura_temporal(td)
            self.assertEqual(out['neo4j_connections'],0)
            self.assertEqual(list(Path(td).iterdir()),[])


if __name__=='__main__':unittest.main(verbosity=2)
