"""Testes sintéticos da integração, sem modelos, serviços ou dados externos."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from contextlib import redirect_stdout
import io,json,unittest,zipfile
import pandas as pd
import entidades_integracao as er


def fixture(root):
    source=root/'fonte';source.mkdir();ner=root/'dados/processados/ner/consolidado';ner.mkdir(parents=True)
    rows=[]
    for i,(nid,typ,surface,gid,name,review) in enumerate([
        ('n1','PESSOA','Ana','1','Ana','0'),('n1','ORGANIZACAO','Empresa','2','Empresa','0'),
        ('n1','PESSOA','A.','1','Ana','1'),('n2','PESSOA','João','3','João','0')]):
        rows.append(dict(mention_id=f'{i+1:064x}',news_id=nid,news_version_id=nid+'v',ner_input_sha256=nid+'h',
            ent_label=typ,ent_text=surface,entity_group_id=gid,entity_group_name=name,entity_review_required=review,
            entity_quality_status='eligible',entity_resolution_status='EXISTING_ASSOCIATION'))
    a=pd.DataFrame(rows);a.to_csv(source/'associacoes_mencoes.csv.gz',index=False)
    a[['mention_id','news_id','news_version_id','ner_input_sha256','ent_label','ent_text']].to_csv(ner/'mencoes_pol.csv.gz',index=False)
    pd.DataFrame([dict(entity_group_id=gid,entity_group_name=name,ent_label=label,registry_member='1')
        for gid,name,label in [('1','Ana','PESSOA'),('2','Empresa','ORGANIZACAO'),('3','João','PESSOA')]]).to_csv(source/'registro_entidades.csv',index=False)
    meta=dict(schema='er-associations-1',input_signature='a'*64,mentions_total=4,groups_used=3,review_mentions=1,
        outputs={name:er.sha(source/name) for name in er.INPUT_FILES})
    (source/'manifesto.json').write_text(json.dumps(meta))
    re_folder=root/'relacoes';re_folder.mkdir();rels=[]
    for i,(head,tail,label) in enumerate([(0,1,'vinculo_inst'),(0,2,'ident'),(0,1,'ident'),(0,2,'vinculo_inst')]):
        h,t=rows[head],rows[tail];rels.append(dict(relation_id=str(i),news_id='n1',news_version_id='n1v',head_id=h['mention_id'],tail_id=t['mention_id'],
            head_type=h['ent_label'],tail_type=t['ent_label'],head_surface=h['ent_text'],tail_surface=t['ent_text'],label=label,
            technical_provisional='False',semantic_flags='',origin='EXECUTION'))
    pd.DataFrame(rels).to_csv(re_folder/'relacoes_mencoes.csv.gz',index=False)
    return source,re_folder,dict(snapshot_sha256='b'*64,summary={'relations':4})


class EntityTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.source,self.re,self.meta=fixture(self.root)
        self.quiet=redirect_stdout(io.StringIO());self.quiet.__enter__();self.addCleanup(self.quiet.__exit__,None,None,None)
        self.mock=patch.object(er,'carregar_consolidado_re',side_effect=lambda root:(self.re,self.meta));self.mock.start();self.addCleanup(self.mock.stop)
        er.registrar_associacoes(self.root,self.source)
    def test_all_rows_ids_and_diagnostics_preserved(self):
        result=er.aplicar_resolucao(self.root,tamanho_bloco=2)
        self.assertEqual(result['mentions'],4);self.assertEqual(result['groups'],3);self.assertEqual(result['relations_preserved'],4)
        self.assertEqual(result['relation_roles'],{'SEMANTIC_BETWEEN_GROUPS':1,'IDENTITY_WITHIN_GROUP':1,'IDENTITY_BETWEEN_GROUPS':1,'SEMANTIC_WITHIN_GROUP':1})
        frame=pd.read_csv(result['output_directory']/'relacoes_resolvidas.csv.gz',dtype=str)
        self.assertEqual(frame.head_entity_id.tolist(),['1']*4)
        self.assertEqual(frame.tail_entity_id.tolist(),['2','1','2','1'])
        self.assertEqual(er.sha(self.source/'associacoes_mencoes.csv.gz'),er.sha(result['output_directory']/'mencoes_resolvidas.csv.gz'))
    def test_idempotency_and_immutable_sources(self):
        before={p:er.sha(p) for p in self.source.iterdir()}
        a=er.aplicar_resolucao(self.root);b=er.aplicar_resolucao(self.root,tamanho_bloco=1)
        self.assertEqual(a['output_directory'],b['output_directory'])
        self.assertTrue(all(er.sha(p)==h for p,h in before.items()))
    def test_new_re_requires_new_integration_preserving_old(self):
        a=er.aplicar_resolucao(self.root);self.meta=dict(self.meta,snapshot_sha256='c'*64)
        with self.assertRaises(ValueError):er.carregar_entidades_integradas(self.root)
        b=er.aplicar_resolucao(self.root)
        self.assertNotEqual(a['output_directory'],b['output_directory']);self.assertTrue(a['output_directory'].exists())
    def test_missing_ner_association_blocks_activation(self):
        p=self.root/'dados/processados/ner/consolidado/mencoes_pol.csv.gz';d=pd.read_csv(p,dtype=str);d.loc[len(d)]=d.iloc[0];d.loc[len(d)-1,'mention_id']='f'*64;d.to_csv(p,index=False)
        with self.assertRaises(ValueError):er.aplicar_resolucao(self.root)
        self.assertFalse((self.root/'dados/processados/entidades/resolucao/atual.json').exists())
    def test_endpoint_version_mismatch_is_rejected(self):
        p=self.re/'relacoes_mencoes.csv.gz';d=pd.read_csv(p,dtype=str);d.loc[0,'news_version_id']='outra';d.to_csv(p,index=False)
        with self.assertRaises(ValueError):er.aplicar_resolucao(self.root)
    def test_tampered_output_is_blocked(self):
        result=er.aplicar_resolucao(self.root);(result['output_directory']/'LEIA_ME.txt').write_text('alterado')
        with self.assertRaises(ValueError):er.carregar_entidades_integradas(self.root)
    def test_zip_registration_preserves_same_version(self):
        archive=self.root/'associacoes.zip'
        with zipfile.ZipFile(archive,'w') as z:
            for p in self.source.iterdir():z.write(p,p.name)
        registered=er.registrar_associacoes(self.root,archive)
        self.assertEqual(er.fonte_ativa(self.root)[0],registered)
        self.assertEqual(er.sha(registered/'associacoes_mencoes.csv.gz'),er.sha(self.source/'associacoes_mencoes.csv.gz'))
    def test_registration_does_not_accept_altered_data(self):
        (self.source/'registro_entidades.csv').write_text('alterado')
        with self.assertRaises(ValueError):er.registrar_associacoes(self.root,self.source)

if __name__=='__main__':unittest.main(verbosity=2)
