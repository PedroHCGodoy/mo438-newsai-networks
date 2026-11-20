"""Extração documental de relações com respostas persistidas e retomada local."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from collections import Counter
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import uuid
import unicodedata
from typing import Optional
import zipfile
import pandas as pd
from re_parser import parse_llm_doclevel_relations_json

PROMPT_SHA256 = '34f37d5ec453ab94c22048a9b7f064aeac92aaed78d060059ca4bba5bf99a2bc'
LABELS = set('ident vinculo_inst incluido inclui sede_de ocorre_em autor_de obra_de relacao_familiar local_nascimento_de natural_de propriedade_de proprietario_de produtor_de produzido_por'.split())
TERMINAIS = {'SUCCESS', 'SUCCESS_ZERO'}
_PRINT_LOCK = threading.Lock()


def agora():
    return datetime.now(timezone.utc).isoformat()


def sha_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with tmp.open('w', encoding='utf-8', newline='\n') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def log(rid, message):
    with _PRINT_LOCK:
        print(f'[RE {rid[:12]}] {message}', flush=True)


def contrato(provider):
    if provider == 'google':
        return {'schema': 1, 'provider': 'google', 'model': 'gemini-2.5-flash',
                'temperature': 0, 'seed': 42, 'response_mime_type': 'application/json',
                'prompt_id': 'TEST_D12_T13_L04_R15', 'prompt_sha256': PROMPT_SHA256}
    if provider == 'deepinfra':
        return {'schema': 1, 'provider': 'deepinfra', 'model': 'google/gemini-2.5-flash',
                'temperature': 0, 'prompt_id': 'TEST_D12_T13_L04_R15',
                'prompt_sha256': PROMPT_SHA256}
    raise ValueError('PROVEDOR_RE deve ser google ou deepinfra; não há troca automática.')


def carregar_entradas(projeto):
    """Confere a fila aprovada e os snapshots antes de montar qualquer chamada."""
    root = Path(projeto).resolve()
    folder = root / 'dados/processados/re'
    meta = json.loads((folder/'manifesto_planejamento_re.json').read_text(encoding='utf-8'))
    paths = {
        'prepared_csv': root/'dados/processados/noticias_preparadas.csv',
        'ner_documents_csv': root/'dados/processados/ner/consolidado/documentos_ner.csv',
        'ner_manifest': root/'dados/processados/ner/consolidado/manifesto.json',
        'mentions_pol_snapshot': root/'dados/processados/ner/consolidado/mencoes_pol.csv.gz',
    }
    for name, path in paths.items():
        if sha_file(path) != meta['inputs_sha256'][name]:
            raise ValueError(f'Entrada diferente do planejamento: {path.name}. Atualize o planejamento antes de executar.')
    queue_path = folder/'fila_re.csv'
    if sha_file(queue_path) != meta['outputs_sha256']['dados/processados/re/fila_re.csv']:
        raise ValueError('A fila difere do manifesto de planejamento.')
    if sha_file(root/'prompts/re_instrucoes.txt') != PROMPT_SHA256:
        raise ValueError('O prompt fixo difere do contrato.')
    queue = pd.read_csv(queue_path, dtype=str, keep_default_na=False)
    if queue.news_id.duplicated().any() or queue.planning_id.duplicated().any():
        raise ValueError('Identidades duplicadas na fila.')
    if not queue.re_action.eq('EXECUTAR_RE').all():
        raise ValueError('A fila inclui ações diferentes de EXECUTAR_RE.')
    years = pd.to_numeric(queue.publication_year, errors='raise')
    if not years.lt(2026).all():
        raise ValueError('Esta execução está limitada a publicações anteriores a 2026.')
    queue = queue.sort_values(['publication_year','publication_date','source','news_id'], kind='stable').reset_index(drop=True)
    news = pd.read_csv(paths['prepared_csv'], dtype=str, keep_default_na=False,
                       usecols=['news_id','news_version_id','title','full_text','link'])
    if news.news_id.duplicated().any():
        raise ValueError('news_id duplicado na base preparada.')
    news = news.set_index('news_id')
    mentions = pd.read_csv(paths['mentions_pol_snapshot'], dtype=str, keep_default_na=False,
                          usecols=['mention_id','news_id','news_version_id','ner_input_sha256','start','end','ent_text','ent_label'])
    mentions = mentions.loc[mentions.news_id.isin(set(queue.news_id))].copy()
    if mentions.mention_id.duplicated().any():
        raise ValueError('mention_id duplicado no snapshot NER.')
    groups = {k: v for k, v in mentions.groupby('news_id', sort=False)}
    prefix = (root/'prompts/re_instrucoes.txt').read_text(encoding='utf-8')
    return {'root': root, 'queue': queue, 'news': news, 'mentions': groups,
            'prefix': prefix, 'queue_sha256': sha_file(queue_path)}


def montar_requisicao(inputs, row, contract):
    news = inputs['news'].loc[row['news_id']]
    group = inputs['mentions'].get(row['news_id'])
    if group is None or len(group) < 2 or len(group) != int(row['mentions_pol']):
        raise ValueError('Contagem de menções incompatível com a fila: '+row['news_id'])
    if news.news_version_id != row['news_version_id'] or not group.news_version_id.eq(row['news_version_id']).all():
        raise ValueError('Versão documental incompatível: '+row['news_id'])
    if not group.ner_input_sha256.eq(row['ner_input_sha256']).all():
        raise ValueError('Snapshot das menções incompatível: '+row['news_id'])
    text = news.title.strip() + '\n\n' + news.full_text.strip()
    if digest(text) != row['ner_input_sha256']:
        raise ValueError('Texto de entrada diferente do NER: '+row['news_id'])
    # IDs de menção pertencem ao documento e permanecem independentes da resolução.
    group = group.assign(_start=pd.to_numeric(group.start), _end=pd.to_numeric(group.end))
    group = group.sort_values(['_start','_end','mention_id'], kind='stable')
    entities = [{'em_id': x.mention_id, 'mention_text': x.ent_text,
                 'categoria': x.ent_label} for x in group.itertuples()]
    if any(x['categoria'] not in {'PESSOA','ORGANIZACAO','LOCAL'} for x in entities):
        raise ValueError('Categoria não elegível para RE.')
    docid = row['news_id']
    prompt = (inputs['prefix']+'\nDOCUMENTO\nDOCID: '+docid+'\n\nTEXTO:\n'+text+
              '\n\nLISTA DE ENTIDADES\n'+json.dumps(entities, ensure_ascii=False, indent=2))
    identity = {'news_id': docid, 'news_version_id': row['news_version_id'],
                'ner_input_sha256': row['ner_input_sha256'], 'prompt_sha256': digest(prompt),
                'contract': contract}
    rid = digest(json.dumps(identity, sort_keys=True, ensure_ascii=False))
    return {'request_id': rid, 'identity': identity, 'prompt': prompt,
            'entities': entities, 'news': row}


def normalize_re_label(raw: Optional[str]) -> str:
    """
    Realiza normalização textual leve para rótulos de relação
    retornados pelo LLM.

    Esta função NÃO executa canonização metodológica completa.
    Seu objetivo é apenas estabilizar variações textuais e
    pequenas inconsistências sintáticas produzidas pelo modelo.

    Etapas aplicadas:
    - lowercase;
    - remoção de acentos;
    - substituição de hífen/espaço por underscore;
    - remoção de caracteres inválidos;
    - compactação de underscores múltiplos;
    - aplicação de aliases operacionais mínimos.

    A equivalência semântica/canônica entre rótulos deve ser
    tratada posteriormente via LABEL_EQUIV_CANON_EVAL.
    """
    s = str(raw or '').strip().lower()
    s = unicodedata.normalize('NFKD', s)
    s = ''.join((ch for ch in s if not unicodedata.combining(ch)))
    s = s.replace('-', '_').replace(' ', '_')
    s = re.sub('[^a-z0-9_]+', '_', s)
    s = re.sub('_+', '_', s).strip('_')
    aliases = {'nome_de_ident': 'nome_de', 'residente_em': 'residente_de'}
    return aliases.get(s, s)

def validar_resposta(raw, valid_ids, finish_reason=''):
    edges, audit = parse_llm_doclevel_relations_json(raw)
    accepted, rejected = [], []
    normalized_labels, seen = [], set()
    normalized_duplicates = 0
    for original_edge in edges:
        edge = dict(original_edge)
        raw_label = edge['label']
        edge['label'] = normalize_re_label(raw_label)
        if edge['label'] != raw_label:
            normalized_labels.append({'head_id': edge['head_id'], 'tail_id': edge['tail_id'],
                                      'label_raw': raw_label, 'label_normalized': edge['label']})
        reason = None
        if edge['head_id'] not in valid_ids or edge['tail_id'] not in valid_ids:
            reason = 'UNKNOWN_MENTION_ID'
        elif edge['head_id'] == edge['tail_id']:
            reason = 'SELF_RELATION'
        elif edge['label'] not in LABELS:
            reason = 'UNKNOWN_RELATION_LABEL'
        if reason:
            rejected.append(dict(edge, label_raw=raw_label, reason=reason))
        else:
            triple = (edge['head_id'], edge['tail_id'], edge['label'])
            if triple in seen:
                normalized_duplicates += 1
                continue
            seen.add(triple)
            accepted.append(edge)
    audit['normalizations'] = normalized_labels
    audit['normalized_duplicates'] = normalized_duplicates
    audit['validation_version'] = '1.1.0'
    audit['rejected'] = rejected
    audit['finish_reason'] = finish_reason
    interrupted = finish_reason not in {'', 'STOP', 'stop'}
    if not audit['parse_ok']:
        state = 'INVALID_RESPONSE'
    elif audit['partial_recovered'] or audit['items_invalid'] or rejected or interrupted:
        state = 'PARTIAL'
    else:
        state = 'SUCCESS' if accepted else 'SUCCESS_ZERO'
    return state, accepted, audit


def credenciais(path, provider):
    from dotenv import dotenv_values
    if not Path(path).is_file():
        raise FileNotFoundError('Não foi encontrado o .env na pasta do projeto.')
    values = dotenv_values(path, interpolate=False, encoding='utf-8-sig')
    variable = 'GEMINI_API_KEY' if provider == 'google' else 'DEEPINFRA_API_KEY'
    key = (values.get(variable) or '').strip()
    if not key or key.lower() in {'sua_chave_aqui', 'cole_sua_chave_aqui'}:
        raise ValueError('Defina '+variable+' no .env local.')
    name = ' '.join(re.sub(r'[^\w .@()/-]', ' ', values.get('KEY_NAME') or 'chave local').split())[:80]
    if key in name or key in (values.get('KEY_NAME') or ''):
        name = 'chave local'
    return key, name


def transporte_http(prompt, contract, key, timeout):
    """Uma chamada por tentativa; não repete automaticamente requisições pagas."""
    if contract['provider'] == 'google':
        url = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent'
        payload = {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
                   'generationConfig': {'temperature': 0, 'seed': 42, 'responseMimeType': 'application/json'}}
        headers = {'Content-Type': 'application/json', 'x-goog-api-key': key}
    else:
        url = 'https://api.deepinfra.com/v1/openai/chat/completions'
        payload = {'model': 'google/gemini-2.5-flash',
                   'messages': [{'role': 'user', 'content': prompt}], 'temperature': 0}
        headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer '+key}
    req = Request(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'), headers=headers, method='POST')
    try:
        with urlopen(req, timeout=timeout) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def extrair_payload(data, provider):
    if provider == 'google':
        candidate = (data.get('candidates') or [{}])[0]
        raw = ''.join(p.get('text','') for p in candidate.get('content',{}).get('parts',[]) if not p.get('thought'))
        return raw, candidate.get('finishReason',''), data.get('usageMetadata',{})
    choice = (data.get('choices') or [{}])[0]
    return choice.get('message',{}).get('content') or '', choice.get('finish_reason',''), data.get('usage',{})


def abrir_db(folder):
    path = folder/'checkpoint.sqlite3'
    if not path.exists() and (any((folder/'validacoes').glob('*.json')) or any((folder/'respostas').glob('*/*.json'))):
        raise ValueError('Respostas existentes sem checkpoint; restaure o checkpoint antes de executar.')
    db = sqlite3.connect(path)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=FULL')
    db.execute('CREATE TABLE IF NOT EXISTS requests (request_id TEXT PRIMARY KEY, news_id TEXT, state TEXT, attempt_id TEXT, updated_at TEXT)')
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='attempts'").fetchone():
        if db.execute('SELECT count(*) FROM requests').fetchone()[0]:
            backup = folder/'backups'/('checkpoint_antes_provedores_'+uuid.uuid4().hex+'.sqlite3')
            backup.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(backup) as dest:
                db.backup(dest)
        db.execute('CREATE TABLE attempts (attempt_id TEXT PRIMARY KEY, request_id TEXT, news_id TEXT, news_version_id TEXT, provider TEXT, model TEXT, state TEXT, updated_at TEXT, identity_json TEXT)')
        for rid,nid,state,attempt,stamp in db.execute('SELECT * FROM requests').fetchall():
            paths = [folder/'requisicoes'/(rid+'.json'), folder/'validacoes'/(rid+'.json'),
                     folder/'respostas'/rid/(attempt+'.json')]
            saved = next((json.loads(p.read_text(encoding='utf-8')) for p in paths if p.exists()), None)
            if saved is None:
                raise ValueError('Tentativa sem identidade persistida; confira os arquivos antes de continuar.')
            identity = saved['identity']; contract = identity['contract']
            db.execute('INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?,?)',
                       (attempt,rid,nid,identity['news_version_id'],contract['provider'],contract['model'],state,stamp,
                        json.dumps(identity,ensure_ascii=False,sort_keys=True)))
    db.commit()
    return db


def salvar_estado(db, req, state, attempt):
    stamp = agora(); identity = req['identity']; contract = identity['contract']
    with db:
        db.execute('INSERT OR REPLACE INTO requests VALUES (?,?,?,?,?)',
                   (req['request_id'], req['news']['news_id'], state, attempt, stamp))
        db.execute('INSERT OR REPLACE INTO attempts VALUES (?,?,?,?,?,?,?,?,?)',
                   (attempt,req['request_id'],req['news']['news_id'],identity['news_version_id'],
                    contract['provider'],contract['model'],state,stamp,
                    json.dumps(identity,ensure_ascii=False,sort_keys=True)))


def estados_ativos(db):
    # A fila é imutável: cada news_id corresponde a uma única versão documental.
    latest = {}
    for rid,nid,state,attempt,stamp in db.execute('SELECT * FROM requests ORDER BY updated_at,request_id'):
        if nid in latest and latest[nid][1] == 'RUNNING':
            raise ValueError('Mais de uma tentativa ativa para a mesma notícia; inspecione o checkpoint.')
        latest[nid] = (rid,state,attempt)
    return latest


def caminhos_validacoes_ativas(folder):
    """Seleciona uma validação por notícia, preservando as tentativas anteriores."""
    folder = Path(folder)
    paths = sorted((folder/'validacoes').glob('*.json'))
    if (folder/'checkpoint.sqlite3').exists():
        with sqlite3.connect(f'file:{(folder/"checkpoint.sqlite3").resolve().as_posix()}?mode=ro',uri=True) as db:
            active = estados_ativos(db)
        chosen = []
        for rid,state,attempt in active.values():
            if state in {'RUNNING','UNCERTAIN'}:
                continue
            path = folder/'validacoes'/(rid+'.json')
            if not path.exists():
                raise ValueError('Checkpoint confirmado sem validação correspondente.')
            item = json.loads(path.read_text(encoding='utf-8'))
            if item['attempt_id'] != attempt or item['state'] != state:
                raise ValueError('Checkpoint e validação incompatíveis.')
            chosen.append(path)
        return sorted(chosen)
    # Permite auditar pacotes de resultados que não incluem o SQLite.
    latest = {}
    for path in paths:
        item = json.loads(path.read_text(encoding='utf-8'))
        key = item['news']['news_id']; stamp = item['updated_at']
        if key in latest and stamp == latest[key][0]:
            raise ValueError('Tentativas documentais com ordenação ambígua.')
        if key not in latest or stamp > latest[key][0]:
            latest[key] = (stamp,path)
    return sorted(item[1] for item in latest.values())


def erro_chave_confirmado(folder, previous):
    rid,state,attempt = previous
    if state != 'HTTP_ERROR':
        return False
    path = folder/'respostas'/rid/(attempt+'.json')
    if not path.exists():
        return False
    env = json.loads(path.read_text(encoding='utf-8'))
    if env.get('request_id') != rid or env.get('attempt_id') != attempt or env.get('http_status') != 400:
        return False
    try:
        error = json.loads(env['body'])['error']
        return error.get('status') == 'INVALID_ARGUMENT' and any(
            d.get('reason') == 'API_KEY_INVALID' for d in error.get('details',[]) if isinstance(d,dict))
    except (ValueError,KeyError,TypeError,AttributeError):
        return False


def registrar_contrato(folder, inputs, contract):
    path = folder/'contrato.json'
    run = {'contract':contract,'queue_sha256':inputs['queue_sha256']}
    if not path.exists() and any((folder/'validacoes').glob('*.json')):
        raise ValueError('Contrato do checkpoint ausente; restaure o contrato antes de continuar.')
    if path.exists():
        previous = json.loads(path.read_text(encoding='utf-8'))
        old = previous.get('contract',{})
        if previous.get('queue_sha256') != inputs['queue_sha256'] or old != contrato(old.get('provider')):
            raise ValueError('A fila ou o contrato científico mudou; confira as entradas.')
    else:
        atomic_json(path,run)
    atomic_json(folder/'contratos'/(digest(json.dumps(contract,sort_keys=True))+'.json'),run)


def avaliar_envelope(req, env):
    if env['http_status'] != 200:
        return 'HTTP_ERROR', [], {'http_status': env['http_status']}
    try:
        data = json.loads(env['body'])
        raw, finish, usage = extrair_payload(data, req['identity']['contract']['provider'])
        state, edges, audit = validar_resposta(raw, {x['em_id'] for x in req['entities']}, finish)
        audit['usage'] = usage
        return state, edges, audit
    except (ValueError, TypeError, AttributeError, KeyError):
        return 'INVALID_RESPONSE', [], {'reason': 'API_ENVELOPE_INVALID'}


def chamada(req, contract, key, timeout, folder, attempt, transport):
    rid = req['request_id']
    log(rid, f'ENVIO — {contract["provider"]}; tentativa {attempt[:8]}; {req["news"]["publication_year"]}; {req["news"]["source"]}; {len(req["entities"])} menções; espera máxima {timeout}s.')
    start = time.monotonic()
    try:
        status, body = transport(req['prompt'], contract, key, timeout)
    except Exception as error:
        # Não inclui mensagens de exceção, que podem conter cabeçalhos ou URLs.
        log(rid, 'TRANSPORTE INCERTO — '+type(error).__name__+'; não haverá reenvio automático.')
        return {'uncertain': type(error).__name__, 'attempt_id': attempt, 'elapsed_s': time.monotonic()-start}
    body_text = body.decode('utf-8', errors='replace') if isinstance(body, bytes) else str(body)
    # Remove a credencial se um servidor a devolver inadvertidamente.
    body_text = body_text.replace(key, '[REDACTED]') if key else body_text
    env = {'request_id': rid, 'attempt_id': attempt, 'identity': req['identity'],
           'http_status': status, 'body': body_text, 'received_at': agora(),
           'elapsed_s': round(time.monotonic()-start, 3)}
    atomic_json(folder/'respostas'/rid/(attempt+'.json'), env)
    log(rid, f'RETORNO — HTTP {status}; {env["elapsed_s"]:.1f}s; resposta persistida.')
    return env


def gravar_resultado(req, env, folder, db):
    state, edges, audit = avaliar_envelope(req, env)
    result = {'request_id': req['request_id'], 'attempt_id': env['attempt_id'],
              'identity': req['identity'], 'news': req['news'], 'state': state,
              'relations': edges, 'audit': audit, 'http_status': env['http_status'],
              'elapsed_s': env['elapsed_s'], 'updated_at': agora()}
    atomic_json(folder/'historico_validacoes'/req['request_id']/(env['attempt_id']+'.json'), result)
    atomic_json(folder/'validacoes'/(req['request_id']+'.json'), result)
    salvar_estado(db, req, state, env['attempt_id'])
    log(req['request_id'], f'VALIDAÇÃO — {state}; {len(edges)} relações; {len(audit.get("rejected", []))} rejeições.')
    return result


def executar(inputs, *, executar_api=False, limite=1, trabalhadores=1, provider='google',
             timeout=360, transport=None, anos=None, retentar_requisicoes=None):
    """Avança somente pedidos ainda não tentados; respostas pendentes são recuperadas."""
    if not isinstance(limite, int) or isinstance(limite, bool) or limite < 1:
        raise ValueError('O limite deve ser um inteiro positivo.')
    if not isinstance(trabalhadores, int) or not 1 <= trabalhadores <= 10:
        raise ValueError('Use entre 1 e 10 trabalhadores.')
    if not 1 <= timeout <= 1800:
        raise ValueError('O timeout deve estar entre 1 e 1800 segundos.')
    contract = contrato(provider)
    if retentar_requisicoes is None:
        retentar_requisicoes = []
    if not isinstance(retentar_requisicoes,(list,tuple,set)) or any(
            not isinstance(rid,str) or not re.fullmatch('[0-9a-f]{64}',rid) for rid in retentar_requisicoes):
        raise ValueError('retentar_requisicoes deve conter identificadores completos de requisições.')
    retry_ids = set(retentar_requisicoes)
    if anos is None:
        selected_years = None
        queue_selected = inputs['queue']
    else:
        if not isinstance(anos, (list, tuple, set, range)) or not anos:
            raise ValueError('anos deve ser uma coleção não vazia de anos inteiros, ou None.')
        if any(not isinstance(year, int) or isinstance(year, bool) or not 1 <= year < 2026 for year in anos):
            raise ValueError('Selecione apenas anos inteiros anteriores a 2026.')
        selected_years = sorted(set(anos))
        queue_selected = inputs['queue'].loc[
            pd.to_numeric(inputs['queue']['publication_year']).isin(selected_years)]
    period = 'todos os anos da fila' if selected_years is None else ', '.join(map(str, selected_years))
    folder = inputs['root']/'dados/processados/re/execucao'
    # No modo de conferência nem o .env nem o checkpoint são alterados.
    if not executar_api:
        previews = []
        active_news = {}
        if (folder/'checkpoint.sqlite3').exists():
            with sqlite3.connect(f'file:{(folder/"checkpoint.sqlite3").resolve().as_posix()}?mode=ro',uri=True) as db:
                active_news = estados_ativos(db)
        for row in queue_selected.to_dict('records'):
            previous = active_news.get(row['news_id'])
            if previous and (previous[0] not in retry_ids or not erro_chave_confirmado(folder,previous)):
                continue
            req = montar_requisicao(inputs, row, contract)
            previews.append({'news_id': row['news_id'], 'request_id': req['request_id'],
                             'year': row['publication_year'], 'source': row['source'],
                             'mentions': len(req['entities']), 'prompt_characters': len(req['prompt'])})
            if len(previews) >= limite:
                break
        print(f'[RE] CONFERÊNCIA LOCAL — {len(inputs["queue"]):,} notícias na fila; nenhuma conexão de rede; provedor selecionado: {provider}.')
        print(f'[RE] RECORTE — {period}; {len(queue_selected):,} notícias selecionadas antes de descontar tentativas anteriores.')
        return {'mode': 'DRY_RUN', 'api_calls': 0, 'selected_years': selected_years, 'selected_news': len(queue_selected), 'preview': previews}
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder/'execucao.lock'
    try:
        lock.mkdir()
    except FileExistsError:
        raise RuntimeError('Outra execução pode estar ativa. Não execute dois kernels sobre o mesmo checkpoint. Consulte as instruções sobre o bloqueio.') from None
    db = None
    try:
        atomic_json(lock/'owner.json', {'pid': os.getpid(), 'started_at': agora()})
        db = abrir_db(folder)
        registrar_contrato(folder, inputs, contract)
        active_news = estados_ativos(db)
        known_ids = {r[0] for r in db.execute('SELECT request_id FROM requests')}
        if retry_ids - known_ids:
            raise ValueError('Autorização de nova tentativa refere-se a uma requisição desconhecida.')
        selected, recovered = [], 0
        for row in queue_selected.to_dict('records'):
            previous = active_news.get(row['news_id'])
            if previous:
                rid,state,attempt = previous
                saved_path = folder/'requisicoes'/(rid+'.json')
                if not saved_path.exists():
                    raise ValueError('Requisição anterior ausente; restaure o arquivo antes de continuar.')
                saved = json.loads(saved_path.read_text(encoding='utf-8'))
                identity = saved['identity']
                if identity['news_version_id'] != row['news_version_id'] or identity['ner_input_sha256'] != row['ner_input_sha256']:
                    raise ValueError('A versão documental mudou em relação ao checkpoint.')
                if state == 'RUNNING':
                    oldreq = montar_requisicao(inputs,row,identity['contract'])
                    if oldreq['request_id'] != rid or oldreq['identity'] != identity:
                        raise ValueError('Identidade da tentativa em curso incompatível.')
                    response = folder/'respostas'/rid/(attempt+'.json')
                    if response.exists():
                        env = json.loads(response.read_text(encoding='utf-8'))
                        if env['request_id'] != rid or env['identity'] != identity or env['attempt_id'] != attempt:
                            raise ValueError('Resposta incompatível com a requisição.')
                        gravar_resultado(oldreq,env,folder,db)
                        recovered += 1
                    else:
                        salvar_estado(db,oldreq,'UNCERTAIN',attempt)
                    continue
                if rid not in retry_ids or not erro_chave_confirmado(folder,previous):
                    continue
            req = montar_requisicao(inputs,row,contract)
            if previous and req['identity']['prompt_sha256'] != identity['prompt_sha256']:
                raise ValueError('O prompt ou as menções mudaram desde a tentativa anterior.')
            selected.append(req)
            if len(selected) >= limite:
                break
        if not selected:
            print('[RE] Nenhuma requisição inédita no recorte. Outros anos não serão iniciados; consulte progresso_re.csv para pendências de revisão.')
            summary = {'mode':'EXECUTION','api_calls':0,'recovered_without_call':recovered,
                       'states_this_run':{},'selected_years':selected_years,'selected_news':len(queue_selected),
                       'paused':False,'finished_at':agora()}
            atomic_json(folder/'ultimo_lote.json',summary)
            exportar(inputs, folder)
            return summary
        if transport is None:
            key, alias = credenciais(inputs['root']/'.env', provider)
        else:
            key, alias = '', 'transporte de teste'
        print(f'[RE] EXECUÇÃO — apelido: {alias}; provedor: {provider}; modelo: {contract["model"]}; limite: {limite}; trabalhadores: {trabalhadores}.', flush=True)
        print(f'[RE] RECORTE — {period}; {len(selected)} chamadas novas selecionadas.', flush=True)
        counts, calls, consecutive_failures, stop = Counter(), 0, 0, False
        iterator = iter(selected)
        with ThreadPoolExecutor(max_workers=trabalhadores) as pool:
            active = {}
            def submit_next():
                nonlocal calls
                req = next(iterator, None)
                if req is None:
                    return
                attempt = uuid.uuid4().hex
                previous_validation = folder/'validacoes'/(req['request_id']+'.json')
                if previous_validation.exists():
                    old = json.loads(previous_validation.read_text(encoding='utf-8'))
                    atomic_json(folder/'historico_validacoes'/req['request_id']/(old['attempt_id']+'.json'),old)
                atomic_json(folder/'requisicoes'/(req['request_id']+'.json'),
                            {'identity':req['identity'], 'entities':req['entities'], 'news':req['news']})
                prompt_path = folder/'prompts'/(req['request_id']+'.txt')
                prompt_path.parent.mkdir(parents=True, exist_ok=True)
                prompt_path.write_text(req['prompt'], encoding='utf-8', newline='\n')
                salvar_estado(db, req, 'RUNNING', attempt)
                future = pool.submit(chamada, req, contract, key, timeout, folder, attempt, transport or transporte_http)
                active[future] = req
                calls += 1
            for _ in range(min(trabalhadores,len(selected))):
                submit_next()
            while active:
                ready, _ = wait(active, return_when=FIRST_COMPLETED)
                # Primeiro avalia todas as respostas prontas; depois repõe vagas.
                for future in ready:
                    req = active.pop(future)
                    env = future.result()
                    if 'uncertain' in env:
                        salvar_estado(db, req, 'UNCERTAIN', env['attempt_id'])
                        state = 'UNCERTAIN'
                        consecutive_failures += 1
                    else:
                        result = gravar_resultado(req, env, folder, db)
                        state = result['state']
                        status = env['http_status']
                        consecutive_failures = consecutive_failures + 1 if status != 200 else 0
                        if status in {400,401,402,403,404,429}:
                            stop = True
                            print(f'[RE] PAUSA — HTTP {status}; não serão iniciados novos envios. As requisições em curso serão preservadas.', flush=True)
                    if consecutive_failures >= 3:
                        stop = True
                        print('[RE] PAUSA — três falhas consecutivas de transporte/HTTP.', flush=True)
                    counts[state] += 1
                if not stop:
                    for _ in range(trabalhadores-len(active)):
                        submit_next()
        summary = {'mode':'EXECUTION','api_calls':calls,'recovered_without_call':recovered,
                   'states_this_run':dict(counts),'provider':provider,'model':contract['model'],'paused':stop,'selected_years':selected_years,
                   'selected_news':len(queue_selected),'finished_at':agora()}
        atomic_json(folder/'ultimo_lote.json',summary)
        exportar(inputs, folder)
        print('[RE] LOTE ENCERRADO — '+json.dumps(summary, ensure_ascii=False), flush=True)
        return summary
    finally:
        if db is not None:
            db.close()
        (lock/'owner.json').unlink(missing_ok=True)
        lock.rmdir()


def exportar(inputs, folder=None):
    """Gera tabelas e um pacote sem .env, credenciais, textos integrais ou prompts."""
    folder = Path(folder or inputs['root']/'dados/processados/re/execucao')
    table_dir = inputs['root']/'resultados/tabelas/re'
    table_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for path in caminhos_validacoes_ativas(folder):
        results.append(json.loads(path.read_text(encoding='utf-8')))
    progress = inputs['queue'][['planning_id','news_id','publication_year','source','re_processing_type']].copy()
    progress['state'] = 'PENDING'
    if (folder/'checkpoint.sqlite3').exists():
        with sqlite3.connect(folder/'checkpoint.sqlite3') as db:
            states = {nid:value[1] for nid,value in estados_ativos(db).items()}
            attempts = pd.read_sql_query('SELECT * FROM attempts ORDER BY updated_at,attempt_id',db)
        attempts.to_csv(table_dir/'tentativas_re.csv',index=False,encoding='utf-8-sig')
        progress['state'] = progress.news_id.map(states).fillna('PENDING')
    progress.to_csv(table_dir/'progresso_re.csv',index=False,encoding='utf-8-sig')
    rows = []
    for result in results:
        for edge in result['relations']:
            rows.append({'request_id':result['request_id'], 'news_id':result['news']['news_id'],
                         'news_version_id':result['news']['news_version_id'],
                         'publication_year':result['news']['publication_year'], 'source':result['news']['source'],
                         **edge, 'state':result['state'],
                         'ner_availability': result['news']['ner_availability'],
                         'provider':result['identity']['contract']['provider'],
                         'model':result['identity']['contract']['model'], 'attempt_id':result['attempt_id'],
                         'provisional':result['state'] not in TERMINAIS})
    columns = ['request_id','news_id','news_version_id','publication_year','source','head_id','tail_id','label','state','ner_availability','provider','model','attempt_id','provisional']
    pd.DataFrame(rows,columns=columns).to_csv(table_dir/'relacoes_extraidas.csv.gz',index=False,compression='gzip')
    by_year = progress.groupby(['publication_year','state'],dropna=False).size().reset_index(name='news')
    by_year.to_csv(table_dir/'progresso_re_por_ano.csv',index=False,encoding='utf-8-sig')
    print('Progresso na fila anterior a 2026:')
    print(progress.groupby('state').size().rename('noticias').to_string())
    exports = inputs['root']/'resultados/re'
    exports.mkdir(parents=True,exist_ok=True)
    dest = exports/('Resumo_RE_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]+'.zip')
    with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as z:
        for path in sorted(table_dir.glob('*')):
            if path.is_file():
                z.write(path,'tabelas/'+path.name)
        for name in ['contrato.json','ultimo_lote.json']:
            path = folder/name
            if path.exists(): z.write(path,name)
        for category in ['validacoes','historico_validacoes','contratos']:
            for path in sorted((folder/category).rglob('*.json')):
                z.write(path,str(path.relative_to(folder)))
        # Respostas permitem auditar o parse, mas prompts/textos de entrada não são incluídos.
        for path in sorted((folder/'respostas').glob('*/*.json')):
            z.write(path,'respostas/'+path.parent.name+'/'+path.name)
    print('Pacote de verificação:',dest)
    return dest
