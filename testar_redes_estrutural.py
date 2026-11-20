"""Verificações exatas em grafos pequenos, sem conexão com Neo4j."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from contextlib import redirect_stdout
import io
import unittest
import pandas as pd
import redes_estrutural as r


class MetricsTests(unittest.TestCase):
    def test_triangle_and_tail_both_global_coefficients(self):
        f=r.calcular_referencia([1,2,3,4],[(1,2),(2,3),(1,3),(3,4)])
        f,c,d,s,h,m=r.resumir_metricas(f,4)
        self.assertEqual(m['triangles'],1);self.assertEqual(m['connected_triples'],5)
        self.assertAlmostEqual(m['mean_local_clustering_degree_ge_two'],7/9)
        self.assertAlmostEqual(m['mean_local_clustering_all_nodes'],7/12)
        self.assertAlmostEqual(m['transitivity'],3/5)
        self.assertAlmostEqual(m['density'],2/3)
        self.assertEqual(m['degree_sum'],8);self.assertEqual(m['connected_components'],1)
        self.assertEqual(int(h.nodes.sum()),4)
    def test_disconnected_graph_with_isolated_node(self):
        f=r.calcular_referencia([1,2,3,4,5,6],[(1,2),(2,3),(1,3),(4,5)])
        _,c,_,_,_,m=r.resumir_metricas(f,4)
        self.assertEqual(m['connected_components'],3);self.assertEqual(m['isolated_nodes'],1)
        self.assertEqual(m['largest_component_nodes'],3);self.assertEqual(m['triangles'],1)
        self.assertEqual(m['mean_local_clustering_degree_ge_two'],1)
        self.assertEqual(m['mean_local_clustering_all_nodes'],.5)
        self.assertEqual(int(c.nodes.sum()),6)
    def test_no_eligible_nodes_has_undefined_mean_and_transitivity(self):
        f=r.calcular_referencia([1,2],[(1,2)])
        *_,m=r.resumir_metricas(f,1)
        self.assertIsNone(m['mean_local_clustering_degree_ge_two']);self.assertIsNone(m['transitivity'])
        self.assertEqual(m['mean_local_clustering_all_nodes'],0)
    def test_complete_graph_four_vertices(self):
        pairs=[(a,b) for a in range(1,5) for b in range(a+1,5)]
        f=r.calcular_referencia(range(1,5),pairs);*_,m=r.resumir_metricas(f,6)
        self.assertEqual(m['triangles'],4);self.assertEqual(m['transitivity'],1)
        self.assertEqual(m['mean_local_clustering_degree_ge_two'],1)
    def test_component_ids_are_canonical_and_ccdf_is_correct(self):
        f=r.calcular_referencia([1,2,3,4,5],[(1,2),(2,3),(4,5)])
        f['component_id']=[900,900,900,300,300]
        out,c,d,*_=r.resumir_metricas(f,3)
        self.assertEqual(out.component_id.tolist(),[1,1,1,4,4])
        self.assertEqual(d.degree.tolist(),[1,2]);self.assertEqual(d.ccdf_ge_k.tolist(),[1,.2])
    def test_bad_topology_or_algorithm_output_is_blocked(self):
        for pairs in [[(1,1)],[(1,3)],[(1,2),(2,1)]]:
            with self.assertRaises(ValueError):r.calcular_referencia([1,2],pairs)
        f=r.calcular_referencia([1,2,3],[(1,2),(2,3)])
        f.loc[0,'triangle_count']=1
        with self.assertRaises(ValueError):r.resumir_metricas(f,2)
        f=r.calcular_referencia([1,2],[(1,2)]);f.loc[0,'degree']=2
        with self.assertRaises(ValueError):r.resumir_metricas(f,1)
    def test_all_figure_formats(self):
        f=r.calcular_referencia([1,2,3,4],[(1,2),(2,3),(1,3),(3,4)])
        f,c,d,s,h,m=r.resumir_metricas(f,4)
        with TemporaryDirectory() as tmp:
            cat=r.gerar_figuras(tmp,f,d,s,h,m)
            self.assertEqual(len(cat),9)
            self.assertEqual({Path(x).suffix for x in cat.file},{'.svg','.png','.pdf'})
            self.assertTrue(all((Path(tmp)/x).stat().st_size>0 for x in cat.file))
    def test_algorithms_are_executed_once_each(self):
        calls=[]
        def query(session,q,**params):
            calls.append(q)
            if '.estimate' in q:return [{'requiredMemory':'synthetic','bytesMin':1,'bytesMax':1,'nodeCount':2,'relationshipCount':2}]
            value=1 if 'degree.stream' in q else (0 if 'triangleCount.stream' in q else 500)
            return [{'entity_group_id':i,'value':value} for i in [1,2]]
        with patch.object(r,'_query',side_effect=query),redirect_stdout(io.StringIO()):
            f,estimates,timings=r.executar_algoritmos(None,'synthetic')
        self.assertEqual(len(calls),6);self.assertEqual(len(f),2)
        self.assertEqual(len(estimates),3);self.assertEqual(len(timings),3)

if __name__=='__main__':unittest.main()
