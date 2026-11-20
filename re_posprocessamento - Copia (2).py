"""Revalidação e auditoria de relações persistidas, sem chamadas de inferência."""
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
import shutil
import tempfile
import uuid
import zipfile
import pandas as pd
import re_execucao
import re_parser

VERSION = '1.0.0'


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _text_sha(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def _json_sha(data):
    return _text_sha(json.dumps(data,sort_keys=True,ensure_ascii=False))


def _subsequencia(small, large):
    iterator = iter(large)
    return all(any(c == wanted for c in iterator) for wanted in small)


def _candidatos(identifier, entities):
    """Sugestões por omissão de até quatro caracteres; nunca são aplicadas aqui."""
    return [key for key in sorted(entities)
            if 1 <= len(key)-len(identifier) <= 4 and _subsequencia(identifier,key)]


def _alertas(edge, entities):
    head, tail = entities[edge['head_id']], entities[edge['tail_id']]
    issues = []
    if edge['label']=='vinculo_inst' and {head['categoria'],tail['categoria']}!={'PESSOA','ORGANIZACAO'}:
        issues.append('VINCULO_PAIR_TYPES')
    if edge['label']=='ocorre_em' and tail['categoria']!='LOCAL':
        issues.append('OCORRE_DESTINATION_NOT_LOCAL')
    if edge['label']=='ident' and head['categoria']!=tail['categoria']:
        issues.append('IDENT_DIFFERENT_NER_TYPES')
    return issues


def _ler_prompt(prompt, identity):
    if _text_sha(prompt) != identity['prompt_sha256']:
        raise ValueError('O prompt salvo não corresponde à identidade da requisição.')
    prefix, document = prompt.split('\nDOCUMENTO\n',1)
    if _text_sha(prefix) != identity['contract']['prompt_sha256']:
        raise ValueError('Instruções fixas incompatíveis com o contrato.')
    doc, text_block = document.split('\n\nTEXTO:\n',1)
    if doc != 'DOCID: '+identity['news_id']:
        raise ValueError('DOCID incompatível com a identidade documental.')
    # A lista é o último bloco do formato; títulos/textos podem conter marcadores.
    text, serialized = text_block.rsplit('\n\nLISTA DE ENTIDADES\n',1)
    if _text_sha(text) != identity['ner_input_sha256']:
        raise ValueError('Texto do prompt incompatível com a entrada NER.')
    items = json.loads(serialized)
    if not isinstance(items,list) or not all(isinstance(x,dict) for x in items):
        raise ValueError('Lista de entidades inválida.')
    entities = {x['em_id']:x for x in items}
    if len(entities) != len(items) or not entities:
        raise ValueError('IDs de entidades duplicados ou ausentes.')
    if any(not isinstance(k,str) or not k or x.get('categoria') not in {'PESSOA','ORGANIZACAO','LOCAL'}
           or not isinstance(x.get('mention_text'),str) for k,x in entities.items()):
        raise ValueError('Entidades fora do esquema elegível.')
    return entities


def _mapas_aprovados(data):
    result = {}
    for record in data.get('mappings',[]):
        if record.get('decision')!='APPROVED':
            continue
        required = ['request_id','news_id','prompt_sha256','old_id','new_id','surface','review_basis']
        if any(not isinstance(record.get(k),str) or not record[k] for k in required):
            raise ValueError('Correção aprovada sem identidade ou justificativa completa.')
        key = (record['request_id'],record['old_id'])
        if key in result:
            raise ValueError('Correções duplicadas para o mesmo ID e requisição.')
        result[key] = record
    return result


def _revalidar_documento(original, envelope, prompt, approved):
    """Retorna uma camada derivada; não altera os objetos recebidos."""
    rid, identity = original['request_id'], original['identity']
    if _json_sha(identity) != rid:
        raise ValueError('Identidade da requisição não corresponde ao seu hash.')
    if envelope['request_id']!=rid or envelope['identity']!=identity or envelope['attempt_id']!=original['attempt_id']:
        raise ValueError('Resposta e validação pertencem a requisições diferentes.')
    if original['news']['news_id']!=identity['news_id'] or original['news']['news_version_id']!=identity['news_version_id']:
        raise ValueError('Metadados documentais incompatíveis.')
    entities = _ler_prompt(prompt,identity)
    if len(entities)!=int(original['news']['mentions_pol']):
        raise ValueError('Contagem de entidades diferente do registro de execução.')
    repairs, candidates = [], []
    if envelope['http_status']!=200:
        return {'state':'HTTP_ERROR','relations':[],'audit':{'http_status':envelope['http_status']},
                'entities':entities,'repairs':repairs,'candidates':candidates,'used_maps':[]}
    try:
        payload = json.loads(envelope['body'])
        raw, finish, usage = re_execucao.extrair_payload(payload,identity['contract']['provider'])
        if not isinstance(raw,str):
            raise ValueError('Conteúdo textual inválido no envelope.')
    except (ValueError,TypeError,KeyError,AttributeError):
        return {'state':'INVALID_RESPONSE','relations':[],'audit':{'reason':'API_ENVELOPE_INVALID'},
                'entities':entities,'repairs':repairs,'candidates':candidates,'used_maps':[]}
    baseline_state, baseline_edges, baseline_audit = re_execucao.validar_resposta(raw,set(entities),finish)
    if baseline_state!=original['state'] or baseline_edges!=original['relations']:
        raise ValueError('A validação original não é reproduzida pelo validador instalado. Confira a versão do executor.')
    items, parse_audit = re_parser.parse_llm_doclevel_relations_json(raw)
    corrected = []
    used = set()
    unknown = set()
    for index, item in enumerate(items):
        edge = dict(item)
        for endpoint in ['head_id','tail_id']:
            old_id = item[endpoint]
            if old_id in entities:
                continue
            decision = approved.get((rid,old_id))
            if decision:
                if decision['news_id']!=identity['news_id'] or decision['prompt_sha256']!=identity['prompt_sha256']:
                    raise ValueError('Correção aprovada para outra versão documental ou prompt.')
                target = decision['new_id']
                if target not in entities or entities[target]['mention_text']!=decision['surface']:
                    raise ValueError('Destino da correção não pertence às menções do prompt.')
                edge[endpoint] = target
                used.add((rid,old_id))
                repairs.append({'request_id':rid,'news_id':identity['news_id'],'item_index':index,
                    'endpoint':endpoint,'old_id':old_id,'new_id':target,'surface':decision['surface'],
                    'review_basis':decision['review_basis'],'prompt_sha256':identity['prompt_sha256']})
            else:
                unknown.add(old_id)
        corrected.append(edge)
    for identifier in sorted(unknown):
        matches = _candidatos(identifier,entities)
        if matches:
            for target in matches:
                candidates.append({'request_id':rid,'news_id':identity['news_id'],'unknown_id':identifier,
                    'candidate_id':target,'surface':entities[target]['mention_text'],
                    'candidate_count':len(matches),'status':'REVIEW_REQUIRED_NOT_APPLIED',
                    'criterion':'SUBSEQUENCE_UP_TO_4_OMISSIONS'})
        else:
            candidates.append({'request_id':rid,'news_id':identity['news_id'],'unknown_id':identifier,
                'candidate_id':'','surface':'','candidate_count':0,'status':'UNRESOLVED_NOT_APPLIED',
                'criterion':'NO_SUBSEQUENCE_CANDIDATE'})
    state, edges, audit = re_execucao.validar_resposta(json.dumps(corrected,ensure_ascii=False),set(entities),finish)
    # Serializar fragmentos recuperados não transforma uma resposta incompleta em completa.
    if not parse_audit['parse_ok']:
        state = 'INVALID_RESPONSE'
        edges = []
    elif parse_audit['partial_recovered'] or parse_audit['items_invalid']:
        state = 'PARTIAL'
    audit['original_parse'] = parse_audit
    audit['usage'] = usage
    audit['postprocessing_version'] = VERSION
    return {'state':state,'relations':edges,'audit':audit,'entities':entities,
            'repairs':repairs,'candidates':candidates,'used_maps':sorted(used)}


def _csv(folder,name,rows,columns,compression=None):
    path = folder/name
    if compression=='gzip':
        compression={'method':'gzip','mtime':0}
    pd.DataFrame(rows,columns=columns).to_csv(path,index=False,encoding='utf-8-sig',
                                          compression=compression,lineterminator='\n')


def _resumo_zip(root,folder):
    export = root/'resultados/re'
    export.mkdir(parents=True,exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
    path = export/('Resumo_Pos_RE_'+stamp+'.zip')
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for f in sorted(folder.iterdir()):
            if f.is_file():z.write(f,f.name)
    return path


def processar_re(projeto=None, *, arquivo_correcoes=None):
    """Revalida respostas locais com correções explícitas e alertas não destrutivos."""
    root = Path(projeto or Path.cwd()).resolve()
    source = root/'dados/processados/re/execucao'
    if (source/'execucao.lock').exists():
        raise RuntimeError('Aguarde o encerramento da execução RE antes de gerar o snapshot derivado.')
    validations = re_execucao.caminhos_validacoes_ativas(source)
    if not validations:
        raise FileNotFoundError('Nenhuma validação RE encontrada.')
    corrections_path = Path(arquivo_correcoes) if arquivo_correcoes is not None else root/'dados/processados/re/curadoria/correcoes_ids_aprovadas.json'
    corrections = json.loads(corrections_path.read_text(encoding='utf-8-sig')) if corrections_path.exists() else {'mappings':[]}
    approved = _mapas_aprovados(corrections)
    inputs = {}
    def register(path):
        relative = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
        inputs[relative] = {'path':path,'sha256':_sha(path)}
        return relative
    if corrections_path.exists():register(corrections_path)
    for path in [Path(__file__).resolve(),Path(re_execucao.__file__).resolve(),Path(re_parser.__file__).resolve()]:
        register(path)
    documents, relations, flags, repairs, candidates, rejections, audits = [], [], [], [], [], [], []
    used_maps = set()
    original_states = Counter()
    original_count = 0
    seen_news, seen_rids = set(), set()
    for path in validations:
        register(path)
        original = json.loads(path.read_text(encoding='utf-8'))
        rid, attempt = original['request_id'],original['attempt_id']
        # Apenas nomes hexadecimais podem formar caminhos de respostas.
        if path.stem!=rid or len(rid)!=64 or any(c not in '0123456789abcdef' for c in rid+attempt):
            raise ValueError('Nome ou identificador de requisição inválido.')
        if not attempt or original['news']['news_id'] in seen_news or rid in seen_rids:
            raise ValueError('Identidades documentais duplicadas ou tentativa ausente.')
        seen_news.add(original['news']['news_id']);seen_rids.add(rid)
        response_path = source/'respostas'/rid/(attempt+'.json')
        prompt_path = source/'prompts'/(rid+'.txt')
        register(response_path);register(prompt_path)
        envelope = json.loads(response_path.read_text(encoding='utf-8'))
        prompt = prompt_path.read_text(encoding='utf-8-sig')
        doc = _revalidar_documento(original,envelope,prompt,approved)
        audits.append({'request_id':rid,'attempt_id':attempt,'original_execution_state':original['state'],
                       'revalidation_state':doc['state'],'audit':doc['audit']})
        original_states[original['state']] += 1
        original_count += len(original['relations'])
        repairs.extend(doc['repairs']);candidates.extend(doc['candidates']);used_maps.update(map(tuple,doc['used_maps']))
        metadata = {'request_id':rid,'news_id':original['news']['news_id'],
            'news_version_id':original['news']['news_version_id'],'publication_year':original['news']['publication_year'],
            'source':original['news']['source'],'title':original['news']['title'],'link':original['news']['link'],
            'provider':original['identity']['contract']['provider'], 'model':original['identity']['contract']['model'],
            'attempt_id':attempt}
        nflags = 0
        for edge in doc['relations']:
            head, tail = doc['entities'][edge['head_id']],doc['entities'][edge['tail_id']]
            issues = _alertas(edge,doc['entities'])
            nflags += bool(issues)
            relation_id = _json_sha([rid,edge['head_id'],edge['tail_id'],edge['label']])
            row = {**metadata,'relation_id':relation_id,**edge,
                'head_surface':head['mention_text'],'tail_surface':tail['mention_text'],
                'head_type':head['categoria'],'tail_type':tail['categoria'],
                'original_execution_state':original['state'],'revalidation_state':doc['state'],
                'ner_availability':original['news']['ner_availability'],
                'technical_provisional':doc['state'] not in {'SUCCESS','SUCCESS_ZERO'},
                'semantic_status':'REVIEW_PENDING' if issues else 'NOT_REVIEWED',
                'semantic_flags':'|'.join(issues)}
            relations.append(row)
            if issues:
                flags.append({**row,'decision':'','replacement_label':'','reviewer':'','justification':''})
        for rejection in doc['audit'].get('rejected',[]):
            rejections.append({**metadata,'head_id':rejection['head_id'],'tail_id':rejection['tail_id'],
                              'label':rejection['label'],'reason':rejection['reason']})
        documents.append({**metadata,'original_execution_state':original['state'],'revalidation_state':doc['state'],
            'original_relations':len(original['relations']),'derived_relations':len(doc['relations']),
            'repaired_endpoints':len(doc['repairs']),'flagged_relations':nflags,
            'remaining_rejections':len(doc['audit'].get('rejected',[])),
            'semantic_status':'REVIEW_PENDING' if nflags else 'NOT_REVIEWED',
            'original_partial_parse':bool(doc['audit'].get('original_parse',{}).get('partial_recovered',False))})
    # Os arquivos de origem precisam manter a mesma versão durante a leitura.
    if (source/'execucao.lock').exists() or validations!=re_execucao.caminhos_validacoes_ativas(source):
        raise RuntimeError('A execução RE mudou durante o pós-processamento. Aguarde e repita.')
    for entry in inputs.values():
        if _sha(entry['path'])!=entry['sha256']:
            raise ValueError('Uma entrada mudou durante a leitura; nenhum resultado será publicado.')
    hashes = {key:value['sha256'] for key,value in sorted(inputs.items())}
    signature = _json_sha({'version':VERSION,'inputs':hashes})
    folder = root/'dados/processados/re/posprocessado'/signature[:20]
    manifest_path = folder/'manifesto.json'
    if folder.exists():
        if not manifest_path.exists():raise ValueError('Pasta derivada sem manifesto.')
        manifest = json.loads(manifest_path.read_text())
        if manifest['snapshot_sha256']!=signature:raise ValueError('Colisão de identidade do snapshot.')
        for name,expected in manifest['outputs_sha256'].items():
            if _sha(folder/name)!=expected:raise ValueError('Saída derivada modificada. Preserve a edição separadamente antes de regenerar.')
        print('[PÓS-RE] Snapshot existente conferido; nenhuma relação foi duplicada.')
    else:
        folder.parent.mkdir(parents=True,exist_ok=True)
        temp = Path(tempfile.mkdtemp(prefix='.preparando_',dir=folder.parent))
        try:
            mcols=['request_id','news_id','news_version_id','publication_year','source','title','link','provider','model','attempt_id']
            rcols=mcols+['relation_id','head_id','tail_id','label','head_surface','tail_surface','head_type','tail_type',
                'original_execution_state','revalidation_state','ner_availability','technical_provisional','semantic_status','semantic_flags']
            _csv(temp,'relacoes_posprocessadas.csv.gz',relations,rcols,'gzip')
            _csv(temp,'inspecao_relacoes.csv',flags,rcols+['decision','replacement_label','reviewer','justification'])
            _csv(temp,'documentos_revalidados.csv',documents,mcols+['original_execution_state','revalidation_state',
                'original_relations','derived_relations','repaired_endpoints','flagged_relations','remaining_rejections',
                'semantic_status','original_partial_parse'])
            _csv(temp,'correcoes_ids_aplicadas.csv',repairs,['request_id','news_id','item_index','endpoint','old_id','new_id','surface','review_basis','prompt_sha256'])
            _csv(temp,'candidatos_ids_inspecao.csv',candidates,['request_id','news_id','unknown_id','candidate_id','surface','candidate_count','status','criterion'])
            _csv(temp,'rejeicoes_restantes.csv',rejections,mcols+['head_id','tail_id','label','reason'])
            with (temp/'auditorias_revalidacao.jsonl').open('w',encoding='utf-8') as f:
                for record in audits:
                    f.write(json.dumps(record,ensure_ascii=False)+'\n')
            summary = {'documents':len(documents),'original_relations':original_count,'derived_relations':len(relations),
                'recovered_relations_net':len(relations)-original_count,'approved_id_mappings_used':len(used_maps),
                'repaired_endpoint_occurrences':len(repairs),'original_states':dict(original_states),
                'revalidation_states':dict(Counter(x['revalidation_state'] for x in documents)),
                'flagged_relations':len(flags),'candidate_rows_for_review':len(candidates),
                'remaining_rejections':len(rejections),'semantically_auto_approved':0,'api_calls':0}
            manifest = {'postprocessing_version':VERSION,'snapshot_sha256':signature,
                'created_at':datetime.now(timezone.utc).isoformat(),'inputs_sha256':hashes,
                'unused_approved_mappings':[{'request_id':k[0],'old_id':k[1]} for k in sorted(set(approved)-used_maps)],
                'summary':summary,'outputs_sha256':{p.name:_sha(p) for p in sorted(temp.iterdir())}}
            (temp/'manifesto.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            os.rename(temp,folder)
        finally:
            if temp.exists():shutil.rmtree(temp)
    package = _resumo_zip(root,folder)
    print('[PÓS-RE] '+json.dumps(manifest['summary'],ensure_ascii=False))
    print('[PÓS-RE] Saídas:',folder)
    print('[PÓS-RE] Pacote de verificação:',package)
    return {**manifest['summary'],'output_directory':folder,'package':package}
