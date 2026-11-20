"""Importação documental auditada de relações para o esquema de menções atual."""
from pathlib import Path
import json, zipfile, io, hashlib, sys, unicodedata, gzip
from collections import Counter
import pandas as pd
import argparse
parser = argparse.ArgumentParser(description='Prepara importação RE documentada, com remapeamento bijetivo de menções; sem chamadas à API.')
parser.add_argument('--projeto', type=Path, required=True)
parser.add_argument('--fontes', type=Path, required=True, help='Pasta com a auditoria, prompts e exportações documentais referenciadas.')
parser.add_argument('--destino', type=Path, required=True, help='Nova pasta de saída, ainda inexistente.')
args = parser.parse_args()
root = args.projeto.resolve()
sys.path.insert(0, str(root))
import re_execucao as re
inputs = args.fontes.resolve()
out = args.destino.resolve()
if out.exists():
    raise FileExistsError('Preserve a importação existente e escolha outra pasta de destino.')
out.mkdir(parents=True)
audit = zipfile.ZipFile(inputs / 'Auditoria_Compatibilidade_RE.zip')
provenance = json.loads(audit.read('proveniencia.json'))
for name in ['Prompts_Antigos_RE_20261116_054851_619593.zip', 'prompts_by_doc.zip', 'Relacoes_para_auditoria_20261115_224044_540176.zip', 'B_emFiltered.extracted_relations.raw.csv']:
    if not re.sha_file(inputs / name) == provenance['input_sha256'][name]:
        raise ValueError(name)
pdocs = pd.read_csv(io.BytesIO(audit.read('prompts_documentos.csv')), dtype=str, keep_default_na=False)
pdocs = pdocs.loc[pdocs.data_compatible.eq('True')].copy()
if not (pdocs.news_id.is_unique and len(pdocs) > 0):
    raise ValueError('Falha de consistência na importação documentada.')
coverage = pd.read_csv(io.BytesIO(audit.read('fila_preliminar_re.csv')), dtype=str, keep_default_na=False)
base = pd.read_csv(root / 'dados/processados/noticias_preparadas.csv', dtype=str, keep_default_na=False, usecols=['news_id', 'news_version_id', 'title', 'full_text', 'source_normalized', 'publication_year', 'link']).set_index('news_id')
mentions = pd.read_csv(root / 'dados/processados/ner/consolidado/mencoes_pol.csv.gz', dtype=str, keep_default_na=False, usecols=['news_id', 'mention_id', 'source_mention_id', 'ent_text', 'ent_label', 'start', 'end', 'news_version_id', 'ner_input_sha256'])
if not re.sha_file(root / 'dados/processados/ner/consolidado/mencoes_pol.csv.gz') == provenance['input_sha256']['mencoes_pol.csv.gz']:
    raise ValueError('Falha de consistência na importação documentada.')
groups = {nid: g for nid, g in mentions.groupby('news_id', sort=False)}
cols = ['docid', 'E1_id', 'E2_id', 'relation_label', 'llm_provider', 'llm_model_name', 'prompt_id', 'news_link']
zraw = zipfile.ZipFile(inputs / 'Relacoes_para_auditoria_20261115_224044_540176.zip')
rawgroups = {}
for name in zraw.namelist():
    if name.endswith('.extracted_relations.raw.csv'):
        frame = pd.read_csv(io.BytesIO(zraw.read(name)), dtype=str, keep_default_na=False, usecols=cols)
        for docid, g in frame.groupby('docid', sort=False):
            rawgroups['old', name.split('/')[0], docid] = g
frame = pd.read_csv(inputs / 'B_emFiltered.extracted_relations.raw.csv', dtype=str, keep_default_na=False, usecols=cols)
for docid, g in frame.groupby('docid', sort=False):
    rawgroups['sample', '', docid] = g
zp = {'old': zipfile.ZipFile(inputs / 'Prompts_Antigos_RE_20261116_054851_619593.zip'), 'sample': zipfile.ZipFile(inputs / 'prompts_by_doc.zip')}
sample_names = {Path(n).name: n for n in zp['sample'].namelist() if n.endswith('.prompt.txt')}
relations = []
documents = []
mappingrows = []
duplicates = 0
norm = lambda s: s.replace('\r\n', '\n').replace('\r', '\n')
for i, a in enumerate(pdocs.itertuples(index=False)):
    prompt_path = a.path if a.collection == 'old' else sample_names[Path(a.path).name]
    prompt = zp[a.collection].read(prompt_path).decode('utf-8-sig').replace('\r\n', '\n')
    prefix, document = prompt.split('\nDOCUMENTO\n', 1)
    text, serialized = document.split('\n\nTEXTO:\n', 1)[1].rsplit('\n\nLISTA DE ENTIDADES\n', 1)
    if not re.digest(prefix) == a.prefix_sha256:
        raise ValueError(('prefix', a.docid))
    current = base.loc[a.news_id]
    currenttext = current.title.strip() + '\n\n' + current.full_text.strip()
    if not norm(text) == norm(currenttext):
        raise ValueError(('text', a.docid))
    entities = json.loads(serialized)
    g = groups[a.news_id]
    if not len(entities) == len(g) == int(a.current_entities):
        raise ValueError('Falha de consistência na importação documentada.')
    source = {}
    for m in g.itertuples(index=False):
        source.setdefault(m.source_mention_id, []).append(m)
    mapped = {}
    entitydict = {}
    for ent in entities:
        oldid = str(ent['em_id'])
        candidates = source.get(oldid, [])
        if not len(candidates) == 1:
            raise ValueError(('map', a.docid, oldid))
        m = candidates[0]
        if not (ent['mention_text'] == m.ent_text and ent['categoria'] == m.ent_label):
            raise ValueError(('surface', a.docid, oldid))
        mapped[oldid] = m.mention_id
        entitydict[m.mention_id] = {'mention_text': m.ent_text, 'categoria': m.ent_label}
        mappingrows.append({'news_id': a.news_id, 'source_document_id': a.docid, 'source_mention_id': oldid, 'mention_id': m.mention_id})
    if not len(set(mapped.values())) == len(mapped):
        raise ValueError('Falha de consistência na importação documentada.')
    raw = rawgroups.get((a.collection, a.folder if a.collection == 'old' else '', a.docid), pd.DataFrame(columns=cols))
    if not len(raw) == int(a.raw_rows) == int(a.declared_raw_relations):
        raise ValueError((a.docid, len(raw), a.raw_rows, a.declared_raw_relations))
    seen = set()
    for e in raw.itertuples(index=False):
        edge = {'head_id': mapped[e.E1_id], 'tail_id': mapped[e.E2_id], 'label': re.normalize_re_label(e.relation_label)}
        if not (edge['head_id'] != edge['tail_id'] and edge['label'] in re.LABELS):
            raise ValueError((a.docid, edge))
        key = tuple(edge.values())
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        relations.append({'news_id': a.news_id, 'news_version_id': current.news_version_id, **edge, 'provider': e.llm_provider, 'model': e.llm_model_name, 'source_document_id': a.docid, 'source_collection': a.collection, 'source_location': a.folder, 'instruction_sha256': a.prefix_sha256, 'instruction_variant': a.canonical_instructions != 'True', 'ner_availability': a.availability, 'ner_input_sha256': re.digest(currenttext), 'head_surface': entitydict[edge['head_id']]['mention_text'], 'tail_surface': entitydict[edge['tail_id']]['mention_text'], 'head_type': entitydict[edge['head_id']]['categoria'], 'tail_type': entitydict[edge['tail_id']]['categoria']})
    documents.append({'news_id': a.news_id, 'news_version_id': current.news_version_id, 'source_document_id': a.docid, 'source_collection': a.collection, 'source_location': a.folder, 'state': 'SUCCESS_ZERO' if not seen else 'SUCCESS', 'relations': len(seen), 'instruction_sha256': a.prefix_sha256, 'instruction_variant': a.canonical_instructions != 'True', 'ner_availability': a.availability, 'ner_input_sha256': re.digest(currenttext)})
    if (i + 1) % 2000 == 0:
        print('Importação conferida:', i + 1, flush=True)
for name, records in [('relacoes_importadas.csv.gz', relations), ('documentos_importados.csv.gz', documents), ('mapa_mencoes_importadas.csv.gz', mappingrows)]:
    with (out / name).open('wb') as f:
        with gzip.GzipFile(fileobj=f, mode='wb', mtime=0, filename='') as gz:
            pd.DataFrame(records).to_csv(gz, index=False, encoding='utf-8', lineterminator='\n')
coverage[['news_id', 'news_version_id', 'ner_availability', 'mentions_pol']].to_csv(out / 'cobertura_ner.csv', index=False, encoding='utf-8', lineterminator='\n')
manifest = {'schema': 're-import-1', 'selection_policy': 'DATA_COMPATIBLE_WITH_DOCUMENTED_INSTRUCTION_VARIANT', 'scientific_accuracy_validated': False, 'api_calls': 0, 'documents': len(documents), 'relations': len(relations), 'duplicates_removed': duplicates, 'canonical_documents': int(pdocs.canonical_instructions.eq('True').sum()), 'instruction_variant_documents': int(pdocs.canonical_instructions.ne('True').sum()), 'mention_mapping': 'Bijective source_mention_id matching within news_id; exact surface and category; complete prompt entity scope.', 'inputs_sha256': provenance['input_sha256'], 'outputs_sha256': {f.name: re.sha_file(f) for f in out.iterdir()}, 'limitations': ['Automated extraction; no corpus-wide manual semantic validation.', 'Compatibility allows line-ending normalization in source texts.', 'Documented instruction-format variant retained under approved reuse policy.']}
re.atomic_json(out / 'manifesto.json', manifest)
print('IMPORTACAO', json.dumps({k: v for k, v in manifest.items() if k not in ['inputs_sha256', 'outputs_sha256']}, ensure_ascii=False))
