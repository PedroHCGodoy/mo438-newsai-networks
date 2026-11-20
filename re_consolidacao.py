"""Consolidação versionada de relações entre menções, sem inferência remota."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import hashlib
import json
import os
import shutil
import tempfile
import gzip
import sqlite3
import zipfile
import uuid
import pandas as pd
import re_execucao
from re_posprocessamento import _alertas

VERSION = '1.0.0'
RELATION_COLUMNS = ['relation_id','news_id','news_version_id','head_id','tail_id','label',
    'head_surface','tail_surface','head_type','tail_type','origin','provider','model',
    'request_id','attempt_id','source_document_id','instruction_sha256','instruction_variant',
    'execution_state','ner_availability','technical_provisional','semantic_status','semantic_flags']


def sha(path):
    return re_execucao.sha_file(path)


def json_sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def read_csv(path):
    return pd.read_csv(path,dtype=str,keep_default_na=False)


def execution_fingerprint(root):
    source=Path(root)/'dados/processados/re/execucao'
    if (source/'execucao.lock').exists():
        raise RuntimeError('Aguarde o encerramento do lote RE para consolidar.')
    dbpath=source/'checkpoint.sqlite3'
    if not dbpath.exists():raise FileNotFoundError('Checkpoint RE ausente.')
    with sqlite3.connect(f'file:{dbpath.resolve().as_posix()}?mode=ro',uri=True) as db:
        states=db.execute('SELECT * FROM requests ORDER BY request_id').fetchall()
    validations={str(p.relative_to(source)):sha(p) for p in re_execucao.caminhos_validacoes_ativas(source)}
    return json_sha({'states':states,'validations':validations})


def write_csv(folder,name,frame):
    if name.endswith('.gz'):
        with (folder/name).open('wb') as stream:
            with gzip.GzipFile(fileobj=stream,mode='wb',filename='',mtime=0) as gz:
                frame.to_csv(gz,index=False,encoding='utf-8',lineterminator='\n')
    else:frame.to_csv(folder/name,index=False,encoding='utf-8-sig',lineterminator='\n')


def validate_manifest(folder):
    manifest=json.loads((folder/'manifesto.json').read_text(encoding='utf-8'))
    for name,expected in manifest['outputs_sha256'].items():
        if Path(name).name!=name or sha(folder/name)!=expected:
            raise ValueError('Arquivo derivado ausente ou modificado: '+name)
    return manifest


def attempt_statistics(source):
    records=[]
    for path in sorted((source/'respostas').glob('*/*.json')):
        env=json.loads(path.read_text(encoding='utf-8'))
        contract=env['identity']['contract'];usage={}
        if env['http_status']==200:
            try:
                body=json.loads(env['body'])
                _,_,usage=re_execucao.extrair_payload(body,contract['provider'])
            except (ValueError,TypeError,AttributeError,KeyError):
                usage={}
        has_cost='estimated_cost' in usage and usage['estimated_cost'] is not None
        records.append({'request_id':env['request_id'],'attempt_id':env['attempt_id'],
            'news_id':env['identity']['news_id'],'provider':contract['provider'],'model':contract['model'],
            'http_status':env['http_status'],'received_at_utc':env['received_at'],'elapsed_s':env['elapsed_s'],
            'prompt_tokens':usage.get('prompt_tokens',usage.get('promptTokenCount','')),
            'completion_tokens':usage.get('completion_tokens',usage.get('candidatesTokenCount','')),
            'reasoning_tokens':(usage.get('completion_tokens_details') or {}).get('reasoning_tokens',usage.get('thoughtsTokenCount','')),
            'total_tokens':usage.get('total_tokens',usage.get('totalTokenCount','')),
            'estimated_cost_usd':usage['estimated_cost'] if has_cost else '',
            'cost_status':'PROVIDER_REPORTED_ESTIMATE' if has_cost else 'NOT_REPORTED'})
    attempts=pd.DataFrame(records)
    if attempts.attempt_id.duplicated().any():raise ValueError('Resposta duplicada para uma tentativa.')
    costs=[]
    for (provider,model),g in attempts.groupby(['provider','model'],sort=True):
        values=pd.to_numeric(g.estimated_cost_usd,errors='coerce')
        times=pd.to_numeric(g.elapsed_s)
        costs.append({'provider':provider,'model':model,'responses_saved':len(g),
            'responses_with_cost':int(values.notna().sum()),'responses_without_cost':int(values.isna().sum()),
            'reported_estimated_cost_usd':values.sum(min_count=1),
            'sum_call_elapsed_s':times.sum(),'mean_call_elapsed_s':times.mean(),
            'median_call_elapsed_s':times.median(),'max_call_elapsed_s':times.max()})
    return attempts,pd.DataFrame(costs)


def consolidar_re(projeto, pasta_posprocessada):
    """Cria um snapshot e atualiza o apontador apenas após validar todas as saídas."""
    root=Path(projeto).resolve();post=Path(pasta_posprocessada).resolve()
    fingerprint=execution_fingerprint(root)
    postmanifest=validate_manifest(post)
    # O pós-processamento precisa representar exatamente a execução atual.
    source=root/'dados/processados/re/execucao'
    post_sources={k.replace('\\','/'):v for k,v in postmanifest['inputs_sha256'].items()}
    active=re_execucao.caminhos_validacoes_ativas(source)
    recorded={k:v for k,v in post_sources.items() if k.startswith('dados/processados/re/execucao/validacoes/')}
    current={str(p.relative_to(root)).replace(os.sep,'/'):sha(p) for p in active}
    recorded={k.replace('\\','/'):v for k,v in recorded.items()}
    if recorded!=current:raise ValueError('Pós-processamento desatualizado; execute a seção 25 novamente.')
    imported=root/'dados/processados/re/importado';im=validate_manifest(imported)
    dependencies=[root/'dados/processados/noticias_preparadas.csv',root/'dados/processados/ner/consolidado/mencoes_pol.csv.gz',
        root/'dados/processados/re/fila_re.csv',post/'manifesto.json',post/'relacoes_posprocessadas.csv.gz',post/'documentos_revalidados.csv',
        imported/'manifesto.json',*[imported/n for n in im['outputs_sha256']]]
    hashes={str(p.relative_to(root)).replace(os.sep,'/'):sha(p) for p in dependencies}
    signature=json_sha({'version':VERSION,'inputs':hashes,'execution':fingerprint,'code':sha(Path(__file__))})
    destination=root/'dados/processados/re/consolidado'/signature[:20]
    if destination.exists():
        manifest=validate_manifest(destination)
        if manifest.get('snapshot_sha256')!=signature:raise ValueError('Identidade do snapshot incompatível.')
    else:
        base=read_csv(dependencies[0]);queue=read_csv(root/'dados/processados/re/fila_re.csv')
        if not base.news_id.is_unique or not queue.news_id.is_unique:raise ValueError('Identidades documentais duplicadas.')
        mentions=pd.read_csv(dependencies[1],dtype=str,keep_default_na=False,
            usecols=['mention_id','news_id','news_version_id','ner_input_sha256','ent_text','ent_label'])
        if not mentions.mention_id.is_unique:raise ValueError('IDs de menção duplicados.')
        byid=mentions.set_index('mention_id')
        rd=read_csv(post/'documentos_revalidados.csv');re=read_csv(post/'relacoes_posprocessadas.csv.gz')
        idocs=read_csv(imported/'documentos_importados.csv.gz');ie=read_csv(imported/'relacoes_importadas.csv.gz')
        if not rd.news_id.is_unique or not idocs.news_id.is_unique:raise ValueError('Mais de um resultado documental ativo.')
        # Uma tentativa atual substitui a importação apenas com resposta utilizável.
        replacing=set(rd.loc[rd.revalidation_state.isin(['SUCCESS','SUCCESS_ZERO','PARTIAL']),'news_id'])
        idocs=idocs.loc[~idocs.news_id.isin(replacing)].copy();ie=ie.loc[ie.news_id.isin(set(idocs.news_id))].copy()
        re=re.copy();re['origin']='EXECUTION';re['execution_state']=re.revalidation_state
        re['source_document_id']='';re['instruction_sha256']=re_execucao.PROMPT_SHA256;re['instruction_variant']=False
        ie=ie.copy();ie['origin']='IMPORT';ie['request_id']='';ie['attempt_id']='';ie['execution_state']='SUCCESS'
        ie['technical_provisional']=ie.ner_availability.eq('PARTIAL')
        re['technical_provisional']=re.technical_provisional.str.lower().eq('true')|re.ner_availability.eq('PARTIAL')
        ie['semantic_status']='NOT_REVIEWED';ie['semantic_flags']=''
        for col in ['provider','model','attempt_id']:
            if col not in re:raise ValueError('Atualize o módulo de pós-processamento antes de consolidar.')
        rel=pd.concat([ie,re],ignore_index=True,sort=False)
        if not set(rel.label)<=re_execucao.LABELS:raise ValueError('Rótulos de relação fora do contrato.')
        for endpoint in ['head','tail']:
            ids=rel[endpoint+'_id']
            if not ids.isin(byid.index).all():raise ValueError('Relação com menção ausente no snapshot NER.')
            linked=byid.reindex(ids).reset_index(drop=True)
            for column in ['news_id','news_version_id']:
                if not linked[column].eq(rel[column]).all():raise ValueError('Relação e menção pertencem a documentos ou versões diferentes.')
            if not linked.ent_text.eq(rel[endpoint+'_surface']).all() or not linked.ent_label.eq(rel[endpoint+'_type']).all():
                raise ValueError('Superfície ou categoria de menção incompatível.')
        if rel.head_id.eq(rel.tail_id).any():raise ValueError('Autorrelação entre a mesma menção.')
        for index,row in rel.loc[rel.origin.eq('IMPORT')].iterrows():
            entities={row.head_id:{'categoria':row.head_type},row.tail_id:{'categoria':row.tail_type}}
            flags=_alertas({'head_id':row.head_id,'tail_id':row.tail_id,'label':row.label},entities)
            rel.at[index,'semantic_flags']='|'.join(flags)
            if flags:rel.at[index,'semantic_status']='REVIEW_PENDING'
        keys=['news_id','news_version_id','head_id','tail_id','label']
        if rel.duplicated(keys).any():raise ValueError('Relações duplicadas entre as entradas; requer conciliação explícita.')
        rel['relation_id']=[json_sha(list(x)) for x in rel[keys].itertuples(index=False,name=None)]
        rel=rel[RELATION_COLUMNS].sort_values(keys,kind='stable').reset_index(drop=True)
        coverage=base[['news_id','news_version_id','publication_year','source_normalized','link']].copy().rename(columns={'source_normalized':'source'})
        nc=read_csv(imported/'cobertura_ner.csv').set_index('news_id')
        if not coverage.news_id.isin(nc.index).all():raise ValueError('A cobertura NER precisa ser atualizada para a nova base.')
        if not coverage.news_version_id.eq(coverage.news_id.map(nc.news_version_id)).all():raise ValueError('Versões documentais mudaram; atualize a conciliação NER/importação.')
        coverage['ner_availability']=coverage.news_id.map(nc.ner_availability)
        counts=mentions.groupby('news_id').size();coverage['mentions_pol']=coverage.news_id.map(counts).fillna(0).astype(int)
        bidx=base.set_index('news_id')
        for nid,g in mentions.groupby('news_id',sort=False):
            article=bidx.loc[nid];text=article.title.strip()+'\n\n'+article.full_text.strip()
            if not g.news_version_id.eq(article.news_version_id).all() or not g.ner_input_sha256.eq(re_execucao.digest(text)).all():
                raise ValueError('Texto da base e snapshot NER incompatíveis.')
        coverage['re_state']='NOT_READY_NER'
        coverage.loc[coverage.ner_availability.isin(['AVAILABLE','PARTIAL'])&coverage.mentions_pol.lt(2),'re_state']='TOO_FEW_MENTIONS'
        coverage.loc[coverage.news_id.isin(set(queue.news_id)),'re_state']='PENDING'
        coverage['origin']='';coverage['instruction_variant']=False
        idocmap=idocs.set_index('news_id');mask=coverage.news_id.isin(idocmap.index)
        coverage.loc[mask,'re_state']=coverage.loc[mask,'news_id'].map(idocmap.state)
        coverage.loc[mask,'origin']='IMPORT';coverage.loc[mask,'instruction_variant']=coverage.loc[mask,'news_id'].map(idocmap.instruction_variant).astype(str).str.lower().eq('true')
        dmap=rd.set_index('news_id');mask=coverage.news_id.isin(dmap.index)&~coverage.news_id.isin(set(idocs.news_id))
        coverage.loc[mask,'re_state']=coverage.loc[mask,'news_id'].map(dmap.revalidation_state);coverage.loc[mask,'origin']='EXECUTION'
        with sqlite3.connect(f'file:{(source/"checkpoint.sqlite3").resolve().as_posix()}?mode=ro',uri=True) as db:
            active_states=re_execucao.estados_ativos(db)
        for nid,(_,state,_) in active_states.items():
            if state in ['UNCERTAIN','RUNNING'] and nid not in set(idocs.news_id):coverage.loc[coverage.news_id.eq(nid),'re_state']=state
        coverage['relations']=coverage.news_id.map(rel.groupby('news_id').size()).fillna(0).astype(int)
        coverage['technical_provisional']=coverage.re_state.eq('PARTIAL')|coverage.ner_availability.eq('PARTIAL')
        if not set(rel.news_id)<=set(coverage.news_id):raise ValueError('Relações fora da base.')
        if coverage.re_state.eq('NOT_READY_NER').any() and coverage.loc[coverage.re_state.eq('NOT_READY_NER'),'ner_availability'].isin(['AVAILABLE','PARTIAL']).any():
            raise ValueError('Notícia elegível sem planejamento RE nem resultado.')
        tables={
            'cobertura_documental.csv':coverage,
            'relacoes_mencoes.csv.gz':rel,
            'relacoes_identidade.csv.gz':rel.loc[rel.label.eq('ident')],
            'relacoes_semanticas.csv.gz':rel.loc[rel.label.ne('ident')],
            'pendencias_inspecao.csv':rel.loc[rel.semantic_flags.ne('')],
            'cobertura_por_ano_fonte.csv':coverage.groupby(['publication_year','source','re_state','origin'],dropna=False).size().reset_index(name='news'),
            'relacoes_por_rotulo_origem.csv':rel.groupby(['label','origin'],dropna=False).size().reset_index(name='relations')}
        attempts,costs=attempt_statistics(source);tables['tentativas_tempo_custo.csv']=attempts;tables['tempo_custo_por_provedor.csv']=costs
        destination.parent.mkdir(parents=True,exist_ok=True)
        temp=Path(tempfile.mkdtemp(prefix='.consolidando_',dir=destination.parent))
        try:
            for name,frame in tables.items():write_csv(temp,name,frame)
            summary={'news':len(coverage),'news_with_re_result':int(coverage.re_state.isin(['SUCCESS','SUCCESS_ZERO','PARTIAL']).sum()),
                'news_by_state':coverage.re_state.value_counts().to_dict(),'imported_news_selected':len(idocs),
                'executed_news_revalidated':len(rd),'relations':len(rel),'identity_relations':int(rel.label.eq('ident').sum()),
                'semantic_relations':int(rel.label.ne('ident').sum()),'relations_by_origin':rel.origin.value_counts().to_dict(),
                'technical_provisional_relations':int(rel.technical_provisional.sum()),
                'semantic_diagnostic_flags':int(rel.semantic_flags.ne('').sum()),'api_calls':0}
            text=('RELAÇÕES ENTRE MENÇÕES — CONSOLIDAÇÃO\n\n'+json.dumps(summary,ensure_ascii=False,indent=2)+
                '\n\nO snapshot é parcial enquanto houver notícias pendentes. SUCCESS indica validação técnica, não aprovação semântica.\n'+
                'Identidades e relações semânticas permanecem separadas. Não há resolução de entidades, expansão transitiva ou agregação de pesos nesta etapa.\n'+
                'Valores de custo são estimativas informadas pela API; ausências não são custos zero. A soma dos tempos das chamadas não é a duração do lote paralelo.\n')
            (temp/'LEIA_ME.txt').write_text(text,encoding='utf-8')
            manifest={'schema':'re-consolidation-1','version':VERSION,'snapshot_sha256':signature,'created_at_utc':datetime.now(timezone.utc).isoformat(),
                'postprocessing_snapshot':postmanifest['snapshot_sha256'],'execution_fingerprint':fingerprint,
                'inputs_sha256':hashes,'code_sha256':sha(Path(__file__)),'summary':summary,
                'outputs_sha256':{p.name:sha(p) for p in sorted(temp.iterdir())}}
            re_execucao.atomic_json(temp/'manifesto.json',manifest)
            if execution_fingerprint(root)!=fingerprint or any(sha(root/name)!=h for name,h in hashes.items()):
                raise ValueError('As entradas mudaram durante a consolidação; nenhum snapshot será ativado.')
            os.rename(temp,destination)
        finally:
            if temp.exists():shutil.rmtree(temp)
    # Ativação atômica: os snapshots anteriores continuam disponíveis.
    re_execucao.atomic_json(destination.parent/'atual.json',{'snapshot_sha256':signature,'folder':destination.name})
    exports=root/'resultados/re';exports.mkdir(parents=True,exist_ok=True)
    package=exports/('Resumo_Consolidacao_RE_'+signature[:12]+'_'+uuid.uuid4().hex[:6]+'.zip')
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(destination.iterdir()):
            if p.name not in {'relacoes_mencoes.csv.gz','relacoes_identidade.csv.gz','relacoes_semanticas.csv.gz'}:
                z.write(p,p.name)
    print('[CONSOLIDAÇÃO RE] '+json.dumps(manifest['summary'],ensure_ascii=False))
    print('[CONSOLIDAÇÃO RE] Snapshot:',destination)
    print('[CONSOLIDAÇÃO RE] Pacote:',package)
    return {**manifest['summary'],'output_directory':destination,'package':package,'snapshot_sha256':signature}


def carregar_consolidado_re(projeto, *, permitir_desatualizado=False):
    """Retorna o snapshot ativo; por padrão bloqueia entradas posteriores à consolidação."""
    root=Path(projeto).resolve();parent=root/'dados/processados/re/consolidado'
    pointer=json.loads((parent/'atual.json').read_text(encoding='utf-8'))
    if Path(pointer['folder']).name!=pointer['folder']:raise ValueError('Apontador inválido.')
    folder=parent/pointer['folder'];manifest=validate_manifest(folder)
    if manifest['snapshot_sha256']!=pointer['snapshot_sha256']:raise ValueError('Apontador e manifesto incompatíveis.')
    if not permitir_desatualizado:
        if execution_fingerprint(root)!=manifest['execution_fingerprint']:
            raise ValueError('Há novas tentativas RE. Execute 25 e 26 antes de atualizar as análises.')
        if any(sha(root/name)!=h for name,h in manifest['inputs_sha256'].items()):
            raise ValueError('Uma entrada mudou; gere e valide uma nova consolidação.')
    return folder,manifest
