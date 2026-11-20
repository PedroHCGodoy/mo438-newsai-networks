"""Testes sintéticos de isolamento, retomada e validação da carga."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from contextlib import redirect_stdout
import io
import unittest
import neo4j_carga as n


class Row(dict):
    def data(self):return dict(self)
class Result(list):
    def consume(self):return None
class Driver:
    def __init__(self):
        self.nodes={};self.edges={};self.meta=None;self.constraints={};self.queries=[];self.fail_edge=False
        self.legacy_nodes={1:{'name':'legacy','entity_group_id':1}}
        self.legacy_edges=[{'weight':7}]
    def verify_connectivity(self):pass
    def session(self,**kw):return self
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def close(self):pass
    def execute_read(self,fn):return fn(self)
    def execute_write(self,fn):return fn(self)
    def run(self,query,**p):
        self.queries.append(query)
        if query in [n.NODE_CONSTRAINT,n.EDGE_CONSTRAINT,n.RUN_CONSTRAINT]:
            for name,label,props in [('newsai_entity_graph_id_v1',n.NODE_LABEL,['graph_tag','entity_group_id']),
                ('newsai_relation_graph_id_v1',n.RELATION_TYPE,['graph_tag','edge_id']),
                ('newsai_network_tag_v1','NewsAINetwork',['graph_tag'])]:
                self.constraints[name]={'name':name,'type':'UNIQUENESS','labelsOrTypes':[label],'properties':props}
            rows=[]
        elif query==n.CHECK_CONSTRAINTS:rows=list(self.constraints.values())
        elif query==n.GET_RUN:rows=[{'properties':self.meta.copy()}] if self.meta else []
        elif query==n.TARGET_COUNTS:rows=[{'nodes':len(self.nodes),'edges':len(self.edges)}]
        elif query==n.INITIALIZE:
            if self.meta is None:self.meta={'graph_tag':p['tag'],'snapshot_sha256':p['snapshot'],'payload_sha256':p['payload'],'state':'LOADING'}
            rows=[{'properties':self.meta.copy()}]
        elif query==n.NODES:
            for props in p['rows']:self.nodes[props['entity_group_id']]=props.copy()
            rows=[{'processed':len(p['rows'])}]
        elif query==n.EDGES:
            if self.fail_edge:raise RuntimeError('interrupção simulada')
            for props in p['rows']:self.edges[props['edge_id']]=props.copy()
            rows=[{'processed':len(p['rows'])}]
        elif query==n.READ_NODES:rows=[{'properties':x.copy()} for x in self.nodes.values()]
        elif query==n.READ_EDGES:rows=[{'properties':x.copy(),'source_tag':x['graph_tag'],
            'target_tag':x['graph_tag'],'source_id':x['source_group_id'],'target_id':x['target_group_id'],
            'source_labels':[n.NODE_LABEL],'target_labels':[n.NODE_LABEL]} for x in self.edges.values()]
        elif query==n.FINISH:self.meta['state']='COMPLETE';rows=[{'state':'COMPLETE'}]
        else:raise AssertionError('Consulta não reconhecida')
        return Result([Row(x) for x in rows])


def payload():
    tag='newsai_test'
    return {'tag':tag,'snapshot':'a'*64,'nodes':[{'graph_tag':tag,'entity_group_id':i,'name':str(i)} for i in [1,2]],
        'edges':[{'graph_tag':tag,'edge_id':'e','source_group_id':1,'target_group_id':2,
            'relation_label':'vinculo_inst','weight':3,'distance':1/3}]}


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.quiet=redirect_stdout(io.StringIO());self.quiet.__enter__();self.addCleanup(self.quiet.__exit__,None,None,None)
    def test_load_idempotence_and_legacy_preservation(self):
        d=Driver();before=deepcopy((d.legacy_nodes,d.legacy_edges))
        first=n.importar_driver(d,'neo4j',payload(),batch_size=1)
        self.assertTrue(first['all_properties_verified']);self.assertEqual(first['weight_sum'],3)
        self.assertEqual(d.meta['state'],'COMPLETE')
        d.nodes[1]['pagerank']=0.5
        second=n.importar_driver(d,'neo4j',payload())
        self.assertTrue(second['reused_completed_load']);self.assertEqual(second['batches_written'],0)
        self.assertEqual(d.nodes[1]['pagerank'],0.5)
        self.assertEqual(before,(d.legacy_nodes,d.legacy_edges))
        for q in d.queries:
            self.assertNotIn('DELETE',q.upper());self.assertNotIn('DROP',q.upper())
            self.assertNotIn('MERGE (n:Entity ',q)
    def test_resume_after_interruption(self):
        d=Driver();d.fail_edge=True
        with self.assertRaises(RuntimeError):n.importar_driver(d,'neo4j',payload(),batch_size=1)
        self.assertEqual(d.meta['state'],'LOADING');self.assertEqual(len(d.nodes),2)
        d.fail_edge=False;r=n.importar_driver(d,'neo4j',payload(),batch_size=1)
        self.assertEqual(r['edges'],1);self.assertEqual(len(d.nodes),2);self.assertEqual(len(d.edges),1)
    def test_unmanaged_destination_blocks(self):
        d=Driver();d.nodes[1]={'name':'unexpected'}
        with self.assertRaises(ValueError):n.importar_driver(d,'neo4j',payload())
        self.assertFalse(d.constraints)
    def test_different_payload_blocks(self):
        d=Driver();n.importar_driver(d,'neo4j',payload())
        p=payload();p['nodes'][0]['name']='different'
        with self.assertRaises(ValueError):n.importar_driver(d,'neo4j',p)
        self.assertEqual(d.nodes[1]['name'],'1')
    def test_tampered_imported_property_blocks(self):
        d=Driver();n.importar_driver(d,'neo4j',payload());d.edges['e']['weight']=4
        with self.assertRaises(ValueError):n.importar_driver(d,'neo4j',payload())
    def test_dry_run_never_connects(self):
        with TemporaryDirectory() as tmp,patch.object(n,'carregar_rede',return_value=(Path(tmp),{'snapshot_sha256':'a'*64})),patch.object(n,'preparar_carga',return_value=payload()):
            result=n.carregar_rede_neo4j(tmp,driver_factory=lambda *a,**k:self.fail('não deve conectar'))
            self.assertEqual(result['database_writes'],0);self.assertEqual(result['neo4j_connections'],0)
    def test_pin_blocks(self):
        with TemporaryDirectory() as tmp,patch.object(n,'carregar_rede',return_value=(Path(tmp),{'snapshot_sha256':'a'*64})):
            with self.assertRaises(ValueError):n.carregar_rede_neo4j(tmp,assinatura_rede_esperada='wrong')

if __name__=='__main__':unittest.main()
