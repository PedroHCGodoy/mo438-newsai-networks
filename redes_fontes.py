"""Redes por fonte com pesos e atributos recalculados no período selecionado."""
from pathlib import Path
from datetime import datetime, timezone
import json
import shutil
import tempfile
import uuid
import zipfile
import pandas as pd
from redes_construcao import carregar_rede
from redes_projecoes import preparar_tabelas as projetar_tabelas
from re_consolidacao import sha, json_sha, write_csv, validate_manifest
from re_execucao import atomic_json

VERSION = '1.0.0'
FONTES = {'cnn': 'CNN Brasil', 'folha': 'Folha de S.Paulo', 'g1': 'G1'}
KEYS = ['news_id', 'news_version_id']
FLAGS = ['review_records', 'provisional_records', 'semantic_flag_records']


def inteiro_positivo(frame, col, zero=False):
    valores = pd.to_numeric(frame[col], errors='raise')
    if valores.isna().any() or not valores.ge(0 if zero else 1).all() or not valores.mod(1).eq(0).all():
        raise ValueError('Contagem inválida: ' + col)
    frame[col] = valores.astype('int64')


def construir_fonte(noticias, nos, arestas, nos_noticias, evidencias, *, fonte, inicio, fim):
    """Seleciona documentos e reconta ocorrências; IDs globais são preservados."""
    n = noticias.copy()
    if n.news_id.duplicated().any() or nos.entity_group_id.duplicated().any() or arestas.edge_id.duplicated().any():
        raise ValueError('Identidades duplicadas nas entradas.')
    dias = pd.to_datetime(n.publication_date, format='%Y-%m-%d', errors='coerce')
    candidatos = n.source.eq(fonte) & n.publication_year.astype(str).isin(
        [str(y) for y in range(inicio.year, fim.year + 1)])
    if (candidatos & (dias.isna() | ~n.publication_date_precision.isin(['DATA_HORA', 'DIA']))).any():
        raise ValueError('Data ausente ou imprecisa no período; revise o recorte documental.')
    if not dias.loc[candidatos].dt.year.astype(str).eq(n.loc[candidatos, 'publication_year'].astype(str)).all():
        raise ValueError('Ano divergente da data documental.')
    selecionadas = n.loc[n.source.eq(fonte) & dias.ge(inicio) & dias.le(fim)].copy()
    if selecionadas.empty:
        raise ValueError('Nenhuma notícia no período para ' + fonte)
    chaves = selecionadas[KEYS]
    if evidencias.duplicated(['edge_id'] + KEYS).any():
        raise ValueError('Evidência aresta-notícia duplicada.')
    validacao = evidencias[KEYS].drop_duplicates().merge(n[KEYS], on=KEYS, how='left', indicator=True)
    if not validacao['_merge'].eq('both').all():
        raise ValueError('Evidência sem versão documental correspondente.')
    e = evidencias.merge(chaves, on=KEYS, how='inner', validate='many_to_one').copy()
    if e.empty:
        raise ValueError('Fonte sem relações retidas no período: ' + fonte)
    if not e.source.eq(fonte).all():
        raise ValueError('Fonte divergente no suporte documental.')
    datas_e = e[KEYS + ['publication_date']].merge(selecionadas[KEYS + ['publication_date']], on=KEYS,
                                                suffixes=('_e', '_n'), validate='many_to_one')
    if not datas_e.publication_date_e.eq(datas_e.publication_date_n).all():
        raise ValueError('Data divergente no suporte documental.')
    for col in ['occurrence_count'] + FLAGS:
        inteiro_positivo(e, col, zero=col != 'occurrence_count')
    if any(e[c].gt(e.occurrence_count).any() for c in FLAGS):
        raise ValueError('Sinalizadores excedem as ocorrências.')
    atributos = arestas[['edge_id', 'source_id', 'target_id', 'label', 'relation_macro']]
    contagens = e.groupby('edge_id', as_index=False, sort=True).agg(
        weight=('occurrence_count', 'sum'), review_records=('review_records', 'sum'),
        provisional_records=('provisional_records', 'sum'), semantic_flag_records=('semantic_flag_records', 'sum'),
        distinct_news_count=('news_id', 'nunique'), first_observed_date=('publication_date', 'min'),
        last_observed_date=('publication_date', 'max'))
    a = contagens.merge(atributos, on='edge_id', how='left', validate='one_to_one')
    if a.source_id.isna().any() or a.source_id.eq(a.target_id).any() or a.label.eq('ident').any():
        raise ValueError('Aresta desconhecida, identidade ou autolaço no recorte.')
    if a[['source_id', 'target_id', 'label']].duplicated().any():
        raise ValueError('Tripla dirigida repetida.')
    a['distinct_source_count'] = 1
    ids = set(a.source_id) | set(a.target_id)
    nn = nos_noticias.merge(chaves, on=KEYS, how='inner', validate='many_to_one')
    nn = nn.loc[nn.entity_group_id.isin(ids)].copy()
    if nn.duplicated(['entity_group_id'] + KEYS).any() or not nn.source.eq(fonte).all():
        raise ValueError('Menções agrupadas duplicadas ou de outra fonte.')
    for col in ['mention_count', 'review_mentions', 'relation_participation_count']:
        inteiro_positivo(nn, col, zero=col != 'mention_count')
    participacoes = e[['edge_id'] + KEYS + ['occurrence_count']].merge(atributos, on='edge_id', validate='many_to_one')
    partes = pd.concat([participacoes[[lado] + KEYS + ['occurrence_count']].rename(columns={lado: 'entity_group_id'})
                        for lado in ['source_id', 'target_id']], ignore_index=True)
    p = partes.groupby(['entity_group_id'] + KEYS, as_index=False).occurrence_count.sum()
    check = p.merge(nn[['entity_group_id'] + KEYS + ['relation_participation_count']],
                    on=['entity_group_id'] + KEYS, how='outer', validate='one_to_one')
    if not check.occurrence_count.fillna(0).eq(check.relation_participation_count.fillna(-1)).all():
        raise ValueError('Participações nas relações diferem do suporte dos nós.')
    estatisticas = nn.groupby('entity_group_id', as_index=False).agg(
        mention_count=('mention_count', 'sum'), distinct_news_count=('news_id', 'nunique'),
        review_mentions=('review_mentions', 'sum'), first_observed_date=('publication_date', 'min'),
        last_observed_date=('publication_date', 'max'))
    rn = p.groupby('entity_group_id').news_id.nunique().rename('relation_news_count').reset_index()
    v = nos.loc[nos.entity_group_id.isin(ids), ['entity_group_id', 'entity_group_name', 'ent_label']].copy()
    if len(v) != len(ids):
        raise ValueError('Nó ausente do catálogo global.')
    v = v.merge(estatisticas, on='entity_group_id', how='left', validate='one_to_one').merge(rn, on='entity_group_id', how='left', validate='one_to_one')
    if v.mention_count.isna().any() or v.relation_news_count.isna().any():
        raise ValueError('Nó sem menção ou suporte relacional no recorte.')
    v['distinct_source_count'] = 1
    v['entity_review_required'] = v.review_mentions.gt(0)
    projecoes, _ = projetar_tabelas(a, e)
    linhas = pd.concat([a[['source_id', 'weight']].rename(columns={'source_id': 'entity_group_id'}),
                        a[['target_id', 'weight']].rename(columns={'target_id': 'entity_group_id'})])
    for campo, serie in [('weighted_strength', linhas.groupby('entity_group_id').weight.sum()),
                         ('out_strength', a.groupby('source_id').weight.sum()),
                         ('in_strength', a.groupby('target_id').weight.sum())]:
        v[campo] = v.entity_group_id.map(serie).fillna(0).astype('int64')
    if int(v.weighted_strength.sum()) != 2 * int(e.occurrence_count.sum()):
        raise ValueError('Forças dos nós não recompõem os pesos.')
    resumo = {'source': fonte, 'selected_news': len(selecionadas),
        're_completed_strict': int(selecionadas.re_state.isin(['SUCCESS', 'SUCCESS_ZERO']).sum()),
        're_partial': int(selecionadas.re_state.eq('PARTIAL').sum()),
        'support_news': int(e.news_id.nunique()), 'nodes': len(v), 'typed_directed_edges': len(a),
        'distinct_directed_pairs': len(a[['source_id', 'target_id']].drop_duplicates()),
        'undirected_pairs': len(projecoes['simples_nao_dirigida.csv.gz']),
        'weight_sum': int(a.weight.sum()), 'self_loops': 0, 'identity_edges': 0,
        'observed_min_date': selecionadas.publication_date.min(), 'observed_max_date': selecionadas.publication_date.max()}
    if resumo['weight_sum'] != int(e.occurrence_count.sum()):
        raise ValueError('Peso não recompõe o suporte documental.')
    tabelas = {'nos.csv.gz': v.sort_values('entity_group_id'), 'arestas.csv.gz': a.sort_values('edge_id'),
               'noticias.csv.gz': selecionadas, 'nos_noticias.csv.gz': nn,
               'arestas_noticias.csv.gz': e, **projecoes}
    return tabelas, resumo


def construir_redes_fontes(projeto, *, executar=False, data_inicial='2025-01-01',
                           data_final='2025-12-31', assinatura_rede_esperada=None):
    root = Path(projeto).resolve()
    if root.name == 'PROJECT_EXTRACAO':
        raise ValueError('Execute no projeto de análise.')
    inicio, fim = pd.Timestamp(data_inicial), pd.Timestamp(data_final)
    if pd.isna(inicio) or pd.isna(fim) or inicio > fim or inicio != inicio.normalize() or fim != fim.normalize():
        raise ValueError('Use limites de datas válidos, sem horário.')
    origem, meta = carregar_rede(root)
    if assinatura_rede_esperada and meta['snapshot_sha256'] != assinatura_rede_esperada:
        raise ValueError('A rede ativa difere da edição esperada.')
    if not executar:
        return {'mode': 'DRY_RUN', 'sources': list(FONTES.values()),
                'start_date': str(inicio.date()), 'end_date': str(fim.date()),
                'recompute_weights_from_evidence': True, 'files_written': 0,
                'api_calls': 0, 'neo4j_connections': 0}
    nomes = ['noticias.csv.gz', 'nos.csv.gz', 'arestas.csv.gz', 'nos_noticias.csv.gz', 'arestas_noticias.csv.gz']
    entradas = [pd.read_csv(origem/nome, dtype=str, keep_default_na=False) for nome in nomes]
    spec = {'schema': 'source-networks-1', 'version': VERSION, 'code_sha256': sha(Path(__file__)),
            'projection_code_sha256': sha(Path(projetar_tabelas.__code__.co_filename)),
            'network_snapshot_sha256': meta['snapshot_sha256'], 'sources': FONTES,
            'start_date': str(inicio.date()), 'end_date': str(fim.date()),
            'node_universe': 'endpoints of retained relations in each source and period',
            'inputs_sha256': {nome: sha(origem/nome) for nome in nomes}}
    assinatura = json_sha(spec)
    base = root/'dados/processados/redes/fontes'
    base.mkdir(parents=True, exist_ok=True)
    destino = base/assinatura[:20]
    if destino.exists():
        salvo = validate_manifest(destino)
        if salvo['snapshot_sha256'] != assinatura:
            raise ValueError('Assinatura incompatível na saída existente.')
        resumos = salvo['summary']['networks']
    else:
        temp = Path(tempfile.mkdtemp(prefix='.fontes_', dir=base))
        try:
            resumos = []
            for slug, fonte in FONTES.items():
                tabelas, resumo = construir_fonte(*entradas, fonte=fonte, inicio=inicio, fim=fim)
                for nome, tabela in tabelas.items(): write_csv(temp, slug+'_'+nome, tabela)
                resumos.append({'source_key': slug, **resumo})
                print('[FONTES]', json.dumps(resumos[-1], ensure_ascii=False))
            write_csv(temp, 'resumo_redes.csv', pd.DataFrame(resumos))
            (temp/'LEIA_ME.md').write_text(
                '# Redes por fonte\n\nOs prefixos cnn, folha e g1 identificam tabelas independentes. '
                'Os pesos, atributos e vínculos documentais são recontados no período de cada fonte. '
                'Os IDs globais de grupos e arestas são preservados; não compare nomes como chaves.\n\n'
                'Os nós participam de pelo menos uma relação retida no recorte. Seus totais de menções '
                'incluem documentos do recorte com NER disponível, mesmo sem RE concluída. '
                'relation_news_count conta apenas notícias com participação nas relações retidas.\n\n'
                'A projeção simples é não dirigida e tem peso unitário. A ponderada agrega rótulos e '
                'ambas as direções. distance=1/weight é atributo disponível, não distância topológica: '
                'caminhos em número de arestas devem usar a projeção simples.\n\n'
                'As redes descrevem a cobertura disponível, sem imputação de relações faltantes. '
                'As mesmas exclusões da rede de origem permanecem aplicadas. Não há detecção de '
                'comunidades, cálculo de PageRank, carga ou projeção em memória do Neo4j nesta execução. '
                'As tabelas de projeção são persistidas para os cálculos posteriores.\n', encoding='utf-8')
            resumo_geral = {'networks': resumos, 'api_calls': 0, 'neo4j_connections': 0,
                'database_writes': 0, 'global_network_modified': False, 'scientific_algorithms_computed': False}
            atomic_json(temp/'manifesto.json', {**spec, 'snapshot_sha256': assinatura, 'summary': resumo_geral,
                'created_at_utc': datetime.now(timezone.utc).isoformat(),
                'outputs_sha256': {p.name: sha(p) for p in sorted(temp.iterdir())}})
            validate_manifest(temp)
            temp.rename(destino)
        finally:
            if temp.exists(): shutil.rmtree(temp)
    atomic_json(base/'atual.json', {'folder': destino.name, 'snapshot_sha256': assinatura})
    saidas = root/'resultados/comparacao_fontes'
    saidas.mkdir(parents=True, exist_ok=True)
    pacote = saidas/('Resumo_Redes_Fontes_'+assinatura[:12]+'_'+uuid.uuid4().hex[:6]+'.zip')
    with zipfile.ZipFile(pacote, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(destino.iterdir()): z.write(p, p.name)
    print('[FONTES] Pacote:', pacote)
    return {'networks': resumos, 'api_calls': 0, 'neo4j_connections': 0, 'database_writes': 0,
            'global_network_modified': False, 'scientific_algorithms_computed': False,
            'output_directory': destino, 'package': pacote, 'snapshot_sha256': assinatura}
