"""Testes locais de projeções, suporte documental e validação do catálogo."""
from contextlib import redirect_stdout
from unittest.mock import patch
from collections import defaultdict
import io
import unittest
import pandas as pd
import redes_projecoes as r


def fixture():
    edges=pd.DataFrame([dict(edge_id='e1',source_id='1',target_id='2',weight='2'),
        dict(edge_id='e2',source_id='1',target_id='2',weight='3'),
        dict(edge_id='e3',source_id='2',target_id='1',weight='4')])
    support=pd.DataFrame([dict(edge_id='e1',news_id='n1'),dict(edge_id='e2',news_id='n1'),dict(edge_id='e3',news_id='n2')])
    return edges,support


class Row(dict):
    def data(self):return dict(self)
class Result(list):
    def consume(self):return None
class Driver:
    def __init__(self,payload,meta,edges,pairs):
        self.payload=payload;self.meta=meta;self.edges=edges;self.pairs=pairs
        self.graphs={};self.queries=[];self.run_state='COMPLETE';self.wrong_tag=False;self.bad_weight=False
    def verify_connectivity(self):pass
    def session(self,**kwargs):return self
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def execute_read(self,fn):return fn(self)
    def run(self,q,**p):
        self.queries.append(q)
        if q==r.GET_RUN:
            rows=[{'properties':{'state':self.run_state,'snapshot_sha256':self.payload['snapshot'],
                'payload_sha256':r.json_sha(self.payload)}}]
        elif q==r.EXISTS:rows=[{'exists':p['name'] in self.graphs}]
        elif q==r.LIST_GRAPH:
            values=self.graphs[p['name']]
            rows=[{'graphName':p['name'],'nodeCount':2,'relationshipCount':sum(map(len,values.values())),
                'database':'neo4j','memoryUsage':'synthetic'}]
        elif q==r.STREAM_NODES:
            rows=[{'entity_group_id':i,'graph_tag':'wrong' if self.wrong_tag else self.payload['tag']} for i in [1,2]]
        elif q==r.STREAM_PROPERTY:
            rows=[]
            for (a,b),vals in self.graphs[p['name']].items():
                for value in vals:
                    v=1/value if p['property']=='distance' else value
                    rows.append({'source_id':a,'target_id':b,'value':v+1 if self.bad_weight else v})
        else:
            kind=next(k for k in r.KINDS if q==r.query_projecao(k))
            self.graphs[p['name']]=r.valores_esperados(kind,self.edges,self.pairs);rows=[]
        return Result([Row(x) for x in rows])


class ProjectionTests(unittest.TestCase):
    def test_pair_weights_and_union_of_news(self):
        frames,edges=r.preparar_tabelas(*fixture());p=frames['ponderada_nao_dirigida.csv.gz']
        self.assertEqual(len(p),1);self.assertEqual(p.iloc[0].weight,9)
        self.assertEqual(p.iloc[0].distinct_news_count,2);self.assertEqual(p.iloc[0].typed_edge_count,3)
        self.assertEqual(frames['simples_nao_dirigida.csv.gz'].iloc[0].weight,1)
        self.assertEqual(len(frames['vinculos_arestas_projecoes.csv.gz']),3)
    def test_direction_and_parallel_edges_preserved(self):
        frames,e=r.preparar_tabelas(*fixture());pairs=frames['ponderada_nao_dirigida.csv.gz']
        d=r.valores_esperados('directed',e,pairs)
        self.assertEqual(d[(1,2)],[2,3]);self.assertEqual(d[(2,1)],[4])
        u=r.valores_esperados('community',e,pairs)
        self.assertEqual(u[(1,2)],[9]);self.assertEqual(u[(2,1)],[9])
    def test_stream_checks_topology_multiplicity_and_values(self):
        expected={(1,2):[2,3]}
        good=[dict(source_id=1,target_id=2,value=x) for x in [3,2]]
        self.assertEqual(r.conferir_valores(good,expected),5)
        for rows in [good[:1],[dict(source_id=2,target_id=1,value=5)],
            [dict(source_id=1,target_id=2,value=x) for x in [2,4]]]:
            with self.assertRaises(ValueError):r.conferir_valores(rows,expected)
    def test_invalid_inputs_blocked(self):
        for mode in ['loop','zero','duplicate']:
            e,s=fixture()
            if mode=='loop':e.loc[0,'target_id']='1'
            if mode=='zero':e.loc[0,'weight']='0'
            if mode=='duplicate':e.loc[0,'edge_id']='e2'
            with self.assertRaises(ValueError):r.preparar_tabelas(e,s)
    def setup_driver(self):
        frames,e=r.preparar_tabelas(*fixture());pairs=frames['ponderada_nao_dirigida.csv.gz']
        payload={'tag':'newsai_test','snapshot':'a'*64,'nodes':[{'entity_group_id':1},{'entity_group_id':2}],'edges':[]}
        meta={'graph_names':{k:'test_'+k for k in r.KINDS}}
        return Driver(payload,meta,e,pairs)
    def execute(self,d):
        with redirect_stdout(io.StringIO()),patch.object(r,'validar_banco',return_value={}):
            return r.executar_projecoes(d,'neo4j',d.payload,d.meta,d.edges,d.pairs)
    def test_create_reuse_and_no_automatic_deletion(self):
        d=self.setup_driver();first=self.execute(d);second=self.execute(d)
        self.assertEqual(len(d.graphs),3)
        self.assertTrue(all(x['reused_existing_projection'] for x in second.values()))
        self.assertEqual(first['structural']['relationshipCount'],2)
        self.assertEqual(first['community']['weight_sum'],18)
        for q in d.queries:
            self.assertNotIn('gds.graph.drop',q);self.assertNotIn('DELETE ',q.upper());self.assertNotIn('SET ',q.upper())
    def test_incomplete_load_blocks(self):
        d=self.setup_driver();d.run_state='LOADING'
        with self.assertRaises(ValueError):self.execute(d)
        self.assertFalse(d.graphs)
    def test_existing_graph_from_wrong_edition_blocks(self):
        d=self.setup_driver();self.execute(d);d.wrong_tag=True
        with self.assertRaises(ValueError):self.execute(d)
    def test_existing_graph_with_changed_values_blocks(self):
        d=self.setup_driver();self.execute(d);d.bad_weight=True
        with self.assertRaises(ValueError):self.execute(d)

if __name__=='__main__':unittest.main()
