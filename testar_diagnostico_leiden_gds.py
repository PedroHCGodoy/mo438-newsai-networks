"""Fluxos de falha, recuperação e preservação sem conexão com Neo4j."""
from pathlib import Path
import tempfile,json,unittest,zipfile
from unittest.mock import patch
import pandas as pd
import diagnostico_leiden_gds as diagnostic
from revisao_pendencias import sha

class Record:
    def __init__(self,row):self.row=row
    def data(self):return self.row
class Result(list):
    def __init__(self,rows=()):super().__init__(Record(x) for x in rows)
    def consume(self):return None
class FakeSession:
    def __init__(self,driver):self.driver=driver
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def execute_read(self,fn):return fn(self)
    def run(self,statement,**params):
        if statement=='RETURN gds.version() AS version':return Result([{'version':'2026.09.0'}])
        if 'gds.graph.exists' in statement:return Result([{'exists':self.driver.exists}])
        if statement=='PROJECT_QUERY':self.driver.created.append(params['name']);return Result()
        if 'gds.graph.drop' in statement:self.driver.dropped.append(params['name']);return Result()
        raise AssertionError('Unexpected query')
class FakeDriver:
    def __init__(self,exists=True):self.exists=exists;self.created=[];self.dropped=[];self.closed=False
    def verify_connectivity(self):pass
    def session(self,**kwargs):return FakeSession(self)
    def close(self):self.closed=True

class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'PROJECT';self.root.mkdir()
        self.comm=self.root/'resultados/comunidades/instancias/abc';self.comm.mkdir(parents=True)
        self.proj=self.root/'dados/processados/redes/projecoes/def';self.proj.mkdir(parents=True)
        data=pd.DataFrame({'run_id':['leiden_seed_44']*4,'entity_group_id':[10,11,12,13],
            'ent_label':['LOCAL']*4,'component_id':[10]*4,'raw_community_id':[5]*4,
            'community_id':[10]*4,'internal_piece_id':[10,10,12,12]})
        data.to_csv(self.comm/'particoes_nos.csv.gz',index=False)
        pairs=pd.DataFrame({'source_id':[10,12],'target_id':[11,13],'weight':[1,1]})
        pairs.to_csv(self.proj/'ponderada_nao_dirigida.csv.gz',index=False)
        (self.comm/'execucoes_gds.json').write_text(json.dumps({'leiden_seed_44':{'config':{'randomSeed':44,'maxLevels':10,'consecutiveIds':True,'tolerance':1e-4},'gds_version':'2026.09.0'}}))
        for folder,signature,extra in [(self.comm,'c'*64,{'network_snapshot_sha256':'a'*64,'projection_snapshot_sha256':'p'*64}),(self.proj,'p'*64,{'graph_names':{'community':'original_graph'}})]:
            meta={'snapshot_sha256':signature,**extra,'outputs_sha256':{p.name:sha(p) for p in folder.iterdir()}}
            (folder/'manifesto.json').write_text(json.dumps(meta))
        (self.comm.parent.parent/'atual.json').write_text(json.dumps({'folder':'instancias/abc','snapshot_sha256':'c'*64}))
        (self.proj.parent/'atual.json').write_text(json.dumps({'folder':'def','snapshot_sha256':'p'*64}))
        self.original={str(p):sha(p) for p in self.root.rglob('*') if p.is_file()}
        self.driver=FakeDriver();self.state={};self.count=0
    def tearDown(self):self.tmp.cleanup()
    def ops(self):
        def configuration(root):
            if self.state.get('configuration_error'):raise ValueError('password=SECRET bolt://private-host')
            return 'bolt://private-host','private-user','SECRET','neo4j'
        def verify(*args):
            if self.state.get('mismatch'):raise ValueError('Banco ou contagens diferentes da projeção esperada.')
            return {'graphName':args[1],'nodeCount':4,'relationshipCount':4}
        def run(*args):
            self.count+=1
            if self.state.get('fail_run')==self.count:raise ValueError('server says SECRET')
            return pd.DataFrame({'entity_group_id':[10,11,12,13],'community_id':[5]*4}),{'gds_version':'2026.09.0'}
        def canonical(frame,ids):
            f=frame.rename(columns={'community_id':'raw_community_id'});f['community_id']=10;return f
        return dict(configuration=configuration,verify=verify,expected=lambda *a:{},
                    project_query=lambda *a:'PROJECT_QUERY',run=run,canonical=canonical,compare=lambda *a:{'ari':1.,'nmi':1.})
    def execute(self,**kwargs):
        with patch.object(diagnostic,'_operations',self.ops):return diagnostic.diagnosticar_global(self.root,executar_gds=True,driver_factory=lambda *a,**k:self.driver,**kwargs)
    def preserved(self):
        for p,h in self.original.items():self.assertEqual(sha(p),h)
        self.assertFalse((self.root/'resultados/revisao_pendencias/diagnostico_gds/execucao.lock').exists())
    def test_existing_projection_reused_and_original_preserved(self):
        result=self.execute();self.assertEqual(result['runs'],4);self.assertFalse(self.driver.created);self.assertFalse(self.driver.dropped);self.assertTrue(self.driver.closed);self.preserved()
    def test_missing_projection_created_temporarily_and_removed(self):
        self.driver.exists=False;result=self.execute()
        self.assertEqual(len(self.driver.created),1);self.assertEqual(self.driver.created,self.driver.dropped)
        self.assertNotIn('original_graph',self.driver.dropped);self.assertEqual(result['gds_graphs_removed'],1);self.preserved()
    def test_mismatch_not_silently_replaced(self):
        self.state['mismatch']=True
        with self.assertRaisesRegex(RuntimeError,'VALIDAR_PROJECAO_COMPLETA.*Banco ou contagens'):self.execute()
        self.assertFalse(self.driver.created);self.assertFalse(self.driver.dropped);self.preserved()
    def test_failure_retains_partial_results_and_cleans_temporary_graph(self):
        self.driver.exists=False;self.state['fail_run']=2
        with self.assertRaisesRegex(RuntimeError,'EXECUTAR_seed44_sem_consecutiveIds'):self.execute()
        self.assertEqual(self.driver.created,self.driver.dropped)
        base=self.root/'resultados/revisao_pendencias/diagnostico_gds'
        with zipfile.ZipFile(base/'Resumo_Diagnostico_Leiden_GDS_Falha.zip') as z:
            self.assertIn('seed44_original.csv.gz',z.namelist())
            report=json.loads(z.read('diagnostico_falha.json'));self.assertEqual(len(report['runs']),1)
            self.assertNotIn('SECRET',z.read('diagnostico_falha.json').decode())
        self.preserved()
    def test_unknown_error_redacted_and_stage_retained(self):
        self.state['configuration_error']=True
        with self.assertRaises(RuntimeError) as ctx:self.execute()
        self.assertIn('CONFIGURAR_NEO4J',str(ctx.exception));self.assertNotIn('SECRET',str(ctx.exception))
        p=self.root/'resultados/revisao_pendencias/diagnostico_gds/Falha_Diagnostico_Leiden_GDS.json'
        report=p.read_text();self.assertNotIn('SECRET',report);self.assertNotIn('private-host',report);self.preserved()
    def test_recreation_can_be_disabled(self):
        self.driver.exists=False
        with self.assertRaisesRegex(RuntimeError,'Projeção ausente ou ambígua'):self.execute(recriar_projecao_ausente=False)
        self.assertFalse(self.driver.created);self.preserved()
    def test_dry_run_never_loads_connection_operations(self):
        with patch.object(diagnostic,'_operations',side_effect=AssertionError('must not load')):
            result=diagnostic.diagnosticar_global(self.root,executar_gds=False)
        self.assertEqual(result['neo4j_connections'],0);self.assertFalse((self.root/'resultados/revisao_pendencias').exists())

if __name__=='__main__':unittest.main(verbosity=2)
