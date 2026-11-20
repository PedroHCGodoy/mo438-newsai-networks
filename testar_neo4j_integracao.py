"""Verificações sintéticas sem conexão real com Neo4j."""
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import io
import json
import unittest
import zipfile
import neo4j_integracao as n


class Row(dict):
    def data(self):return dict(self)


class Driver:
    def __init__(self,fail=None,target=False,missing=False):
        self.fail=fail;self.target=target;self.missing=missing;self.closed=False;self.executed=[]
    def verify_connectivity(self):
        if self.fail:raise self.fail
    def session(self,**kwargs):
        assert kwargs['default_access_mode']=='READ'
        return self
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def close(self):self.closed=True
    def execute_read(self,fn):return fn(self)
    def execute_write(self,*args):raise AssertionError('Escrita indevida')
    def run(self,query,**params):
        self.executed.append(query)
        name=next(key for key,value in n.QUERIES.items() if value==query)
        if self.missing and name.startswith('gds_'):raise RuntimeError('GDS indisponível')
        rows={
            'components':[dict(name='Neo4j Kernel',versions=['5.26'],edition='community')],
            'database_counts':[dict(nodes=123)],'relationship_count':[dict(relationships=456)],
            'existing_networks':[dict(graph_tag='legacy',labels=['Entity'],nodes=123)],
            'constraints':[dict(name='old_unique',type='UNIQUENESS',entityType='NODE',labelsOrTypes=['Entity'],properties=['name'])],
            'indexes':[],
            'target_nodes':[dict(labels=['Entity'],nodes=2)] if self.target else [],
            'target_relationships':[],
            'gds_version':[dict(version='2.13')],
            'gds_procedures':[dict(name=x) for x in ['gds.pageRank.stream','gds.wcc.stream','gds.louvain.stream','gds.leiden.stream']],
            'gds_functions':[dict(name='gds.graph.project')],
            'gds_graphs':[dict(graphName='old_projection',nodeCount=123,relationshipCount=456)],
        }[name]
        return [Row(x) for x in rows]


class EnvironmentTests(unittest.TestCase):
    def test_existing_data_are_only_inventoried(self):
        d=Driver();result=n.inspecionar_driver(d,'neo4j','new_snapshot')
        self.assertTrue(result['inspection_complete'])
        self.assertEqual(result['database_writes'],0)
        self.assertEqual(result['queries']['existing_networks']['rows'][0]['graph_tag'],'legacy')
        self.assertEqual(set(d.executed),set(n.QUERIES.values()))
        self.assertTrue(result['gds_capabilities']['projection'])
        for query in d.executed:
            self.assertNotIn('DELETE ',query.upper());self.assertNotIn('MERGE ',query.upper())
            self.assertNotIn('CREATE ',query.upper());self.assertNotIn('SET ',query.upper())
    def test_target_collision_is_detected(self):
        result=n.inspecionar_driver(Driver(target=True),'neo4j','new_snapshot')
        self.assertTrue(result['target_has_existing_data']);self.assertFalse(result['load_executed'])
    def test_missing_gds_is_reported(self):
        result=n.inspecionar_driver(Driver(missing=True),'neo4j','new_snapshot')
        self.assertTrue(result['inspection_complete']);self.assertFalse(result['gds_capabilities']['version_query_ok'])
        self.assertEqual(result['queries']['gds_graphs']['status'],'UNAVAILABLE')
    def test_credentials_never_enter_report_and_source_stays_unchanged(self):
        with TemporaryDirectory() as tmp,redirect_stdout(io.StringIO()):
            root=Path(tmp)
            env=root/'.env';text='NEO4J_URI=bolt://localhost:7687\nNEO4J_USER=neo4j\nNEO4J_PASSWORD=secret-test-only\nGEMINI_API_KEY=unrelated-secret\n'
            env.write_text(text);before=env.read_bytes()
            d=Driver()
            with patch.object(n,'carregar_rede',return_value=(root,{'snapshot_sha256':'a'*64,'summary':{'nodes':10}})):
                result=n.verificar_ambiente_neo4j(root,driver_factory=lambda *a,**kw:d)
            self.assertTrue(d.closed);self.assertEqual(before,env.read_bytes())
            with zipfile.ZipFile(result['package']) as z:
                body=z.read('conferencia_neo4j.json').decode()
                self.assertNotIn('secret-test-only',body);self.assertNotIn('unrelated-secret',body)
    def test_failed_connection_closes_driver_and_hides_message(self):
        with TemporaryDirectory() as tmp:
            d=Driver(fail=RuntimeError('secret-password-in-exception'))
            with patch.object(n,'carregar_rede',return_value=(Path(tmp),{'snapshot_sha256':'a'*64})),patch.object(n,'_configuration',return_value=('bolt://localhost','u','p','neo4j')):
                with self.assertRaises(RuntimeError) as exc:
                    n.verificar_ambiente_neo4j(tmp,driver_factory=lambda *a,**kw:d)
                self.assertNotIn('secret-password',str(exc.exception));self.assertTrue(d.closed)
    def test_wrong_snapshot_blocks_before_connection(self):
        with TemporaryDirectory() as tmp,patch.object(n,'carregar_rede',return_value=(Path(tmp),{'snapshot_sha256':'a'*64})):
            with self.assertRaises(ValueError):n.verificar_ambiente_neo4j(tmp,assinatura_rede_esperada='b'*64)
    def test_missing_credentials_or_embedded_credentials_blocked(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'.env';p.write_text('NEO4J_URI=bolt://localhost\n')
            with self.assertRaises(ValueError):n._configuration(tmp)
            p.write_text('NEO4J_URI=bolt://u:p@localhost\nNEO4J_USER=u\nNEO4J_PASSWORD=p\n')
            with self.assertRaises(ValueError):n._configuration(tmp)


if __name__=='__main__':unittest.main()
