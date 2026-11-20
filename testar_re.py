from pathlib import Path
from tempfile import TemporaryDirectory
import copy
import io
import json
import shutil
from contextlib import redirect_stdout
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import re_execucao as r

import pandas as pd

def fixture():
    rows, articles, mentions = [], [], {}
    for i in range(6):
        nid=f'news-{i}'
        text=f'Título {i}\n\nAna trabalha na Empresa.'
        text_hash=r.digest(text)
        rows.append({'planning_id':f'plan-{i}', 'news_id':nid, 'news_version_id':f'v-{i}',
                     'ner_input_sha256':text_hash, 'publication_year':'2025',
                     'publication_date':f'2025-01-{i+1:02d}', 'source':'Fonte sintética',
                     'mentions_pol':'2', 'ner_availability':'AVAILABLE',
                     're_processing_type':'PROCESSAR_DO_ZERO'})
        articles.append({'news_id':nid, 'news_version_id':f'v-{i}',
                         'title':f'Título {i}', 'full_text':'Ana trabalha na Empresa.'})
        mentions[nid]=pd.DataFrame([
            {'mention_id':nid+'-a', 'news_version_id':f'v-{i}', 'ner_input_sha256':text_hash,
             'start':'10', 'end':'13', 'ent_text':'Ana', 'ent_label':'PESSOA'},
            {'mention_id':nid+'-b', 'news_version_id':f'v-{i}', 'ner_input_sha256':text_hash,
             'start':'26', 'end':'33', 'ent_text':'Empresa', 'ent_label':'ORGANIZACAO'}])
    return {'queue':pd.DataFrame(rows), 'news':pd.DataFrame(articles).set_index('news_id'),
            'mentions':mentions, 'prefix':'Instruções sintéticas.\n', 'queue_sha256':'fixture'}
x=fixture()
c=r.contrato('google')
valid={'a','b'}
e={'head_id':'a','tail_id':'b','label':'ident'}
f={'head_id':'a','tail_id':'b','label':'vinculo_inst'}
for raw in [json.dumps([e]),'```json\n'+json.dumps([e])+'\n```','Explicação: '+json.dumps([e]),json.dumps({'relations':[e]})]:
    assert r.validar_resposta(raw,valid)[0]=='SUCCESS'
assert r.validar_resposta('[]',valid)[0]=='SUCCESS_ZERO'
s,edges,audit=r.validar_resposta(json.dumps([e,f])[:-1]+', {',valid)
assert s=='PARTIAL' and len(edges)==2
assert r.validar_resposta(json.dumps([dict(e,head_id='X')]),valid)[0]=='PARTIAL'
assert r.validar_resposta(json.dumps([e]),valid,'MAX_TOKENS')[0]=='PARTIAL'
assert r.validar_resposta('not json',valid)[0]=='INVALID_RESPONSE'

def fake(prompt, contract, key, timeout):
    payload=json.loads(prompt.split('LISTA DE ENTIDADES\n')[-1]); a,b=payload[:2]
    raw=json.dumps([{'head_id':a['em_id'],'tail_id':b['em_id'],'label':'ident'}])
    return 200,json.dumps({'candidates':[{'content':{'parts':[{'text':raw}]},'finishReason':'STOP'}]}).encode()

checks=[]
with TemporaryDirectory() as tmp,redirect_stdout(io.StringIO()):
    y=dict(x, root=Path(tmp)); y['queue']=x['queue'].head(6)
    assert r.executar(y,limite=1)['api_calls']==0
    assert not list(Path(tmp).iterdir())
    a=r.executar(y,executar_api=True,limite=2,trabalhadores=2,transport=fake)
    assert a['api_calls']==2 and a['states_this_run']=={'SUCCESS':2}
    b=r.executar(y,executar_api=True,limite=2,trabalhadores=2,transport=fake)
    assert b['api_calls']==2
    folder=Path(tmp)/'dados/processados/re/execucao'
    # Simula queda após persistir resposta e antes de confirmar checkpoint.
    db=r.abrir_db(folder)
    row=y['queue'].iloc[0].to_dict();req=r.montar_requisicao(y,row,c)
    attempt=db.execute('SELECT attempt_id FROM requests WHERE request_id=?',(req['request_id'],)).fetchone()[0]
    r.salvar_estado(db,req,'RUNNING',attempt);db.close()
    d=r.executar(y,executar_api=True,limite=1,transport=fake)
    assert d['recovered_without_call']==1 and d['api_calls']==1
    # A última notícia deve ficar registrada como incerta sem reenvio automático.
    def timeout(*args):raise TimeoutError('não expor segredos')
    d=r.executar(y,executar_api=True,limite=1,transport=timeout)
    assert d['states_this_run']=={'UNCERTAIN':1}
    d=r.executar(y,executar_api=True,limite=1,transport=fake)
    assert d['api_calls']==0
    assert r.exportar(y).exists()
    assert r.executar(y,executar_api=True,provider='deepinfra',transport=fake)['api_calls']==0
with TemporaryDirectory() as tmp,redirect_stdout(io.StringIO()):
    y=dict(x,root=Path(tmp));y['queue']=x['queue'].head(4)
    def invalid(*args):return 200,b'{"candidates":[{"content":{"parts":[{"text":"invalido"}]}}]}'
    a=r.executar(y,executar_api=True,limite=3,transport=invalid)
    assert a['api_calls']==3 and not a['paused']
with TemporaryDirectory() as tmp,redirect_stdout(io.StringIO()):
    y=dict(x,root=Path(tmp));y['queue']=x['queue'].head(4)
    a=r.executar(y,executar_api=True,limite=4,transport=lambda *a:(401,b'{}'))
    assert a['api_calls']==1 and a['paused']
print('Testes sem rede: parser, truncamento, execução paralela, retomada, recuperação, estados incertos, pausa HTTP e contrato: OK.')

# A normalização precede a taxonomia e a deduplicação das triplas.
for raw_label, expected in [('VINCULO_INST','vinculo_inst'), ('Vínculo-inst','vinculo_inst'),
                            ('  vínculo inst  ','vinculo_inst'), ('sede-de','sede_de')]:
    state, edges, audit = r.validar_resposta(json.dumps([dict(e,label=raw_label)]), valid)
    assert state == 'SUCCESS' and edges[0]['label'] == expected
    assert audit['normalizations'][0]['label_raw'] == raw_label.strip()
state, edges, audit = r.validar_resposta(json.dumps([dict(e,label='IDENT'), e, f]),valid)
assert state == 'SUCCESS' and len(edges) == 2 and audit['normalized_duplicates'] == 1
state, edges, audit = r.validar_resposta(json.dumps([dict(e,label='ROTULO_INEXISTENTE')]),valid)
assert state == 'PARTIAL' and not edges and audit['rejected'][0]['reason'] == 'UNKNOWN_RELATION_LABEL'
assert r.normalize_re_label('nome_de_ident') == 'nome_de'
assert r.normalize_re_label('residente_em') == 'residente_de'
print('Normalização de rótulos e deduplicação após normalização: OK.')

# O filtro muda o lote, sem modificar a fila nem a identidade das chamadas.
with TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
    y=dict(fixture(),root=Path(tmp))
    y['queue'].loc[:2,'publication_year']='2024'
    original=y['queue'].copy(deep=True)
    a=r.executar(y,executar_api=True,limite=20,trabalhadores=2,anos=[2024],transport=fake)
    assert a['api_calls']==3
    statefile=Path(tmp)/'resultados/tabelas/re/progresso_re.csv'
    progress=pd.read_csv(statefile,dtype=str)
    assert len(progress)==6
    assert progress.loc[progress.publication_year.eq('2024'),'state'].eq('SUCCESS').all()
    assert progress.loc[progress.publication_year.eq('2025'),'state'].eq('PENDING').all()
    # Mesmo com limite alto, não deve atravessar para 2025 nem repetir 2024.
    b=r.executar(y,executar_api=True,limite=20,anos=[2024],transport=fake)
    assert b['api_calls']==0
    c=r.executar(y,executar_api=True,limite=20,anos=[2025],transport=fake)
    assert c['api_calls']==3
    assert y['queue'].equals(original)
    assert pd.read_csv(statefile).state.eq('SUCCESS').all()
    for invalid in [[],[2026],[True],2024]:
        try:r.executar(y,anos=invalid)
        except ValueError:pass
        else:raise AssertionError('Seleção inválida foi aceita')
print('Filtro anual: parada no recorte, retomada, alternância de anos e progresso integral: OK.')
