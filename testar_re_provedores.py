"""Verificações sintéticas locais; nenhum transporte de rede é utilizado."""
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import redirect_stdout
from unittest.mock import patch
import io
import json
import sqlite3
import unittest
import pandas as pd
import re_execucao as r


def fixture(root, n=5):
    rows, articles, mentions = [], [], {}
    for i in range(n):
        nid = f'{i+1:064x}'; ver = f'versao-{i}'
        text = f'Título {i}\n\nAna trabalha na Empresa.'
        rows.append(dict(planning_id=f'plano-{i}',news_id=nid,news_version_id=ver,
            ner_input_sha256=r.digest(text),publication_year='2024',publication_date='2024-01-01',
            source='Fonte sintética',mentions_pol='2',ner_availability='AVAILABLE',
            re_processing_type='PROCESSAR_DO_ZERO',title=f'Título {i}',link='https://example.org'))
        articles.append(dict(news_id=nid,news_version_id=ver,title=f'Título {i}',full_text='Ana trabalha na Empresa.'))
        mentions[nid] = pd.DataFrame([dict(mention_id=f'{2*i+j+1:064x}',news_version_id=ver,
            ner_input_sha256=r.digest(text),start=str(j*10),end=str(j*10+3),ent_text=surface,ent_label=label)
            for j,(surface,label) in enumerate([('Ana','PESSOA'),('Empresa','ORGANIZACAO')])])
    return dict(root=Path(root),queue=pd.DataFrame(rows),news=pd.DataFrame(articles).set_index('news_id'),
                mentions=mentions,prefix='Instrução sintética.\n',queue_sha256='fila-sintetica')


def good(prompt, contract, key, timeout):
    raw = '[]'
    if contract['provider']=='google':
        body={'candidates':[{'content':{'parts':[{'text':raw}]},'finishReason':'STOP'}]}
    else:
        body={'choices':[{'message':{'content':raw},'finish_reason':'stop'}]}
    return 200,json.dumps(body).encode()


def bad_key(*args):
    return 400,json.dumps({'error':{'status':'INVALID_ARGUMENT','details':[{'reason':'API_KEY_INVALID'}]}}).encode()


class ProvidersTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.x=fixture(self.tmp.name);self.folder=self.x['root']/'dados/processados/re/execucao'
        self.quiet=redirect_stdout(io.StringIO());self.quiet.__enter__();self.addCleanup(self.quiet.__exit__,None,None,None)
    def run_batch(self, **kw):
        return r.executar(self.x,executar_api=True,transport=kw.pop('transport',good),**kw)
    def test_switches_skip_completed(self):
        self.run_batch(limite=2)
        self.run_batch(limite=2,provider='deepinfra',trabalhadores=2)
        self.run_batch(limite=2,provider='google')
        for provider in ['google','deepinfra']:
            self.assertEqual(self.run_batch(limite=10,provider=provider)['api_calls'],0)
        with sqlite3.connect(self.folder/'checkpoint.sqlite3') as db:
            attempts=db.execute('SELECT news_id,provider,model FROM attempts').fetchall()
        self.assertEqual(len(attempts),5); self.assertEqual(len({a[0] for a in attempts}),5)
        self.assertEqual({a[1] for a in attempts},{'google','deepinfra'})
    def test_explicit_retries_preserve_all_attempts_and_export_once(self):
        self.run_batch(transport=bad_key)
        old=r.caminhos_validacoes_ativas(self.folder)[0]; original=old.read_bytes()
        rid=old.stem
        # Provider change alone must not retry the failed document.
        self.x['queue']=self.x['queue'].head(1)
        self.assertEqual(self.run_batch(provider='deepinfra')['api_calls'],0)
        self.assertEqual(self.run_batch(provider='deepinfra',retentar_requisicoes=[rid])['api_calls'],1)
        self.assertEqual(old.read_bytes(),original)
        self.assertEqual(len(r.caminhos_validacoes_ativas(self.folder)),1)
        self.assertEqual(json.loads(r.caminhos_validacoes_ativas(self.folder)[0].read_text())['identity']['contract']['provider'],'deepinfra')
        self.assertEqual(self.run_batch(provider='google',retentar_requisicoes=[rid])['api_calls'],0)
        with sqlite3.connect(self.folder/'checkpoint.sqlite3') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM attempts').fetchone()[0],2)
        progress=pd.read_csv(self.x['root']/'resultados/tabelas/re/progresso_re.csv')
        self.assertEqual(progress.state.tolist(),['SUCCESS_ZERO'])
    def test_same_provider_retry_keeps_old_validation(self):
        self.x['queue']=self.x['queue'].head(1)
        self.run_batch(transport=bad_key)
        path=r.caminhos_validacoes_ativas(self.folder)[0]; old=json.loads(path.read_text())
        self.run_batch(retentar_requisicoes=[path.stem])
        historic=self.folder/'historico_validacoes'/path.stem/(old['attempt_id']+'.json')
        self.assertEqual(json.loads(historic.read_text()),old)
        with sqlite3.connect(self.folder/'checkpoint.sqlite3') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM attempts').fetchone()[0],2)
    def test_uncertain_and_partial_never_retry_after_switch(self):
        self.x['queue']=self.x['queue'].head(1)
        def timeout(*a):raise TimeoutError()
        self.run_batch(transport=timeout)
        with sqlite3.connect(self.folder/'checkpoint.sqlite3') as db:rid=db.execute('SELECT request_id FROM requests').fetchone()[0]
        self.assertEqual(self.run_batch(provider='deepinfra',retentar_requisicoes=[rid])['api_calls'],0)
        # Partial outputs also remain protected, even with explicit authentication retry IDs.
        with TemporaryDirectory() as tmp:
            x=fixture(tmp,1)
            def partial(*a):return 200,b'{"candidates":[{"content":{"parts":[{"text":"[]"}]},"finishReason":"MAX_TOKENS"}]}'
            r.executar(x,executar_api=True,transport=partial)
            folder=Path(tmp)/'dados/processados/re/execucao'
            rid=r.caminhos_validacoes_ativas(folder)[0].stem
            self.assertEqual(r.executar(x,executar_api=True,transport=good,provider='deepinfra',retentar_requisicoes=[rid])['api_calls'],0)
    def test_recover_original_provider_response_after_switch(self):
        self.x['queue']=self.x['queue'].head(1)
        self.run_batch()
        row=self.x['queue'].iloc[0].to_dict();req=r.montar_requisicao(self.x,row,r.contrato('google'))
        db=r.abrir_db(self.folder);attempt=db.execute('SELECT attempt_id FROM requests').fetchone()[0]
        r.salvar_estado(db,req,'RUNNING',attempt);db.close()
        result=self.run_batch(provider='deepinfra')
        self.assertEqual(result['api_calls'],0); self.assertEqual(result['recovered_without_call'],1)
    def test_queue_change_blocked(self):
        self.run_batch();self.x['queue_sha256']='outra'
        with self.assertRaises(ValueError):self.run_batch(provider='deepinfra')
    def test_missing_checkpoint_blocks_sending(self):
        self.run_batch()
        (self.folder/'checkpoint.sqlite3').unlink()
        with self.assertRaises(ValueError):self.run_batch(provider='deepinfra')
    def test_dry_run_excludes_already_attempted_news(self):
        self.run_batch(limite=2)
        result=r.executar(self.x,provider='deepinfra',limite=5)
        self.assertEqual(len(result['preview']),3)
        self.assertTrue(all(item['news_id'] not in set(self.x['queue'].head(2).news_id) for item in result['preview']))
    def test_prompt_and_normalization_unchanged(self):
        row=self.x['queue'].iloc[0].to_dict()
        a=r.montar_requisicao(self.x,row,r.contrato('google'));b=r.montar_requisicao(self.x,row,r.contrato('deepinfra'))
        self.assertEqual(a['prompt'].encode(),b['prompt'].encode());self.assertNotEqual(a['request_id'],b['request_id'])
        self.assertEqual(r.normalize_re_label('Vínculo-inst'),'vinculo_inst')
    def test_dry_run_has_no_writes_or_transport(self):
        with patch.object(r,'transporte_http',side_effect=AssertionError('Rede proibida')):
            self.assertEqual(r.executar(self.x,provider='deepinfra')['api_calls'],0)
        self.assertEqual(list(self.x['root'].iterdir()),[])

if __name__=='__main__':unittest.main(verbosity=2)
