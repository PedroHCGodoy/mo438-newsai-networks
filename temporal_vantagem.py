"""Associação longitudinal entre grau anterior e aquisição de novos vizinhos."""
from pathlib import Path
from datetime import datetime, timezone
from time import perf_counter
import json
import shutil
import tempfile
import uuid
import zipfile
import numpy as np
import pandas as pd
from temporal_redes import ANOS, carregar_redes_temporais
from temporal_caudas import carregar_trajetorias
from re_consolidacao import sha, json_sha, write_csv, validate_manifest
from re_execucao import atomic_json

VERSION = '1.0.0'
COLORS = {'PESSOA': '#4C78A8', 'ORGANIZACAO': '#F58518', 'LOCAL': '#54A24B'}
OUTCOMES = ['new_neighbors', 'new_neighbors_to_new',
            'new_neighbors_to_preexisting', 'reinforcement_occurrences']


def rho_descritivo(x, y):
    """Correlação de postos com empates médios, sem p-valor iid."""
    x, y = pd.Series(np.asarray(x)), pd.Series(np.asarray(y))
    if len(x) != len(y) or x.isna().any() or y.isna().any():
        raise ValueError('Pares incompletos para associação.')
    if len(x) < 3 or x.nunique() < 2 or y.nunique() < 2:
        return None
    return float(x.rank(method='average').corr(y.rank(method='average')))


def preparar_painel(dados, cobertura):
    """Confere transições e mantém o conjunto de risco observado no ano anterior."""
    d = dados.copy()
    integer_cols = ['entity_group_id', 'cutoff_year', 'degree', 'previous_degree',
                    'new_neighbors', 'annual_mention_news', 'annual_relation_news']
    for col in integer_cols:
        values = pd.to_numeric(d[col], errors='raise')
        if values.isna().any() or not np.isfinite(values).all() or (values < 0).any() or values.mod(1).ne(0).any():
            raise ValueError('Coluna inteira inválida: ' + col)
        d[col] = values.astype('int64')
    if sorted(d.cutoff_year.unique()) != list(ANOS) or d.duplicated(['entity_group_id', 'cutoff_year']).any():
        raise ValueError('Série incompleta ou com entidade duplicada.')
    if d.degree.lt(1).any() or d[['entity_group_name', 'ent_label']].isna().any().any():
        raise ValueError('Identificação ou grau inválido.')
    c = cobertura.set_index('publication_year', verify_integrity=True)
    if sorted(c.index) != list(ANOS):
        raise ValueError('Cobertura anual incompleta.')
    first = d.groupby('entity_group_id').cutoff_year.min()
    if d.groupby('entity_group_id').ent_label.nunique().gt(1).any():
        raise ValueError('Tipo canônico mudou entre cortes.')
    parts, audit = [], []
    previous = None
    for year, g in d.groupby('cutoff_year', sort=True):
        g = g.copy()
        if len(g) != int(c.loc[year, 'cumulative_nodes']) or int(g.degree.sum()) != 2*int(c.loc[year, 'cumulative_undirected_pairs']):
            raise ValueError('Corte não recompõe a cobertura: ' + str(year))
        if previous is None:
            if not g.is_baseline_stock.astype(str).str.lower().eq('true').all():
                raise ValueError('Estoque inicial não identificado.')
            previous = g.set_index('entity_group_id')
            continue
        if g.is_baseline_stock.astype(str).str.lower().ne('false').any():
            raise ValueError('Transição marcada como estoque inicial.')
        if not set(previous.index).issubset(set(g.entity_group_id)):
            raise ValueError('Entidades desapareceram na acumulação.')
        expected = g.entity_group_id.map(previous.degree).fillna(0).astype('int64')
        if not expected.equals(g.previous_degree) or not g.degree.sub(expected).equals(g.new_neighbors):
            raise ValueError('Ganho ou grau anterior incompatível: ' + str(year))
        for col in OUTCOMES[1:]:
            values = pd.to_numeric(g[col], errors='raise')
            if values.isna().any() or not np.isfinite(values).all() or values.lt(0).any() or values.mod(1).ne(0).any():
                raise ValueError('Ganho inválido: ' + col)
            g[col] = values.astype('int64')
        if not g.new_neighbors.equals(g.new_neighbors_to_new + g.new_neighbors_to_preexisting):
            raise ValueError('Tipos de vizinhos não recompõem o ganho.')
        new_pairs = int(c.loc[year, 'cumulative_undirected_pairs'] - c.loc[year-1, 'cumulative_undirected_pairs'])
        if int(g.new_neighbors.sum()) != 2*new_pairs:
            raise ValueError('Ganhos não recompõem os pares novos.')
        old = g.loc[g.entity_group_id.isin(previous.index)].copy()
        entrants = g.loc[~g.entity_group_id.isin(previous.index)]
        old['previous_year'] = int(year-1)
        old['first_network_year'] = old.entity_group_id.map(first).astype(int)
        old['network_age_years'] = year-1-old.first_network_year
        old['age_band'] = np.select([old.network_age_years.le(2), old.network_age_years.le(9)], ['0-2', '3-9'], default='10+')
        old['mention_exposure_band'] = np.select(
            [old.annual_mention_news.eq(0), old.annual_mention_news.eq(1), old.annual_mention_news.le(4)],
            ['0', '1', '2-4'], default='5+')
        old['degree_bin_lower'] = np.left_shift(1, np.floor(np.log2(old.previous_degree)).astype(int))
        old['degree_bin_upper'] = 2*old.degree_bin_lower-1
        n, gains, degree_sum = len(old), int(old.new_neighbors.sum()), int(old.previous_degree.sum())
        old['uniform_reference_gain'] = gains/n
        old['degree_reference_gain'] = gains*old.previous_degree/degree_sum
        old['normalized_gain'] = old.new_neighbors/(gains/n) if gains else np.nan
        old['previous_degree_rank'] = old.previous_degree.rank(method='min', ascending=False).astype(int)
        old['gain_rank'] = old.new_neighbors.rank(method='min', ascending=False).astype(int)
        old['strict_re_completion_share'] = float(c.loc[year, 'strict_completion_share'])
        old['annual_support_news'] = int(c.loc[year, 'support_news'])
        old['no_completed_re_in_year'] = bool(c.loc[year, 'no_completed_re_in_year'])
        if gains and (not np.isclose(old.uniform_reference_gain.sum(), gains)
                      or not np.isclose(old.degree_reference_gain.sum(), gains)):
            raise ValueError('Referências não conservam o ganho do conjunto anterior.')
        parts.append(old)
        audit.append({'previous_year': int(year-1), 'cutoff_year': int(year), 'preexisting_nodes': n,
            'entering_nodes': len(entrants), 'new_pairs': new_pairs,
            'gains_preexisting_nodes': gains, 'gains_entering_nodes': int(entrants.new_neighbors.sum()),
            'all_node_gains': int(g.new_neighbors.sum()), 'zero_gain_preexisting_nodes': int(old.new_neighbors.eq(0).sum()),
            'corpus_news': int(c.loc[year, 'corpus_news']), 're_completed_strict': int(c.loc[year, 're_completed_strict']),
            're_partial': int(c.loc[year, 're_partial']), 'support_news': int(c.loc[year, 'support_news']),
            'strict_completion_share': float(c.loc[year, 'strict_completion_share']),
            'no_completed_re_in_year': bool(c.loc[year, 'no_completed_re_in_year']),
            'all_gains_verified': True})
        previous = g.set_index('entity_group_id')
    return pd.concat(parts, ignore_index=True), pd.DataFrame(audit)


def resumir_associacoes(painel):
    rows = []
    for year, annual in painel.groupby('cutoff_year', sort=True):
        for tipo in ['ALL'] + sorted(annual.ent_label.unique().tolist()):
            group = annual if tipo == 'ALL' else annual.loc[annual.ent_label.eq(tipo)]
            for scope, g in [('ALL_PREEXISTING', group),
                             ('MENTION_NEWS_GE_1', group.loc[group.annual_mention_news.ge(1)]),
                             ('MENTION_NEWS_GE_5', group.loc[group.annual_mention_news.ge(5)])]:
                for outcome in OUTCOMES:
                    rho = rho_descritivo(g.previous_degree, g[outcome])
                    rows.append({'cutoff_year': int(year), 'entity_type': tipo, 'scope': scope,
                        'outcome': outcome, 'nodes': len(g), 'gain_sum': int(g[outcome].sum()),
                        'zero_gain_nodes': int(g[outcome].eq(0).sum()), 'spearman_rho': rho,
                        'status': 'DEFINED' if rho is not None else 'INSUFFICIENT_VARIATION',
                        'p_value_computed': False})
    return pd.DataFrame(rows)


def resumir_faixas(painel):
    rows = []
    for (year, low), g in painel.groupby(['cutoff_year', 'degree_bin_lower'], sort=True):
        total = painel.loc[painel.cutoff_year.eq(year), 'new_neighbors'].sum()
        gain = int(g.new_neighbors.sum())
        rows.append({'cutoff_year': int(year), 'degree_bin_lower': int(low), 'degree_bin_upper': int(2*low-1),
            'nodes': len(g), 'previous_degree_mean': float(g.previous_degree.mean()),
            'gain_sum': gain, 'gain_mean': float(g.new_neighbors.mean()),
            'positive_gain_share': float(g.new_neighbors.gt(0).mean()),
            'normalized_gain_mean': float(g.normalized_gain.mean()) if total else None,
            'observed_gain_share': gain/total if total else None,
            'uniform_reference_share': float(g.uniform_reference_gain.sum()/total) if total else None,
            'degree_reference_share': float(g.degree_reference_gain.sum()/total) if total else None})
    return pd.DataFrame(rows)


def resumir_estratos(painel):
    rows = []
    keys = ['cutoff_year', 'ent_label', 'age_band', 'mention_exposure_band']
    for key, g in painel.groupby(keys, sort=True):
        rho = rho_descritivo(g.previous_degree, g.new_neighbors)
        rows.append({**dict(zip(keys, key)), 'nodes': len(g), 'gain_sum': int(g.new_neighbors.sum()),
            'mean_previous_degree': float(g.previous_degree.mean()), 'mean_gain': float(g.new_neighbors.mean()),
            'positive_gain_share': float(g.new_neighbors.gt(0).mean()), 'spearman_rho': rho,
            'status': 'DEFINED' if rho is not None else 'INSUFFICIENT_VARIATION'})
    return pd.DataFrame(rows)


def estudar_casos(painel, ids):
    out = painel.loc[painel.entity_group_id.isin(ids)].copy()
    if set(ids) - set(out.entity_group_id):
        raise ValueError('Caso sem transição observada no painel.')
    stats = painel.groupby(['cutoff_year', 'ent_label', 'age_band', 'mention_exposure_band'], as_index=False).agg(
        comparison_nodes=('entity_group_id', 'size'), comparison_gain_mean=('new_neighbors', 'mean'),
        comparison_gain_median=('new_neighbors', 'median'))
    out = out.merge(stats, on=['cutoff_year', 'ent_label', 'age_band', 'mention_exposure_band'], validate='many_to_one')
    out['gain_minus_stratum_mean'] = out.new_neighbors-out.comparison_gain_mean
    return out


def gerar_figuras(folder, associations, bins, audit, cases):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    plt.rcParams.update({'font.size': 10, 'svg.fonttype': 'none', 'pdf.fonttype': 42})
    catalog = []
    def save(fig, name, objective, caption):
        fig.tight_layout()
        for ext in ['svg', 'png', 'pdf']:
            filename = name+'.'+ext
            fig.savefig(folder/filename, dpi=300, bbox_inches='tight')
            catalog.append({'file': filename, 'objective': objective, 'caption': caption})
        plt.close(fig)
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for scope, color, label in [('ALL_PREEXISTING', '#4C78A8', 'Todas as entidades anteriores'),
                                 ('MENTION_NEWS_GE_1', '#F58518', 'Com menção em ≥1 notícia do ano'),
                                 ('MENTION_NEWS_GE_5', '#54A24B', 'Com menção em ≥5 notícias do ano')]:
        g = associations.loc[associations.entity_type.eq('ALL') & associations.outcome.eq('new_neighbors') & associations.scope.eq(scope)]
        axes[0].plot(g.cutoff_year, g.spearman_rho, marker='o', markersize=3, color=color, label=label)
    axes[0].axhline(0, color='grey', linewidth=.7); axes[0].set(ylabel='Spearman: grau anterior × ganho', ylim=(-1.02, 1.02))
    axes[0].legend(frameon=False, fontsize=8); axes[0].grid(alpha=.2)
    axes[1].plot(audit.cutoff_year, audit.strict_completion_share, color='#4C78A8', label='RE estritamente concluída / corpus')
    axes[1].plot(audit.cutoff_year, audit.support_news/audit.corpus_news.replace(0, np.nan), color='#F58518', label='Notícias que sustentam relações / corpus')
    axes[1].set(xlabel='Ano final da transição anual', ylabel='Cobertura', ylim=(0, 1.05))
    axes[1].yaxis.set_major_formatter(PercentFormatter(1)); axes[1].legend(frameon=False, fontsize=8); axes[1].grid(alpha=.2)
    save(fig, '01_associacao_e_cobertura', 'Relacionar associação anual e cobertura das extrações.',
         'Correlação descritiva com empates médios. Todos os nós anteriores incluem ganhos zero; subconjuntos por menção '
         'são análises de sensibilidade, não controle causal. Ausência de variação gera lacuna, não correlação zero. '
         'O painel de cobertura mostra o ano de chegada; a cobertura anterior também afeta o grau de partida. '
         'Subconjuntos pequenos podem produzir coeficientes extremos; consulte nodes no CSV.')
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    for year in [2005, 2013, 2019, 2022, 2025]:
        g = bins.loc[bins.cutoff_year.eq(year)]
        axes[0].plot(g.previous_degree_mean, g.normalized_gain_mean, marker='o', markersize=3, label=str(year))
    axes[0].axhline(1, color='grey', linestyle='--', linewidth=.8)
    axes[0].set(xscale='log', xlabel='Grau anterior médio na faixa', ylabel='Ganho médio / média anual de ganho')
    axes[0].legend(frameon=False); axes[0].grid(alpha=.2)
    g = bins.loc[bins.cutoff_year.eq(2025)].copy()
    x = np.arange(len(g)); labels = [str(int(a)) if a == b else f'{int(a)}–{int(b)}' for a,b in zip(g.degree_bin_lower, g.degree_bin_upper)]
    for offset, col, color, label in [(-.25, 'observed_gain_share', '#4C78A8', 'Observado'),
                                    (0, 'uniform_reference_share', '#F58518', 'Referência uniforme'),
                                    (.25, 'degree_reference_share', '#54A24B', 'Referência proporcional ao grau')]:
        axes[1].bar(x+offset, g[col], width=.25, color=color, label=label)
    axes[1].set(xticks=x, xticklabels=labels, xlabel='Faixa do grau anterior em 2024', ylabel='Fração dos ganhos nos nós anteriores')
    axes[1].tick_params(axis='x', rotation=55); axes[1].yaxis.set_major_formatter(PercentFormatter(1)); axes[1].legend(frameon=False, fontsize=8)
    save(fig, '02_ganhos_por_grau_anterior', 'Comparar ganhos por entidade e referências de alocação.',
         'Faixas fixas 1, 2–3, 4–7 etc.; tamanhos amostrais no CSV. A normalização usa a média anual entre todos os nós '
         'anteriores, incluindo zeros. Referências conservam a soma anual de ganhos; são descrições algébricas, não redes '
         'simuladas nem testes probabilísticos. A curva não estima expoente de conexão preferencial.')
    fig, ax = plt.subplots(figsize=(11, 4.5))
    for outcome, color, label in [('new_neighbors', '#4C78A8', 'Todos os novos vizinhos'),
        ('new_neighbors_to_new', '#F58518', 'Vizinhos que ingressaram no ano'),
        ('new_neighbors_to_preexisting', '#54A24B', 'Vizinhos já presentes'),
        ('reinforcement_occurrences', '#B279A2', 'Reforço: ocorrências em pares existentes')]:
        g = associations.loc[associations.entity_type.eq('ALL') & associations.scope.eq('ALL_PREEXISTING') & associations.outcome.eq(outcome)]
        ax.plot(g.cutoff_year, g.spearman_rho, marker='o', markersize=3, label=label, color=color)
    ax.axhline(0, color='grey', linewidth=.7); ax.set(xlabel='Ano final da transição', ylabel='Spearman com grau anterior', ylim=(-1.02, 1.02))
    ax.grid(alpha=.2); ax.legend(frameon=False, fontsize=8)
    save(fig, '03_formacao_e_reforco', 'Separar expansão da vizinhança e repetição de relações.',
         'Ganho de vizinhos e reforço de pares são resultados distintos. Correlações não são somáveis; reforço não aumenta '
         'o grau. Os graus e os resultados são dependentes pela estrutura da rede; não se fornecem p-valores iid.')
    ids = cases.entity_group_id.drop_duplicates().tolist()
    fig, axes = plt.subplots(len(ids), 2, figsize=(12, max(4, 3.3*len(ids))), squeeze=False)
    for row, entity in enumerate(ids):
        g = cases.loc[cases.entity_group_id.eq(entity)].sort_values('cutoff_year')
        title = f'{g.entity_group_name.iloc[0]} · {g.ent_label.iloc[0]} · ID {entity}'
        axes[row, 0].plot(g.cutoff_year, g.new_neighbors, label='Ganho observado', color='#4C78A8')
        axes[row, 0].plot(g.cutoff_year, g.degree_reference_gain, label='Referência proporcional ao grau', color='#F58518', linestyle='--')
        axes[row, 0].set(title=title, ylabel='Novos vizinhos', xlabel='Ano'); axes[row, 0].legend(frameon=False, fontsize=8)
        axes[row, 1].plot(g.cutoff_year, g.annual_mention_news, label='Notícias com menção (NER)', color='#54A24B')
        axes[row, 1].plot(g.cutoff_year, g.annual_relation_news, label='Notícias com participação na rede', color='#4C78A8')
        axes[row, 1].set(title='Exposição documental observada', ylabel='Notícias distintas', xlabel='Ano'); axes[row, 1].legend(frameon=False, fontsize=8)
        for ax in axes[row]: ax.grid(alpha=.2)
    save(fig, '04_casos_e_exposicao', 'Contextualizar os casos por ganhos, referência e exposição.',
         'Casos configurados por ID e mantidos separados segundo a resolução existente. O painel começa na primeira '
         'transição elegível, após a entrada do nó. A referência proporcional não é previsão ajustada. '
         'Notícias com NER podem não ter RE concluída. Consulte casos_noticias.csv.gz para títulos e links completos.')
    return pd.DataFrame(catalog)


NOTAS = '''# Grau anterior e aquisição de novos vizinhos

Pergunta: entidades já presentes com maior grau em t−1 adquirem mais
vizinhos distintos no ano t? Unidade: entidade × transição anual. São
31 transições, de 1994→1995 até 2024→2025. O estoque de 1994 não é um
ganho observado. Entrantes são auditados, mas não entram como nós com
grau anterior zero; todos os nós anteriores permanecem, inclusive com
ganho zero e sem notícia observada no ano. O grau é o da projeção simples
não dirigida. Reforço soma ocorrências em pares que já existiam.

Referências de alocação, entre n nós anteriores com ganho total G:
uniforme U_i=G/n; proporcional D_i=G*k_i/soma(k). Ambas conservam G.
Não são modelos geradores de grafos, não impõem restrições de pares e
não são testes nulos probabilísticos. Não incorporam saturação: cada nó
tem no máximo N_t−1−k_i vizinhos novos possíveis. Comparações por faixa
fixa informam número de nós, média de ganho, chance empírica de ganho
positivo e participações. Não se ajusta regressão log-log nem expoente
de conexão preferencial. Ganho normalizado divide pela média anual
de ganho entre nós anteriores. Ano sem ganhos produz valor ausente.

Spearman usa postos médios nos empates e não fornece p-valor ou intervalo
de confiança iid. Ano sem variação produz INSUFFICIENT_VARIATION, não
evidência de ausência de associação. Cada ano é analisado separadamente;
não se agregam linhas de anos distintos para inferência independente.
Comparações por tipo e subconjuntos com ≥1 e ≥5 notícias com menção são
sensibilidades. Estratos de tipo, idade na rede (0–2, 3–9, 10+) e menções
(0, 1, 2–4, 5+) são descritivos; seus cortes não têm validade universal.
Exposição é contemporânea ao ganho e pode participar do mecanismo; não
é controle causal. Estratos pequenos ou constantes ficam identificados.
Idade é tempo desde a primeira aparição nesta rede, não idade real.

Cobertura de RE, volume de notícias, extrações parciais, tipo de entidade,
antiguidade, diferenças de exposição e resolução de entidades podem
afetar a associação. A normalização anual não corrige seleção de notícias
nem lacunas de extração. Em 2021, sem RE concluída nesta edição, ausência
de ganho não representa ausência de novas relações no noticiário.

O caso utiliza todos os anos elegíveis. Comparadores no mesmo estrato
incluem o próprio caso e não formam grupo de controle independente.
Estados Unidos e EUA não são fundidos nem reclassificados. Os títulos,
links e atributos das notícias são preservados no arquivo dos casos;
uma menção não garante participação em relação retida.

Uma associação positiva é compatível com vantagem cumulativa observada,
mas não identifica causalidade, não comprova conexão preferencial linear
nem Efeito Mateus sociológico. Concentração, cauda dos graus, persistência
e associação temporal respondem a perguntas diferentes.

Referência: Jeong, Néda e Barabási (2003), Measuring preferential attachment
in evolving networks, EPL 61, 567–572. DOI: 10.1209/epl/i2003-00166-9.
A análise utiliza cortes anuais agregados; não reproduz a sequência
intra-anuais de ligação usada em modelos de crescimento.
'''


def analisar_vantagem_cumulativa(projeto, *, executar=False, assinatura_protagonismo_esperada=None):
    start = perf_counter(); root = Path(projeto).resolve()
    if root.name == 'PROJECT_EXTRACAO': raise ValueError('Use o projeto de análise.')
    origem, meta = carregar_trajetorias(root, assinatura_protagonismo_esperada)
    series, smeta = carregar_redes_temporais(root, meta['network_snapshot_sha256'])
    if smeta['snapshot_sha256'] != meta['temporal_snapshot_sha256']:
        raise ValueError('Trajetórias e cobertura pertencem a séries diferentes.')
    cases = list(meta['configured_case_ids'])
    if not cases: raise ValueError('Configure casos na análise de protagonismo.')
    if not executar:
        out = {'mode': 'DRY_RUN', 'annual_transitions': 31, 'configured_case_ids': cases,
            'include_zero_gains': True, 'baseline_1994_excluded': True, 'api_calls': 0,
            'neo4j_connections': 0, 'files_written': 0}
        print('[VANTAGEM]', json.dumps(out)); return out
    spec = {'schema': 'temporal-degree-gain-association-1', 'version': VERSION,
        'code_sha256': sha(Path(__file__)), 'protagonism_snapshot_sha256': meta['snapshot_sha256'],
        'temporal_snapshot_sha256': smeta['snapshot_sha256'], 'configured_case_ids': cases,
        'numpy_version': np.__version__, 'pandas_version': pd.__version__}
    signature = json_sha(spec); base = root/'resultados/temporal/vantagem'; base.mkdir(parents=True, exist_ok=True)
    target = base/signature[:20]; lock = base/'analise.lock'; temp = None
    try: lock.mkdir()
    except FileExistsError: raise RuntimeError('Análise pode estar ativa; confira o bloqueio antes de retomar.') from None
    try:
        if target.exists():
            saved = validate_manifest(target)
            if saved['snapshot_sha256'] != signature: raise ValueError('Resultado incompatível.')
            summary = saved['summary']
        else:
            temp = Path(tempfile.mkdtemp(prefix='.vantagem_', dir=base))
            data = pd.read_csv(origem/'trajetorias_entidades.csv.gz')
            coverage = pd.read_csv(series/'cobertura_anual.csv')
            panel, audit = preparar_painel(data, coverage)
            associations = resumir_associacoes(panel); bins = resumir_faixas(panel)
            strata = resumir_estratos(panel); case_table = estudar_casos(panel, cases)
            links = pd.read_csv(origem/'casos_noticias.csv.gz')
            if set(cases)-set(links.entity_group_id): raise ValueError('Documentos dos casos ausentes.')
            for year, g in panel.groupby('cutoff_year'):
                print(f'[VANTAGEM] {year-1}→{year}: {len(g):,} entidades anteriores; '
                      f'{int(g.new_neighbors.sum()):,} ganhos; zeros preservados.', flush=True)
            for name, table in [('painel_transicoes.csv.gz', panel), ('auditoria_transicoes.csv', audit),
                ('associacoes_anuais.csv', associations), ('ganhos_por_faixa.csv', bins),
                ('associacoes_por_estrato.csv', strata), ('casos_transicoes.csv', case_table)]:
                write_csv(temp, name, table)
            shutil.copyfile(origem/'casos_noticias.csv.gz', temp/'casos_noticias.csv.gz')
            catalog = gerar_figuras(temp, associations, bins, audit, case_table)
            write_csv(temp, 'catalogo_figuras.csv', catalog)
            summary = {'annual_transitions': len(audit), 'entity_transition_rows': len(panel),
                'zero_gain_rows': int(panel.new_neighbors.eq(0).sum()), 'association_rows': len(associations),
                'stratum_rows': len(strata), 'configured_case_ids': cases, 'figure_files': len(catalog),
                'all_degree_gains_verified': True, 'all_previous_nodes_included': True,
                'year_without_completed_re': audit.loc[audit.no_completed_re_in_year, 'cutoff_year'].tolist(),
                'association_analysis_completed': True, 'causality_identified': False,
                'preferential_attachment_exponent_fitted': False, 'iid_p_values_computed': False,
                'api_calls': 0, 'neo4j_connections': 0, 'database_writes': 0,
                'entity_groups_merged': 0, 'network_modified': False}
            (temp/'LEIA_ME.md').write_text(NOTAS, encoding='utf-8')
            if carregar_trajetorias(root, assinatura_protagonismo_esperada)[1]['snapshot_sha256'] != meta['snapshot_sha256']:
                raise ValueError('Protagonismo mudou durante a análise.')
            if carregar_redes_temporais(root, meta['network_snapshot_sha256'])[1]['snapshot_sha256'] != smeta['snapshot_sha256']:
                raise ValueError('Série temporal mudou durante a análise.')
            atomic_json(temp/'manifesto.json', {**spec, 'snapshot_sha256': signature, 'summary': summary,
                'created_at_utc': datetime.now(timezone.utc).isoformat(),
                'outputs_sha256': {p.name: sha(p) for p in sorted(temp.iterdir())}})
            validate_manifest(temp); temp.rename(target); temp = None
        atomic_json(base/'atual.json', {'folder': target.name, 'snapshot_sha256': signature})
    finally:
        if temp is not None and temp.exists(): shutil.rmtree(temp)
        lock.rmdir()
    package = base/f'Resumo_Vantagem_Cumulativa_{signature[:12]}_{uuid.uuid4().hex[:6]}.zip'
    with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(target.iterdir()): z.write(p, p.name)
    print('[VANTAGEM]', json.dumps(summary, ensure_ascii=False)); print('[VANTAGEM] Pacote:', package)
    return {**summary, 'elapsed_seconds_this_run': perf_counter()-start,
            'output_directory': target, 'package': package, 'snapshot_sha256': signature}
