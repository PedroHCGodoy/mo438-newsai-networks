"""Testes sintéticos de consolidação: não leem chaves nem chamam APIs."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from contextlib import redirect_stdout
import io,json,sqlite3,unittest
import pandas as pd
import re_execucao as r
from re_consolidacao import consolidar_re,carregar_consolidado_re,sha


def save_manifest(folder, **extra):
    r.atomic_json(folder/'manifesto.json',dict(outputs_sha256={p.name:sha(p) for p in folder.iterdir() if p.is_file() and p.name!='manifesto.json'},**extra))


def fixture(root):
    folder=root/'dados/processados/re/execucao';folder.mkdir(parents=True)
    nid='a'*64;ver='b'*64;mid1='c'*64;mid2='d'*64;text='Título\n\nAna trabalha na Empresa.'
    base=pd.DataFrame([dict(news_id=nid,news_version_id=ver,title='Título',full_text='Ana trabalha na Empresa.',publication_year='2024',source_normalized='Fonte',link='https://example.org')])
    base.to_csv(root/'dados/processados/noticias_preparadas.csv',index=False)
    ner=root/'dados/processados/ner/consolidado';ner.mkdir(parents=True)
    mentions=pd.DataFrame([dict(mention_id=mid,news_id=nid,news_version_id=ver,ner_input_sha256=r.digest(text),ent_text=surface,ent_label=kind)
        for mid,surface,kind in [(mid1,'Ana','PESSOA'),(mid2,'Empresa','ORGANIZACAO')]])
    mentions.to_csv(ner/'mencoes_pol.csv.gz',index=False)
    pd.DataFrame([dict(news_id=nid)]).to_csv(folder.parent/'fila_re.csv',index=False)
    identity=dict(news_id=nid,news_version_id=ver,ner_input_sha256=r.digest(text),prompt_sha256='teste',contract=r.contrato('deepinfra'))
    rid=r.digest(json.dumps(identity,sort_keys=True,ensure_ascii=False));attempt='e'*32
    validation=dict(request_id=rid,attempt_id=attempt,identity=identity,news=dict(news_id=nid),state='SUCCESS',updated_at=r.agora())
    r.atomic_json(folder/'validacoes'/(rid+'.json'),validation)
    with sqlite3.connect(folder/'checkpoint.sqlite3') as db:
        db.execute('CREATE TABLE requests(request_id TEXT PRIMARY KEY,news_id TEXT,state TEXT,attempt_id TEXT,updated_at TEXT)')
        db.execute('INSERT INTO requests VALUES (?,?,?,?,?)',(rid,nid,'SUCCESS',attempt,r.agora()))
    body=json.dumps(dict(choices=[dict(message=dict(content='[]'),finish_reason='stop')],usage=dict(estimated_cost=0.01,prompt_tokens=10,completion_tokens=5,total_tokens=15)))
    r.atomic_json(folder/'respostas'/rid/(attempt+'.json'),dict(request_id=rid,attempt_id=attempt,identity=identity,http_status=200,body=body,received_at=r.agora(),elapsed_s=2.0))
    post=folder.parent/'posprocessado/teste';post.mkdir(parents=True)
    docs=pd.DataFrame([dict(news_id=nid,news_version_id=ver,revalidation_state='SUCCESS')]);docs.to_csv(post/'documentos_revalidados.csv',index=False)
    relation=dict(news_id=nid,news_version_id=ver,head_id=mid1,tail_id=mid2,label='vinculo_inst',head_surface='Ana',tail_surface='Empresa',head_type='PESSOA',tail_type='ORGANIZACAO',
        request_id=rid,attempt_id=attempt,provider='deepinfra',model='google/gemini-2.5-flash',revalidation_state='SUCCESS',technical_provisional='False',ner_availability='AVAILABLE',semantic_flags='',semantic_status='NOT_REVIEWED')
    pd.DataFrame([relation]).to_csv(post/'relacoes_posprocessadas.csv.gz',index=False)
    save_manifest(post,snapshot_sha256='pos-teste',inputs_sha256={str((folder/'validacoes'/(rid+'.json')).relative_to(root)).replace('\\','/'):sha(folder/'validacoes'/(rid+'.json'))})
    imported=folder.parent/'importado';imported.mkdir()
    pd.DataFrame(columns=['news_id','news_version_id','state','instruction_variant']).to_csv(imported/'documentos_importados.csv.gz',index=False)
    pd.DataFrame(columns=['news_id','news_version_id','head_id','tail_id','label','provider','model','source_document_id','instruction_sha256','instruction_variant','ner_availability','head_surface','tail_surface','head_type','tail_type']).to_csv(imported/'relacoes_importadas.csv.gz',index=False)
    pd.DataFrame([dict(news_id=nid,news_version_id=ver,ner_availability='AVAILABLE')]).to_csv(imported/'cobertura_ner.csv',index=False)
    save_manifest(imported)
    return post,folder


class ConsolidationTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.post,self.source=fixture(self.root)
        self.quiet=redirect_stdout(io.StringIO());self.quiet.__enter__();self.addCleanup(self.quiet.__exit__,None,None,None)
        self.transport=patch.object(r,'transporte_http',side_effect=AssertionError('API proibida'));self.transport.start();self.addCleanup(self.transport.stop)
    def test_repeat_and_source_preservation(self):
        before={p:sha(p) for p in self.source.rglob('*') if p.is_file()}
        a=consolidar_re(self.root,self.post);b=consolidar_re(self.root,self.post)
        self.assertEqual(a['relations'],1);self.assertEqual(a['output_directory'],b['output_directory'])
        self.assertTrue(all(sha(p)==value for p,value in before.items()))
        self.assertEqual(carregar_consolidado_re(self.root)[0],a['output_directory'])
    def test_new_attempt_blocks_stale_results(self):
        consolidar_re(self.root,self.post)
        with sqlite3.connect(self.source/'checkpoint.sqlite3') as db:db.execute("UPDATE requests SET updated_at='2099-01-01'")
        with self.assertRaises(ValueError):carregar_consolidado_re(self.root)
    def test_new_snapshot_preserves_previous_version(self):
        a=consolidar_re(self.root,self.post)
        with sqlite3.connect(self.source/'checkpoint.sqlite3') as db:db.execute("UPDATE requests SET updated_at='2099-01-01'")
        b=consolidar_re(self.root,self.post)
        self.assertNotEqual(a['output_directory'],b['output_directory'])
        self.assertTrue(a['output_directory'].exists())
        self.assertEqual(b['relations'],1)
        self.assertEqual(carregar_consolidado_re(self.root)[0],b['output_directory'])
    def test_windows_manifest_paths_are_supported(self):
        p=self.post/'manifesto.json';m=json.loads(p.read_text())
        m['inputs_sha256']={k.replace('/','\\'):v for k,v in m['inputs_sha256'].items()}
        r.atomic_json(p,m)
        self.assertEqual(consolidar_re(self.root,self.post)['relations'],1)
    def test_modified_output_is_detected(self):
        a=consolidar_re(self.root,self.post);(a['output_directory']/'LEIA_ME.txt').write_text('alterado')
        with self.assertRaises(ValueError):carregar_consolidado_re(self.root)
    def test_foreign_endpoint_is_rejected(self):
        p=self.post/'relacoes_posprocessadas.csv.gz';frame=pd.read_csv(p,dtype=str,keep_default_na=False);frame.loc[0,'tail_id']='f'*64;frame.to_csv(p,index=False)
        save_manifest(self.post,snapshot_sha256='pos-teste',inputs_sha256={str(p.relative_to(self.root)).replace('\\','/'):sha(p) for p in (self.source/'validacoes').glob('*.json')})
        with self.assertRaises(ValueError):consolidar_re(self.root,self.post)
        self.assertFalse((self.source.parent/'consolidado/atual.json').exists())

if __name__=='__main__':unittest.main(verbosity=2)
