"""Cobertura documental para comparações entre fontes e períodos."""
from pathlib import Path
from datetime import datetime, timezone
import json
import shutil
import tempfile
import uuid
import zipfile
import numpy as np
import pandas as pd
from redes_construcao import carregar_rede
from re_consolidacao import sha, json_sha, write_csv, validate_manifest
from re_execucao import atomic_json

VERSION = '1.0.0'
FONTES = ['CNN Brasil', 'Folha de S.Paulo', 'G1']
CONCLUIDOS = {'SUCCESS', 'SUCCESS_ZERO'}
CHAVES = ['news_id', 'news_version_id']


def preparar_tabelas(noticias, evidencias):
    """Distingue conclusão da RE de suporte à rede após suas exclusões."""
    n = noticias.copy()
    if n.empty or n.news_id.duplicated().any() or n[CHAVES].eq('').any().any():
        raise ValueError('Notícias vazias, duplicadas ou sem identidade/versionamento.')
    if not set(n.source).issubset(FONTES):
        raise ValueError('Fonte não prevista no recorte comparativo.')
    anos = pd.to_numeric(n.publication_year, errors='raise')
    if anos.isna().any() or not anos.eq(anos.astype(int)).all():
        raise ValueError('Ano ausente ou não inteiro.')
    n['publication_year'] = anos.astype(int)
    e = evidencias.copy()
    if e.duplicated(['edge_id'] + CHAVES).any():
        raise ValueError('Vínculo aresta-notícia duplicado.')
    teste = e.merge(n[CHAVES], on=CHAVES, how='left', indicator=True, validate='many_to_one')
    if not teste['_merge'].eq('both').all():
        raise ValueError('Evidência sem versão correspondente no corpus.')
    for col in ['source', 'publication_year']:
        pares = e[CHAVES + [col]].merge(n[CHAVES + [col]], on=CHAVES, suffixes=('_e', '_n'))
        if not pares[col + '_e'].astype(str).eq(pares[col + '_n'].astype(str)).all():
            raise ValueError('Fonte ou ano divergente na evidência.')
    e['occurrence_count'] = pd.to_numeric(e.occurrence_count, errors='raise')
    if not np.isfinite(e.occurrence_count).all() or not e.occurrence_count.ge(1).all() or not e.occurrence_count.mod(1).eq(0).all():
        raise ValueError('Contagem de ocorrências inválida.')
    suporte = e.groupby(CHAVES, as_index=False).agg(
        retained_occurrences=('occurrence_count', 'sum'),
        retained_typed_edges=('edge_id', 'nunique'))
    n = n.merge(suporte, on=CHAVES, how='left', validate='one_to_one')
    for c in ['retained_occurrences', 'retained_typed_edges']:
        n[c] = n[c].fillna(0).astype(int)
    n['supports_final_network'] = n.retained_occurrences.gt(0)
    n['re_completed_strict'] = n.re_state.isin(CONCLUIDOS)
    n['re_partial'] = n.re_state.eq('PARTIAL')
    n['too_few_mentions'] = n.re_state.eq('TOO_FEW_MENTIONS')
    if n.loc[n.re_state.eq('SUCCESS_ZERO'), 'supports_final_network'].any():
        raise ValueError('SUCCESS_ZERO com relações retidas; conferir consolidação.')
    def resumo(grupo):
        total = len(grupo)
        pronto = int(grupo.re_completed_strict.sum())
        parcial = int(grupo.re_partial.sum())
        sem_alvos = int(grupo.too_few_mentions.sum())
        return {
            'corpus_news': total, 're_completed_strict': pronto,
            're_partial': parcial, 'too_few_mentions': sem_alvos,
            're_other_states': total - pronto - parcial - sem_alvos,
            'support_news': int(grupo.supports_final_network.sum()),
            'completed_without_retained_relations': int((grupo.re_completed_strict & ~grupo.supports_final_network).sum()),
            'retained_occurrences': int(grupo.retained_occurrences.sum()),
            'strict_completion_share': pronto / total if total else None,
            'support_share': float(grupo.supports_final_network.mean()) if total else None,
            'observed_min_date': grupo.publication_date.min() if total else '',
            'observed_max_date': grupo.publication_date.max() if total else '',
        }
    linhas = []
    for ano in range(int(n.publication_year.min()), int(n.publication_year.max()) + 1):
        for fonte in FONTES:
            grupo = n.loc[n.publication_year.eq(ano) & n.source.eq(fonte)]
            linhas.append({'publication_year': ano, 'source': fonte, **resumo(grupo)})
    anual = pd.DataFrame(linhas)
    fontes = pd.DataFrame([{'source': fonte, **resumo(n.loc[n.source.eq(fonte)])} for fonte in FONTES])
    estados = n.groupby(['publication_year', 'source', 're_state'], as_index=False).size().rename(columns={'size': 'news_count'})
    candidatos = []
    for ano, grupo in anual.groupby('publication_year'):
        candidatos.append({'publication_year': int(ano),
            'sources_with_corpus': int(grupo.corpus_news.gt(0).sum()),
            'sources_with_network_support': int(grupo.support_news.gt(0).sum()),
            'common_year_with_support': bool(grupo.support_news.gt(0).all()),
            'min_strict_completion_share': grupo.strict_completion_share.min(),
            'min_support_news_per_source': int(grupo.support_news.min()),
            'max_to_min_corpus_ratio': float(grupo.corpus_news.max()/grupo.corpus_news.min()) if grupo.corpus_news.gt(0).all() else None,
            'automatic_period_selection': False})
    return n, anual, fontes, estados, pd.DataFrame(candidatos)


def gerar_cobertura(projeto, *, executar=False, assinatura_rede_esperada=None):
    """Audita a edição ativa sem abrir conexões com Neo4j ou provedores."""
    root = Path(projeto).resolve()
    if root.name == 'PROJECT_EXTRACAO':
        raise ValueError('Use o projeto de análise, não a pasta de extração incremental.')
    origem, meta = carregar_rede(root)
    if assinatura_rede_esperada and meta['snapshot_sha256'] != assinatura_rede_esperada:
        raise ValueError('A rede ativa difere da edição esperada.')
    if not executar:
        return {'mode': 'DRY_RUN', 'network_snapshot_sha256': meta['snapshot_sha256'],
                'api_calls': 0, 'neo4j_connections': 0, 'files_written': 0,
                'automatic_period_selection': False}
    noticias = pd.read_csv(origem/'noticias.csv.gz', dtype=str, keep_default_na=False)
    evidencias = pd.read_csv(origem/'arestas_noticias.csv.gz', dtype=str, keep_default_na=False)
    n, anual, fontes, estados, candidatos = preparar_tabelas(noticias, evidencias)
    if len(n) != meta['summary']['selected_news'] or int(n.supports_final_network.sum()) != meta['summary']['support_news']:
        raise ValueError('Contagens documentais incompatíveis com a rede.')
    if int(n.retained_occurrences.sum()) != meta['summary']['weight_sum']:
        raise ValueError('Ocorrências não recompõem a soma de pesos da rede.')
    spec = {'schema': 'network-document-coverage-1', 'version': VERSION,
            'network_snapshot_sha256': meta['snapshot_sha256'], 'code_sha256': sha(Path(__file__)),
            'inputs_sha256': {name: sha(origem/name) for name in ['noticias.csv.gz', 'arestas_noticias.csv.gz']}}
    assinatura = json_sha(spec)
    base = root/'resultados/comparacao_fontes/cobertura'
    base.mkdir(parents=True, exist_ok=True)
    destino = base/assinatura[:20]
    resumo = {'corpus_news': len(n), 'support_news': int(n.supports_final_network.sum()),
              'retained_occurrences': int(n.retained_occurrences.sum()),
              're_completed_strict': int(n.re_completed_strict.sum()), 're_partial': int(n.re_partial.sum()),
              'common_years_with_network_support': candidatos.loc[candidatos.common_year_with_support, 'publication_year'].tolist(),
              'automatic_period_selection': False, 'api_calls': 0, 'neo4j_connections': 0,
              'database_writes': 0, 'network_modified': False}
    if destino.exists():
        atual = validate_manifest(destino)
        if atual['snapshot_sha256'] != assinatura:
            raise ValueError('Saída incompatível com a assinatura.')
    else:
        temp = Path(tempfile.mkdtemp(prefix='.cobertura_', dir=base))
        try:
            for nome, tabela in [('noticias_cobertura.csv.gz', n), ('cobertura_ano_fonte.csv', anual),
                                  ('cobertura_fontes.csv', fontes), ('estados_re_ano_fonte.csv', estados),
                                  ('anos_comuns.csv', candidatos)]:
                write_csv(temp, nome, tabela)
            texto = ('# Cobertura documental\n\nConclusão estrita: SUCCESS ou SUCCESS_ZERO. PARTIAL é informada separadamente. '
                     'TOO_FEW_MENTIONS não é falha de API nem conclusão por extração.\n\n'
                     'Suporte à rede significa possuir uma relação semântica retida após exclusões; '
                     'não equivale a notícia processada. Uma extração concluída pode não produzir arestas.\n\n'
                     'As proporções usam todas as notícias do corpus da fonte e ano como denominador. '
                     'Linhas sem notícias têm proporções ausentes, não zero. Datas são limites observados '
                     'e não comprovam cobertura de ano completo. Ausência de publicação no corpus não comprova ausência no veículo.\n\n'
                     'Anos comuns indicam apenas suporte nas três fontes. Nenhum período é escolhido automaticamente. '
                     'Volumes por mil notícias não eliminam viés de seleção nem tornam redes de tamanhos diferentes equivalentes.\n')
            (temp/'LEIA_ME.md').write_text(texto, encoding='utf-8')
            atomic_json(temp/'manifesto.json', {**spec, 'snapshot_sha256': assinatura, 'summary': resumo,
                'created_at_utc': datetime.now(timezone.utc).isoformat(),
                'outputs_sha256': {p.name: sha(p) for p in sorted(temp.iterdir())}})
            validate_manifest(temp)
            temp.rename(destino)
        finally:
            if temp.exists(): shutil.rmtree(temp)
    atomic_json(base/'atual.json', {'folder': destino.name, 'snapshot_sha256': assinatura})
    pacote = base/('Resumo_Cobertura_Fontes_' + assinatura[:12] + '_' + uuid.uuid4().hex[:6] + '.zip')
    with zipfile.ZipFile(pacote, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(destino.iterdir()): z.write(p, p.name)
    print('[COBERTURA]', json.dumps(resumo, ensure_ascii=False))
    print('[COBERTURA] Pacote:', pacote)
    return {**resumo, 'output_directory': destino, 'package': pacote, 'snapshot_sha256': assinatura}
