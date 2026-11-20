"""Redes dirigidas multirrelacionais com proveniência documental e pesos de frequência."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import json
import os
import shutil
import tempfile
import time
import uuid
import zipfile
import pandas as pd
from entidades_integracao import carregar_entidades_integradas
from re_consolidacao import carregar_consolidado_re, sha, json_sha, write_csv, validate_manifest
from re_execucao import atomic_json

VERSION = '1.0.0'
SOURCE_NAMES = ('CNN Brasil', 'Folha de S.Paulo', 'Folha de S. Paulo', 'G1')
RELATION_MACRO = {
    'inclui': 'inclusao', 'incluido': 'inclusao',
    'ocorre_em': 'localizacao', 'sede_de': 'localizacao',
    **{k: 'outra' for k in ('vinculo_inst', 'autor_de', 'obra_de', 'relacao_familiar',
        'local_nascimento_de', 'natural_de', 'propriedade_de', 'proprietario_de',
        'produtor_de', 'produzido_por')},
    'ident': 'identidade',
}
NEWS_COLUMNS = ['news_id', 'news_version_id', 'title', 'link', 'author', 'source_normalized',
    'publication_date_normalized', 'publication_date_precision', 'publication_year',
    'category_raw', 'category_grouped', 'category_mapping_status']
MENTION_COLUMNS = ['mention_id', 'news_id', 'news_version_id', 'entity_group_id',
    'entity_group_name', 'ent_label', 'ent_text', 'entity_review_required',
    'entity_resolution_status', 'entity_quality_status']
REL_COLUMNS = ['relation_id', 'news_id', 'news_version_id', 'head_id', 'tail_id', 'label',
    'head_entity_id', 'tail_entity_id', 'technical_provisional', 'semantic_status',
    'semantic_flags', 'resolution_flags', 'entity_review_required']


def _read(path, columns=None):
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=columns)


def _boolean(series):
    if not series.isin(['True', 'False', 'true', 'false', '0', '1', '']).all():
        raise ValueError('Indicador booleano fora do esquema.')
    return series.isin(['True', 'true', '1'])


def _counts(frame, key, value, column):
    return frame.groupby(key, sort=True)[value].nunique().rename(column).reset_index()


def _distribution(frame, key, prefix):
    rows = []
    for dimension in ['publication_year', 'source', 'category_grouped']:
        part = frame.groupby([key, dimension], dropna=False, sort=True).agg(
            distinct_news_count=('news_id', 'nunique'),
            count=(prefix, 'sum')).reset_index()
        part = part.rename(columns={dimension: 'value'})
        part.insert(1, 'dimension', dimension)
        rows.append(part)
    return pd.concat(rows, ignore_index=True)


def agregar_tabelas(news, mentions, registry, relations, coverage):
    """Agrega um recorte já selecionado; mantém referências às evidências originais."""
    news, mentions, registry, relations = (x.copy() for x in [news, mentions, registry, relations])
    if news.source.eq('').any():
        raise ValueError('Fonte documental ausente.')
    if not news.news_id.is_unique or not registry.entity_group_id.is_unique:
        raise ValueError('Notícia ou grupo duplicado.')
    if not mentions.mention_id.is_unique or not relations.relation_id.is_unique:
        raise ValueError('Menção ou relação duplicada.')
    if not coverage.news_id.is_unique:
        raise ValueError('Cobertura documental duplicada.')
    if not set(news.news_id).issubset(set(coverage.news_id)):
        raise ValueError('Notícias sem registro de cobertura RE.')
    for frame in [mentions, relations]:
        check = frame[['news_id', 'news_version_id']].drop_duplicates().merge(
            news[['news_id', 'news_version_id']], on='news_id', how='left',
            suffixes=('', '_base'), validate='many_to_one')
        if not check.news_version_id.eq(check.news_version_id_base).all():
            raise ValueError('Evidência ausente da base ou versão documental incompatível.')
    c = coverage[['news_id', 'news_version_id', 'ner_availability', 're_state', 'origin', 'technical_provisional']]
    news = news.merge(c, on=['news_id', 'news_version_id'], how='left', validate='one_to_one')
    if news.re_state.isna().any():
        raise ValueError('Versão da cobertura incompatível com a base.')
    if not relations.label.isin(RELATION_MACRO).all():
        raise ValueError('Rótulo de relação sem macrocategoria documentada.')
    ids = set(registry.entity_group_id)
    if not set(mentions.entity_group_id).issubset(ids) or not (
            set(relations.head_entity_id) | set(relations.tail_entity_id)).issubset(ids):
        raise ValueError('Grupo ausente do catálogo.')
    # As exclusões usam IDs de grupos localizados por nome canônico e tipo.
    sources = registry.loc[registry.entity_group_name.isin(SOURCE_NAMES)
                           & registry.ent_label.eq('ORGANIZACAO')].copy()
    excluded_ids = set(sources.entity_group_id)
    relations['excluded_identity'] = relations.label.eq('ident')
    relations['excluded_self_loop'] = relations.head_entity_id.eq(relations.tail_entity_id)
    relations['excluded_corpus_source'] = (relations.head_entity_id.isin(excluded_ids)
                                          | relations.tail_entity_id.isin(excluded_ids))
    relations['exclusion_reason'] = ''
    for col, reason in [('excluded_identity', 'IDENTITY'), ('excluded_self_loop', 'SELF_LOOP'),
                        ('excluded_corpus_source', 'CORPUS_SOURCE')]:
        mask = relations[col] & relations.exclusion_reason.eq('')
        relations.loc[mask, 'exclusion_reason'] = reason
    exclusions = relations.loc[relations.exclusion_reason.ne('')].copy()
    evidence = relations.loc[relations.exclusion_reason.eq('')].copy()
    if evidence.empty:
        raise ValueError('O recorte não contém relações utilizáveis após os filtros.')
    evidence['edge_id'] = [json_sha(['semantic-edge-v1', a, b, label])
        for a, b, label in zip(evidence.head_entity_id, evidence.tail_entity_id, evidence.label)]
    evidence['relation_macro'] = evidence.label.map(RELATION_MACRO)
    evidence['review_record'] = _boolean(evidence.entity_review_required).astype('int64')
    evidence['provisional_record'] = _boolean(evidence.technical_provisional).astype('int64')
    evidence['semantic_flag_record'] = evidence.semantic_flags.ne('').astype('int64')
    support = evidence.groupby(['edge_id', 'news_id', 'news_version_id'], sort=True).agg(
        occurrence_count=('relation_id', 'size'), review_records=('review_record', 'sum'),
        provisional_records=('provisional_record', 'sum'),
        semantic_flag_records=('semantic_flag_record', 'sum')).reset_index()
    support = support.merge(news[['news_id', 'source', 'publication_year', 'category_grouped',
        'publication_date']], on='news_id', validate='many_to_one')
    edges = evidence.groupby(['edge_id', 'head_entity_id', 'tail_entity_id', 'label', 'relation_macro'],
        sort=True).agg(weight=('relation_id', 'size'), review_records=('review_record', 'sum'),
        provisional_records=('provisional_record', 'sum'),
        semantic_flag_records=('semantic_flag_record', 'sum')).reset_index().rename(
            columns={'head_entity_id': 'source_id', 'tail_entity_id': 'target_id'})
    support['_first_date'] = support.publication_date.replace('', '9999-12-31')
    edge_stats = support.groupby('edge_id', sort=True).agg(
        distinct_news_count=('news_id', 'nunique'),
        distinct_source_count=('source', 'nunique'),
        first_observed_date=('_first_date', 'min'),
        last_observed_date=('publication_date', 'max')).reset_index()
    edge_stats['first_observed_date'] = edge_stats.first_observed_date.replace('9999-12-31', '')
    support = support.drop(columns='_first_date')
    edges = edges.merge(edge_stats, on='edge_id', validate='one_to_one')
    node_ids = set(edges.source_id) | set(edges.target_id)
    m = mentions.loc[mentions.entity_group_id.isin(node_ids)].copy()
    m['review_record'] = _boolean(m.entity_review_required).astype('int64')
    node_news = m.groupby(['entity_group_id', 'news_id', 'news_version_id'], sort=True).agg(
        mention_count=('mention_id', 'size'), review_mentions=('review_record', 'sum')).reset_index()
    parts = pd.concat([evidence[['head_entity_id', 'news_id']].rename(columns={'head_entity_id': 'entity_group_id'}),
        evidence[['tail_entity_id', 'news_id']].rename(columns={'tail_entity_id': 'entity_group_id'})], ignore_index=True)
    participation = parts.groupby(['entity_group_id', 'news_id'], sort=True).size().rename(
        'relation_participation_count').reset_index()
    missing = participation.merge(node_news[['entity_group_id', 'news_id']], how='left',
        on=['entity_group_id', 'news_id'], indicator=True)
    if missing['_merge'].ne('both').any():
        raise ValueError('Participação em relação sem menção correspondente no documento.')
    node_news = node_news.merge(participation, on=['entity_group_id', 'news_id'], how='left', validate='one_to_one')
    node_news['relation_participation_count'] = node_news.relation_participation_count.fillna(0).astype('int64')
    node_news = node_news.merge(news[['news_id', 'source', 'publication_year', 'category_grouped',
        'publication_date', 'ner_availability', 're_state']], on='news_id', validate='many_to_one')
    nodes = registry.loc[registry.entity_group_id.isin(node_ids),
        ['entity_group_id', 'entity_group_name', 'ent_label']].copy()
    node_news['_first_date'] = node_news.publication_date.replace('', '9999-12-31')
    stats = node_news.groupby('entity_group_id', sort=True).agg(
        mention_count=('mention_count', 'sum'), distinct_news_count=('news_id', 'nunique'),
        review_mentions=('review_mentions', 'sum'),
        distinct_source_count=('source', 'nunique'),
        first_observed_date=('_first_date', 'min'),
        last_observed_date=('publication_date', 'max')).reset_index()
    stats['first_observed_date'] = stats.first_observed_date.replace('9999-12-31', '')
    node_news = node_news.drop(columns='_first_date')
    nodes = nodes.merge(stats, on='entity_group_id', validate='one_to_one')
    linked_news = _counts(node_news.loc[node_news.relation_participation_count.gt(0)],
        'entity_group_id', 'news_id', 'relation_news_count')
    nodes = nodes.merge(linked_news, on='entity_group_id', how='left', validate='one_to_one')
    if nodes.relation_news_count.isna().any():
        raise ValueError('Nó sem participação em relação utilizada.')
    nodes['relation_news_count'] = nodes.relation_news_count.astype('int64')
    nodes['entity_review_required'] = nodes.review_mentions.gt(0)
    quality = m.groupby(['entity_group_id', 'entity_resolution_status', 'entity_quality_status'], sort=True).agg(
        mention_count=('mention_id', 'size'), distinct_news_count=('news_id', 'nunique')).reset_index()
    forms = m.groupby(['entity_group_id', 'ent_text'], sort=True).agg(
        mention_count=('mention_id', 'size'), distinct_news_count=('news_id', 'nunique')).reset_index()
    if not edges.edge_id.is_unique or edges[['source_id', 'target_id', 'label']].duplicated().any():
        raise ValueError('Aresta agregada duplicada.')
    if edges.source_id.eq(edges.target_id).any() or edges.label.eq('ident').any() or node_ids & excluded_ids:
        raise ValueError('Uma exclusão obrigatória permaneceu na rede.')
    if int(edges.weight.sum()) != len(evidence) or int(support.occurrence_count.sum()) != len(evidence):
        raise ValueError('Peso ou suporte documental não preserva os registros utilizados.')
    if (edges.distinct_news_count > edges.weight).any():
        raise ValueError('Suporte documental maior que o peso.')
    if len(evidence) + len(exclusions) != len(relations):
        raise ValueError('Partição de registros incompleta.')
    summary = {'input_relations': len(relations), 'used_relations': len(evidence),
        'excluded_relations': len(exclusions), 'exclusive_exclusion_reasons': dict(Counter(exclusions.exclusion_reason)),
        'nodes': len(nodes), 'edges': len(edges), 'weight_sum': int(edges.weight.sum()),
        'support_news': int(support.news_id.nunique()), 'selected_news': len(news),
        'excluded_source_groups': len(sources), 'directed': True, 'multirelational': True,
        'self_loops': 0, 'identity_edges': 0, 'api_calls': 0, 'inferred_relations_added': 0}
    return {
        'nos.csv.gz': nodes.sort_values('entity_group_id'),
        'arestas.csv.gz': edges,
        'noticias.csv.gz': news,
        'nos_noticias.csv.gz': node_news,
        'arestas_noticias.csv.gz': support,
        'evidencias_relacoes.csv.gz': evidence,
        'relacoes_excluidas.csv.gz': exclusions,
        'variantes_entidades.csv.gz': forms,
        'qualidade_nos.csv.gz': quality,
        'distribuicoes_nos.csv.gz': _distribution(node_news, 'entity_group_id', 'mention_count'),
        'distribuicoes_arestas.csv.gz': _distribution(support, 'edge_id', 'occurrence_count'),
        'grupos_fontes_excluidos.csv': sources,
        'cobertura_por_ano_fonte.csv': news.groupby(['publication_year', 'source', 're_state'],
            dropna=False, sort=True).size().rename('news_count').reset_index(),
    }, summary


def construir_rede(projeto, *, anos=None, fontes=None, assinatura_entidades_esperada=None):
    """Cria uma versão imutável da rede; entradas alteradas geram outra versão."""
    root = Path(projeto).resolve(); started = time.monotonic()
    integrated, parent = carregar_entidades_integradas(root)
    if assinatura_entidades_esperada and parent['snapshot_sha256'] != assinatura_entidades_esperada:
        raise ValueError('A integração selecionada difere da versão esperada para esta edição.')
    if anos is not None and (not isinstance(anos, (list, tuple, set, range)) or not anos
            or any(not isinstance(x, int) or isinstance(x, bool) for x in anos)):
        raise ValueError('Informe uma coleção não vazia de anos inteiros ou None.')
    if fontes is not None and (not isinstance(fontes, (list, tuple, set)) or not fontes
            or any(not isinstance(x, str) or not x for x in fontes)):
        raise ValueError('Informe uma coleção não vazia de nomes de fontes ou None.')
    re_folder, re_meta = carregar_consolidado_re(root)
    prepared = root/'dados/processados/noticias_preparadas.csv'
    input_hashes = {str(prepared.relative_to(root)): sha(prepared),
        str((re_folder/'cobertura_documental.csv').relative_to(root)): sha(re_folder/'cobertura_documental.csv')}
    spec = {'schema': 'semantic-network-1', 'version': VERSION,
        'entity_snapshot_sha256': parent['snapshot_sha256'],
        're_snapshot_sha256': re_meta['snapshot_sha256'], 'inputs_sha256': input_hashes,
        'years': sorted(set(anos)) if anos is not None else None,
        'sources': sorted(set(fontes)) if fontes is not None else None,
        'excluded_source_names': SOURCE_NAMES, 'weight_definition': 'relation_record_count',
        'node_universe': 'endpoints_of_used_relations', 'code_sha256': sha(Path(__file__))}
    signature = json_sha(spec)
    base = root/'dados/processados/redes/instancias';base.mkdir(parents=True, exist_ok=True)
    target = base/signature[:20]; lock = base/'construcao.lock'
    try: lock.mkdir()
    except FileExistsError: raise RuntimeError('Outra construção pode estar ativa; confira o bloqueio.') from None
    staging = None
    try:
        if target.exists():
            validate_manifest(target)
        else:
            news = _read(prepared, NEWS_COLUMNS).rename(columns={
                'source_normalized': 'source', 'publication_date_normalized': 'publication_date'})
            if anos is not None:news = news.loc[news.publication_year.isin(list(map(str, anos)))].copy()
            if fontes is not None:news = news.loc[news.source.isin(fontes)].copy()
            if news.empty:raise ValueError('O recorte não contém notícias.')
            # Datas representam observação no corpus, não nascimento ou duração da entidade.
            news['publication_date_original'] = news.publication_date
            valid_day = pd.to_datetime(news.publication_date.str[:10], format='%Y-%m-%d', errors='coerce')
            news['publication_date'] = valid_day.dt.strftime('%Y-%m-%d').fillna('')
            chosen = set(news.news_id)
            mentions = _read(integrated/'mencoes_resolvidas.csv.gz', MENTION_COLUMNS)
            mentions = mentions.loc[mentions.news_id.isin(chosen)].copy()
            registry = _read(integrated/'entidades.csv.gz')
            relations = _read(integrated/'relacoes_resolvidas.csv.gz', REL_COLUMNS)
            relations = relations.loc[relations.news_id.isin(chosen)].copy()
            coverage = _read(re_folder/'cobertura_documental.csv')
            frames, summary = agregar_tabelas(news, mentions, registry, relations, coverage)
            staging = Path(tempfile.mkdtemp(prefix='.construindo_', dir=base))
            for name, frame in frames.items():write_csv(staging, name, frame)
            doc = ('Rede dirigida multirrelacional, sem identidade, autolaços ou grupos das fontes selecionadas.\n'
                'weight conta registros de relação; distinct_news_count conta notícias distintas.\n'
                'Sinalizações de qualidade são preservadas e não confirmam erros.\n'
                'Categorias jornalísticas descrevem contextos de publicação; não são categorias intrínsecas de entidades.\n'
                'Nos nós, distinct_news_count usa menções NER no recorte; relation_news_count usa relações utilizadas.\n'
                'As tabelas de apoio permitem reconstruir recortes e consultar notícias sem somar contagens distintas indevidamente.\n'
                'A rede não representa relações ausentes em notícias ainda não processadas.\n')
            (staging/'LEIA_ME.txt').write_text(doc, encoding='utf-8')
            manifest = {**spec, 'snapshot_sha256': signature, 'summary': summary,
                'created_at_utc': datetime.now(timezone.utc).isoformat(),
                'elapsed_s': round(time.monotonic()-started, 3),
                'outputs_sha256': {p.name: sha(p) for p in sorted(staging.iterdir())}}
            atomic_json(staging/'manifesto.json', manifest)
            validate_manifest(staging)
            if any(sha(root/p) != h for p, h in input_hashes.items()) or (
                carregar_entidades_integradas(root)[1]['snapshot_sha256'] != parent['snapshot_sha256']):
                raise ValueError('As entradas mudaram durante a construção.')
            os.rename(staging, target);staging = None
        meta = validate_manifest(target)
        if meta['snapshot_sha256'] != signature:raise ValueError('Colisão de versão da rede.')
        atomic_json(base/'atual.json', {'folder': target.name, 'snapshot_sha256': signature})
        output = root/'resultados/redes';output.mkdir(parents=True, exist_ok=True)
        package = output/f'Resumo_Construcao_Rede_{signature[:12]}_{uuid.uuid4().hex[:6]}.zip'
        names = ['manifesto.json', 'LEIA_ME.txt', 'grupos_fontes_excluidos.csv', 'cobertura_por_ano_fonte.csv']
        with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as z:
            for name in names:z.write(target/name, name)
            for name in ['nos.csv.gz', 'arestas.csv.gz', 'arestas_noticias.csv.gz']:
                frame = _read(target/name).head(50)
                z.writestr('amostra_'+name.removesuffix('.gz'), frame.to_csv(index=False))
        print('[REDE]', json.dumps(meta['summary'], ensure_ascii=False))
        print('[REDE] Saídas:', target);print('[REDE] Pacote:', package)
        return {**meta['summary'], 'output_directory': target, 'package': package, 'snapshot_sha256': signature}
    finally:
        if staging is not None:shutil.rmtree(staging, ignore_errors=True)
        lock.rmdir()


def carregar_rede(projeto):
    root = Path(projeto).resolve();base = root/'dados/processados/redes/instancias'
    pointer = json.loads((base/'atual.json').read_text(encoding='utf-8'))
    if Path(pointer['folder']).name != pointer['folder']:raise ValueError('Apontador inválido.')
    folder = base/pointer['folder'];meta = validate_manifest(folder)
    if meta['snapshot_sha256'] != pointer['snapshot_sha256']:raise ValueError('Apontador incompatível.')
    if carregar_entidades_integradas(root)[1]['snapshot_sha256'] != meta['entity_snapshot_sha256']:
        raise ValueError('Há nova integração de entidades. Reconstrua a rede.')
    if any(sha(root/p) != h for p, h in meta['inputs_sha256'].items()):
        raise ValueError('Uma entrada mudou. Reconstrua a rede.')
    return folder, meta


def consultar_noticias(projeto, *, entity_id=None, edge_id=None, somente_relacoes=False):
    """Retorna a lista completa no recorte, com título e link, sem abrir páginas."""
    if (entity_id is None) == (edge_id is None):
        raise ValueError('Informe entity_id ou edge_id, exclusivamente.')
    folder, _ = carregar_rede(projeto)
    if entity_id is not None:
        support = _read(folder/'nos_noticias.csv.gz')
        support = support.loc[support.entity_group_id.eq(str(entity_id))]
        if somente_relacoes:support = support.loc[pd.to_numeric(support.relation_participation_count).gt(0)]
    else:
        support = _read(folder/'arestas_noticias.csv.gz')
        support = support.loc[support.edge_id.eq(str(edge_id))]
    news = _read(folder/'noticias.csv.gz')
    return support.drop(columns=[c for c in support if c in news and c not in ['news_id', 'news_version_id']]).merge(
        news, on=['news_id', 'news_version_id'], how='left', validate='one_to_one').sort_values(
            ['publication_date', 'source', 'news_id'], kind='stable').reset_index(drop=True)
