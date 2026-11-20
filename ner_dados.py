"""Consolidação e leitura de tabelas NER com proveniência e validação local.

Nenhuma função deste módulo acessa serviços externos. Os intervalos são
[start, end), em caracteres Unicode do título e corpo separados por duas quebras.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import contextmanager
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import zipfile

ROTULOS = frozenset('PESSOA ORGANIZACAO LOCAL TEMPO ACONTECIMENTO OBRA VALOR COISA ABSTRACCAO OUTRO'.split())
POL = frozenset(('PESSOA', 'ORGANIZACAO', 'LOCAL'))
COLUNAS = 'mention_id news_id news_version_id ner_input_sha256 source link publication_date start end ent_text ent_label model origin source_mention_id source_news_id source_file source_publication_date original_label original_surface original_start original_end alignment_action'.split()
DOC_COLUNAS = 'news_id news_version_id ner_input_sha256 source link title publication_date year availability execution_state input_source completion_basis request_id response_truncated alignment_issues mentions_all mentions_pol'.split()


def sha_arquivo(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def texto_ner(row):
    return '\n\n'.join(x for x in (row['title'].strip(), row['full_text'].strip()) if x)


@contextmanager
def abrir_csv(path, mode='rt'):
    path = Path(path)
    if path.suffix == '.gz' and mode == 'wt':
        # Mesmo conteúdo produz os mesmos bytes comprimidos.
        with path.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as gz, io.TextIOWrapper(gz, encoding='utf-8-sig', newline='') as f:
            yield f
    else:
        op = gzip.open if path.suffix == '.gz' else open
        with op(path, mode, encoding='utf-8-sig', newline='') as f:
            yield f


def linhas(path):
    with abrir_csv(path) as f:
        yield from csv.DictReader(f)


def gravar_csv(path, fields, rows):
    with abrir_csv(path, 'wt') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='raise')
        writer.writeheader()
        writer.writerows(rows)


def carregar_base(path):
    base = {}
    for row in linhas(path):
        nid = row['news_id']
        if nid in base:
            raise ValueError('news_id repetido na base: ' + nid)
        text = texto_ner(row)
        base[nid] = dict(news_id=nid, news_version_id=row['news_version_id'],
                         ner_input_sha256=hashlib.sha256(text.encode()).hexdigest(),
                         source=row['source_normalized'], link=row['link'], title=row['title'],
                         publication_date=row['publication_date_normalized'], year=row['publication_year'],
                         text=text)
    return base


def assinatura_base(base):
    h = hashlib.sha256()
    fields = ('news_id', 'news_version_id', 'ner_input_sha256', 'source', 'link', 'publication_date', 'year')
    for nid in sorted(base):
        h.update((json.dumps([base[nid][k] for k in fields], ensure_ascii=False, separators=(',', ':')) + '\n').encode())
    return h.hexdigest()


def normalizar_exportacao(arquivo, destino):
    """Converte uma exportação do executor em fonte tabular independente.

    Apenas documentos efetivamente tentados entram nesta fonte. Os estados
    importados exibidos na cobertura não são apresentados como novas inferências.
    """
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(arquivo) as z:
        summary = json.loads(z.read('resumo_execucao_ner.json'))
        coverage = csv.DictReader(io.StringIO(z.read('cobertura_atualizada.csv').decode('utf-8-sig')))
        states = {r['request_id']: r for r in csv.DictReader(io.StringIO(z.read('status_requisicoes.csv').decode('utf-8-sig')))}
        documents = []
        for row in coverage:
            state = states.get(row['request_id'], {})
            if not int(state.get('attempts', 0)):
                continue
            effective = state['state']
            availability = 'AVAILABLE' if effective in {'SUCCESS', 'SUCCESS_EMPTY'} else 'PARTIAL' if effective == 'PARTIAL' else 'UNAVAILABLE'
            documents.append({**{k: row[k] for k in ('news_id', 'news_version_id', 'ner_input_sha256')},
                              'availability': availability, 'execution_state': effective,
                              'completion_basis': 'executor_validation', 'request_id': row['request_id'],
                              'response_truncated': row.get('response_truncated', 'False'),
                              'alignment_issues': row.get('alignment_issues', '0')})
        fields = ['news_id', 'news_version_id', 'ner_input_sha256', 'availability', 'execution_state',
                  'completion_basis', 'request_id', 'response_truncated', 'alignment_issues']
        gravar_csv(destino / 'documentos.csv', fields, documents)
        for name in ('mencoes_todas_execucao.csv.gz', 'mencoes_parciais.csv.gz'):
            (destino / name).write_bytes(z.read(name))
        for name in ('pendencias_alinhamento.csv', 'respostas_interrompidas.csv', 'status_requisicoes.csv'):
            (destino / name).write_bytes(z.read(name))
    return dict(id='execution_' + sha_arquivo(arquivo)[:12], documentos=str(destino / 'documentos.csv'),
                mencoes=[str(destino / 'mencoes_todas_execucao.csv.gz'), str(destino / 'mencoes_parciais.csv.gz')],
                provenance={'kind': 'execution_export', 'file': Path(arquivo).name, 'sha256': sha_arquivo(arquivo),
                            'contract': summary['contract'], 'exported_at_utc': summary['created_at_utc'],
                            'attempts_recorded': summary['attempts_recorded']},
                auditorias=[str(destino / name) for name in ('pendencias_alinhamento.csv', 'respostas_interrompidas.csv', 'status_requisicoes.csv')])


def consolidar(base_path, fontes, destino):
    """Une fontes disjuntas, preservando campos originais e rejeitando conflitos.

    Cada fonte descreve documentos e menções no esquema documentado. Uma notícia
    não pode ter duas fontes: substituir resultados exige uma seleção explícita.
    O destino precisa ser novo para preservar snapshots anteriores.
    """
    destino = Path(destino)
    if destino.exists():
        raise FileExistsError('Preserve o snapshot existente; escolha outro destino: ' + str(destino))
    base = carregar_base(base_path)
    docs = {nid: {**{k: v for k, v in row.items() if k != 'text'},
                  'availability': 'NOT_PROCESSED', 'execution_state': 'NOT_ATTEMPTED',
                  'input_source': '', 'completion_basis': '', 'request_id': '',
                  'response_truncated': 'False', 'alignment_issues': '0', 'mentions_all': 0, 'mentions_pol': 0}
            for nid, row in base.items()}
    if len({f['id'] for f in fontes}) != len(fontes):
        raise ValueError('Identificadores de fontes repetidos.')
    input_records = []
    for source in fontes:
        for row in linhas(source['documentos']):
            nid = row['news_id']
            if nid not in docs:
                raise ValueError('Documento ausente da base: ' + nid)
            doc = docs[nid]
            if doc['input_source']:
                raise ValueError('Fontes sobrepostas; selecione explicitamente o resultado: ' + nid)
            for key in ('news_version_id', 'ner_input_sha256'):
                if row[key] != doc[key]:
                    raise ValueError('Versão ou texto incompatível: ' + nid)
            if row['availability'] not in {'AVAILABLE', 'PARTIAL', 'UNAVAILABLE'}:
                raise ValueError('Disponibilidade inválida: ' + nid)
            doc.update({k: row.get(k, doc[k]) for k in ('availability', 'execution_state', 'completion_basis', 'request_id', 'response_truncated', 'alignment_issues')})
            doc['input_source'] = source['id']
        files = [source['documentos']] + source['mencoes'] + source.get('auditorias', [])
        input_records.append(dict(id=source['id'], provenance=source['provenance'],
                                  files=[{'file': Path(p).name, 'sha256': sha_arquivo(p)} for p in files]))
    destino.parent.mkdir(parents=True, exist_ok=True)
    ids = set()
    counts = Counter()
    with tempfile.TemporaryDirectory(dir=destino.parent, prefix='.ner-') as temp:
        stage = Path(temp)
        with abrir_csv(stage / 'mencoes_todas.csv.gz', 'wt') as full, abrir_csv(stage / 'mencoes_pol.csv.gz', 'wt') as pol:
            fw = csv.DictWriter(full, COLUNAS); pw = csv.DictWriter(pol, COLUNAS)
            fw.writeheader(); pw.writeheader()
            for source in fontes:
                for path in source['mencoes']:
                    for row in linhas(path):
                        if set(row) != set(COLUNAS):
                            raise ValueError('Esquema de menções incompatível: ' + str(path))
                        nid = row['news_id']
                        if nid not in docs or docs[nid]['input_source'] != source['id']:
                            raise ValueError('Menção sem vínculo com a fonte documental: ' + nid)
                        doc = docs[nid]
                        if doc['availability'] not in {'AVAILABLE', 'PARTIAL'}:
                            raise ValueError('Menção em documento sem resultado: ' + nid)
                        for key in ('news_version_id', 'ner_input_sha256', 'source', 'link', 'publication_date'):
                            if row[key] != doc[key]:
                                raise ValueError('Metadado divergente: ' + key + ' / ' + nid)
                        start, end = int(row['start']), int(row['end'])
                        label = row['ent_label']
                        if label not in ROTULOS or not 0 <= start < end <= len(base[nid]['text']):
                            raise ValueError('Rótulo ou intervalo inválido: ' + row['mention_id'])
                        if base[nid]['text'][start:end] != row['ent_text']:
                            raise ValueError('Superfície incompatível com o texto: ' + row['mention_id'])
                        expected = hashlib.sha256(json.dumps([nid, label, start, end, row['ent_text']], ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
                        if row['mention_id'] != expected or expected in ids:
                            raise ValueError('Identificador inválido ou repetido: ' + expected)
                        ids.add(expected)
                        fw.writerow(row); doc['mentions_all'] += 1
                        if label in POL:
                            pw.writerow(row); doc['mentions_pol'] += 1
                        counts[(doc['source'], doc['year'], doc['availability'], label)] += 1
        gravar_csv(stage / 'documentos_ner.csv', DOC_COLUNAS, [docs[nid] for nid in sorted(docs)])
        gravar_csv(stage / 'documentos_para_revisao.csv', DOC_COLUNAS,
                   [docs[nid] for nid in sorted(docs) if docs[nid]['availability'] in {'PARTIAL', 'UNAVAILABLE'}])
        gravar_csv(stage / 'mencoes_fonte_ano_categoria.csv', ['source', 'year', 'availability', 'ent_label', 'mentions'],
                   [dict(zip(['source', 'year', 'availability', 'ent_label', 'mentions'], (*key, val))) for key, val in sorted(counts.items())])
        coverage = Counter((r['source'], r['year'], r['availability'], r['execution_state']) for r in docs.values())
        gravar_csv(stage / 'cobertura_fonte_ano.csv', ['source', 'year', 'availability', 'execution_state', 'news'],
                   [dict(zip(['source', 'year', 'availability', 'execution_state', 'news'], (*key, val))) for key, val in sorted(coverage.items())])
        for source in fontes:
            for path in source.get('auditorias', []):
                target = stage / (source['id'] + '_' + Path(path).name)
                target.write_bytes(Path(path).read_bytes())
        manifest = dict(schema_version='ner-dataset-1', base_logical_sha256=assinatura_base(base),
                        base_csv_sha256=sha_arquivo(base_path), news_total=len(docs),
                        availability=dict(Counter(r['availability'] for r in docs.values())),
                        execution_states=dict(Counter(r['execution_state'] for r in docs.values())),
                        mentions_all=sum(r['mentions_all'] for r in docs.values()),
                        mentions_pol=sum(r['mentions_pol'] for r in docs.values()),
                        label_counts=dict(Counter({label: sum(v for k, v in counts.items() if k[3] == label) for label in sorted(ROTULOS)})),
                        sources=input_records,
                        policies={'partial_mentions': 'retained_with_document_status',
                                  'automatic_text_exclusion': False, 'automatic_date_correction': False,
                                  'imported_completeness': 'not_inferred_from_alignment',
                                  'alignment_validation': 'literal_surface_not_semantic_accuracy'},
                        outputs={p.name: sha_arquivo(p) for p in sorted(stage.iterdir())})
        (stage / 'manifesto.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        # Renomeação única no mesmo volume: o destino fica visível somente completo.
        stage.rename(destino)
    return manifest


def carregar_consolidado(destino, base_path=None):
    """Verifica hashes e cobertura; a comparação da base usa conteúdo lógico.

    Diferenças de quebras de linha ou de serialização CSV não invalidam uma base
    com as mesmas identidades, versões e textos de entrada.
    """
    destino = Path(destino)
    meta = json.loads((destino / 'manifesto.json').read_text(encoding='utf-8'))
    if meta['schema_version'] != 'ner-dataset-1':
        raise ValueError('Versão de esquema não suportada.')
    for name, expected in meta['outputs'].items():
        if Path(name).name != name or sha_arquivo(destino / name) != expected:
            raise ValueError('Arquivo ausente, alterado ou incompleto: ' + name)
    docs = list(linhas(destino / 'documentos_ner.csv'))
    if len(docs) != meta['news_total'] or len({r['news_id'] for r in docs}) != len(docs):
        raise ValueError('Cobertura documental inválida.')
    if dict(Counter(r['availability'] for r in docs)) != meta['availability']:
        raise ValueError('Disponibilidade divergente do manifesto.')
    for key in ('mentions_all', 'mentions_pol'):
        if sum(int(r[key]) for r in docs) != meta[key]:
            raise ValueError('Contagem divergente: ' + key)
    if base_path is not None and assinatura_base(carregar_base(base_path)) != meta['base_logical_sha256']:
        raise ValueError('A base lógica mudou; é necessária nova validação das fontes NER.')
    return docs, meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True, type=Path)
    parser.add_argument('--exportacao', required=True, type=Path)
    parser.add_argument('--destino', required=True, type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temp:
        source = normalizar_exportacao(args.exportacao, Path(temp) / 'fonte')
        meta = consolidar(args.base, [source], args.destino)
    print(json.dumps({k: meta[k] for k in ('news_total', 'availability', 'mentions_all', 'mentions_pol')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
