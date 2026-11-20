"""Formação e reforço de pares de entidades em redes acumuladas."""
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
from temporal_redes import carregar_redes_temporais, ANOS
from redes_construcao import carregar_rede
from re_consolidacao import sha, json_sha, write_csv, validate_manifest
from re_execucao import atomic_json

VERSION = '1.0.0'
CATEGORIAS = ('NEW_NEW', 'OLD_NEW', 'OLD_OLD')
CORES = {'NEW_NEW': 'tab:blue', 'OLD_NEW': 'tab:orange', 'OLD_OLD': 'tab:green'}
ROTULOS = {'NEW_NEW': 'Nova–nova', 'OLD_NEW': 'Antiga–nova', 'OLD_OLD': 'Antiga–antiga'}
COLUNAS = ['previous_year', 'cutoff_year', 'pair_id', 'source_id', 'target_id',
    'event_type', 'endpoint_class', 'previous_weight', 'current_weight',
    'added_occurrences', 'previous_news_count', 'current_news_count', 'added_support_news']


def _pares(frame, nodes):
    f = frame.copy()
    for col in ['source_id', 'target_id', 'weight', 'distinct_news_count']:
        v = pd.to_numeric(f[col], errors='raise')
        if v.isna().any() or not v.mod(1).eq(0).all(): raise ValueError('Contagem ou ID não inteiro: '+col)
        f[col] = v.astype('int64')
    if f.pair_id.duplicated().any() or f[['source_id', 'target_id']].duplicated().any():
        raise ValueError('Par duplicado.')
    if not f.source_id.lt(f.target_id).all() or not f.weight.gt(0).all() or not f.distinct_news_count.gt(0).all():
        raise ValueError('Par não canônico, autolaço ou contagem inválida.')
    if not (set(f.source_id) | set(f.target_id)).issubset(nodes): raise ValueError('Par com entidade desconhecida.')
    return f.set_index('pair_id')


def classificar_transicao(previous_nodes, previous_pairs, current_nodes, current_pairs, previous_year, year):
    """Classifica novidade dos pares e separa os incrementos de peso já existentes."""
    if year <= previous_year: raise ValueError('Transição temporal inválida.')
    previous_nodes, current_nodes = set(map(int, previous_nodes)), set(map(int, current_nodes))
    if not previous_nodes.issubset(current_nodes): raise ValueError('Entidades desapareceram na acumulação.')
    p, c = _pares(previous_pairs, previous_nodes), _pares(current_pairs, current_nodes)
    if not set(p.index).issubset(c.index): raise ValueError('Pares desapareceram na acumulação.')
    for col in ['source_id', 'target_id']:
        if not p[col].equals(c.loc[p.index, col]): raise ValueError('Identificador de par mudou de extremidades.')
    for col in ['weight', 'distinct_news_count']:
        if (c.loc[p.index, col].to_numpy() < p[col].to_numpy()).any(): raise ValueError('Contagem acumulada diminuiu.')
    novos_nos = current_nodes-previous_nodes
    linhas = []; counts = dict.fromkeys(CATEGORIAS, 0); reforcados = 0
    peso_novos = peso_antigos = 0
    for row in c.sort_index().itertuples():
        novo = row.Index not in p.index
        old_weight = 0 if novo else int(p.loc[row.Index, 'weight'])
        old_news = 0 if novo else int(p.loc[row.Index, 'distinct_news_count'])
        delta = int(row.weight)-old_weight
        if not delta: continue
        if novo:
            n = int(row.source_id in novos_nos)+int(row.target_id in novos_nos)
            classe = 'NEW_NEW' if n == 2 else 'OLD_NEW' if n == 1 else 'OLD_OLD'
            counts[classe] += 1; peso_novos += delta
        else:
            classe = 'EXISTING_PAIR'; reforcados += 1; peso_antigos += delta
        linhas.append([previous_year, year, row.Index, row.source_id, row.target_id,
            'NEW_PAIR' if novo else 'REINFORCED_PAIR', classe, old_weight, int(row.weight), delta,
            old_news, int(row.distinct_news_count), int(row.distinct_news_count)-old_news])
    total = len(c)-len(p)
    if sum(counts.values()) != total or peso_novos+peso_antigos != int(c.weight.sum()-p.weight.sum()):
        raise ValueError('A classificação não recompõe os incrementos.')
    resumo = {'previous_year': previous_year, 'cutoff_year': year,
        'interval_calendar_years': year-previous_year, 'new_nodes': len(novos_nos),
        'new_pairs': total, **{key.lower(): value for key, value in counts.items()},
        **{'share_'+key.lower(): value/total if total else None for key, value in counts.items()},
        'reinforced_pairs': reforcados, 'unchanged_previous_pairs': len(p)-reforcados,
        'occurrences_new_pairs': peso_novos, 'occurrences_existing_pairs': peso_antigos,
        'added_occurrences': peso_novos+peso_antigos, 'classification_verified': True}
    return pd.DataFrame(linhas, columns=COLUNAS), resumo


def preparar_proveniencia(final):
    """Recompõe pesos por par e documento a partir das arestas semânticas."""
    ler = lambda n: pd.read_csv(final/n, dtype=str, keep_default_na=False)
    evidence, links, news = [ler(n) for n in ['arestas_noticias.csv.gz', 'vinculos_arestas_projecoes.csv.gz', 'noticias.csv.gz']]
    if links.edge_id.duplicated().any() or news.news_id.duplicated().any(): raise ValueError('Proveniência ambígua.')
    mapped = evidence.merge(links[['edge_id', 'pair_id']], on='edge_id', how='left', validate='many_to_one')
    if mapped.pair_id.isna().any(): raise ValueError('Aresta sem par canônico.')
    mapped['occurrence_count'] = pd.to_numeric(mapped.occurrence_count, errors='raise').astype('int64')
    keys = ['pair_id', 'news_id', 'news_version_id']
    support = mapped.groupby(keys, as_index=False).occurrence_count.sum()
    support = support.merge(news[['news_id', 'news_version_id', 'publication_year']],
        on=['news_id', 'news_version_id'], how='left', validate='many_to_one')
    if support.publication_year.isna().any(): raise ValueError('Suporte sem versão documental.')
    support['publication_year'] = pd.to_numeric(support.publication_year, errors='raise').astype('int64')
    return support, news.loc[news.news_id.isin(support.news_id)].copy()


def conferir_suporte(eventos, suporte, inicio, fim):
    s = suporte.loc[suporte.publication_year.gt(inicio) & suporte.publication_year.le(fim)]
    expected = s.groupby('pair_id').agg(occurrences=('occurrence_count', 'sum'), news=('news_id', 'nunique'))
    got = eventos.set_index('pair_id')
    if set(expected.index) != set(got.index): raise ValueError('Pares ativos diferem do suporte documental do intervalo.')
    if len(got) and (not expected.loc[got.index, 'occurrences'].eq(got.added_occurrences).all()
                    or not expected.loc[got.index, 'news'].eq(got.added_support_news).all()):
        raise ValueError('Incrementos não recompõem a proveniência por par e documento.')


def adicionar_cobertura(rows, annual):
    saida = []
    for row in rows:
        a = annual.loc[annual.publication_year.gt(row['previous_year']) & annual.publication_year.le(row['cutoff_year'])]
        r = dict(row)
        for col in ['corpus_news', 're_completed_strict', 're_partial', 'support_news', 'retained_occurrences']:
            r['interval_'+col] = int(a[col].sum())
        if r['added_occurrences'] != r['interval_retained_occurrences']: raise ValueError('Peso diferente da cobertura.')
        r['network_evidence_available'] = r['interval_support_news'] > 0
        for classe in CATEGORIAS:
            for denominator in ['corpus_news', 'support_news']:
                d = r['interval_'+denominator]
                r[classe.lower()+'_per_'+denominator] = r[classe.lower()]/d if d else None
        saida.append(r)
    return pd.DataFrame(saida)


def carregar_estrutura(projeto, temporal_sha, assinatura_esperada=None):
    base = Path(projeto)/'resultados/temporal/estrutural'
    ptr = json.loads((base/'atual.json').read_text(encoding='utf-8'))
    if Path(ptr['folder']).name != ptr['folder']: raise ValueError('Índice estrutural inválido.')
    folder = base/ptr['folder']; meta = validate_manifest(folder)
    if meta['snapshot_sha256'] != ptr['snapshot_sha256'] or meta['temporal_snapshot_sha256'] != temporal_sha:
        raise ValueError('Edição estrutural incompatível com a série temporal.')
    if assinatura_esperada and meta['snapshot_sha256'] != assinatura_esperada: raise ValueError('Análise estrutural inesperada.')
    for y, h in meta['cutoff_manifests_sha256'].items():
        if sha(folder/y/'manifesto.json') != h: raise ValueError('Manifesto estrutural alterado.')
        validate_manifest(folder/y)
    return folder, meta


def gerar_figuras(folder, annual, reference):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size': 10, 'svg.fonttype': 'none', 'pdf.fonttype': 42})
    catalogo = []
    def salvar(fig, nome, objetivo, legenda):
        fig.tight_layout()
        for ext in ['svg', 'png', 'pdf']:
            file = nome+'.'+ext; fig.savefig(Path(folder)/file, dpi=300, bbox_inches='tight')
            catalogo.append({'file': file, 'objective': objetivo, 'caption': legenda})
        plt.close(fig)
    def composicao(t, nome, legenda):
        fig, ax = plt.subplots(figsize=(9, max(6, .30*len(t)+1.8)))
        left = np.zeros(len(t)); positions = np.arange(len(t))
        for classe in CATEGORIAS:
            v = 100*pd.to_numeric(t['share_'+classe.lower()], errors='coerce').fillna(0).to_numpy()
            ax.barh(positions, v, left=left, label=ROTULOS[classe], color=CORES[classe]); left += v
        for i, row in enumerate(t.itertuples()):
            if row.new_pairs == 0: ax.text(2, i, 'Sem pares novos', va='center', fontsize=8)
        labels = [f'{int(r.previous_year)}→{int(r.cutoff_year)}' for r in t.itertuples()]
        ax.set_yticks(positions, labels); ax.invert_yaxis()
        ax.set(xlim=(0, 100), xlabel='Participação nos pares novos (%)', ylabel='Intervalo entre cortes')
        ax.legend(frameon=False, loc='lower left', bbox_to_anchor=(0, 1.01), ncol=3)
        ax.grid(axis='x', alpha=.2); ax.set_axisbelow(True)
        salvar(fig, nome, 'Distinguir expansão por entrada de entidades e conexões entre entidades já observadas.', legenda)
    composicao(annual, '01_composicao_pares_anuais',
        'Pares novos classificados pela presença de seus extremos na rede acumulada anterior. '
        'Cada par não dirigido conta uma vez, independentemente de rótulo e direção. '
        'A primeira rede, de 1994, é o estoque inicial e não uma transição. Barras vazias não têm percentuais definidos; '
        'consulte a cobertura antes de interpretar ausência de novidade.')
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for ax, denominator, label in zip(axes, ['corpus_news', 'support_news'], ['Corpus anual', 'Suporte relacional anual']):
        for classe in CATEGORIAS:
            v = annual[classe.lower()+'_per_'+denominator].where(annual.network_evidence_available)
            ax.plot(annual.cutoff_year, v, marker='o', markersize=3, color=CORES[classe], label=ROTULOS[classe])
        ax.set_ylabel('Pares novos / notícia'); ax.set_title('Denominador: '+label.lower())
        ax.legend(frameon=False); ax.grid(alpha=.2)
    axes[-1].set_xlabel('Ano limite'); axes[-1].set_xticks(list(range(1995, 2026, 2))); axes[-1].tick_params(axis='x', rotation=45)
    salvar(fig, '02_novos_pares_por_noticia', 'Comparar composição e volume da novidade estrutural.',
        'Razões de incrementos agregados por notícia do corpus e por notícia com relações retidas. '
        'Não representam médias de novidade calculadas individualmente por documento nem controlam o viés de seleção. '
        'Anos sem suporte relacional são lacunas nas curvas.')
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    axes[0].plot(annual.cutoff_year, annual.new_pairs, color='tab:blue', marker='o', markersize=3, label='Pares novos')
    axes[0].plot(annual.cutoff_year, annual.reinforced_pairs, color='tab:orange', marker='s', markersize=3, label='Pares anteriores com novas ocorrências')
    axes[0].set_ylabel('Pares distintos'); axes[0].legend(frameon=False)
    denominator = annual.added_occurrences.where(annual.added_occurrences.gt(0))
    a = 100*annual.occurrences_new_pairs/denominator
    b = 100*annual.occurrences_existing_pairs/denominator
    axes[1].bar(annual.cutoff_year, a, color='tab:blue', label='Em pares novos')
    axes[1].bar(annual.cutoff_year, b, bottom=a, color='tab:orange', label='Em pares anteriores')
    axes[1].set(ylabel='Ocorrências do ano (%)', xlabel='Ano limite', ylim=(0, 105)); axes[1].legend(frameon=False)
    for ax in axes: ax.grid(alpha=.2); ax.set_axisbelow(True)
    axes[-1].set_xticks(list(range(1995, 2026, 2))); axes[-1].tick_params(axis='x', rotation=45)
    salvar(fig, '03_novidade_e_reforco', 'Separar aquisição de conexões e repetição de vínculos já observados.',
        'O painel superior conta pares distintos; o inferior distribui ocorrências retidas no intervalo. '
        'Um novo rótulo ou nova direção em um par já existente aumenta seu peso, mas não cria um par estrutural novo. '
        'Ocorrências não são relações factuais independentes. Intervalos sem ocorrências não têm composição percentual definida.')
    composicao(reference, '04_composicao_marcos_referencia',
        'Classificação recalculada diretamente entre os 19 cortes de referência. Os intervalos têm durações '
        'diferentes; as categorias não são obtidas somando as classificações anuais, pois a condição de entidade nova '
        'ou anterior depende da fronteira inicial. A comparação com os cortes anuais é sensível à agregação temporal.')
    return pd.DataFrame(catalogo)


def analisar_formacao_conexoes(projeto, *, executar=False, assinatura_rede_esperada=None,
                               assinatura_temporal_esperada=None, assinatura_estrutura_esperada=None):
    root = Path(projeto).resolve()
    if root.name == 'PROJECT_EXTRACAO': raise ValueError('Use o projeto de análise.')
    origem, meta = carregar_redes_temporais(root, assinatura_rede_esperada)
    if assinatura_temporal_esperada and meta['snapshot_sha256'] != assinatura_temporal_esperada: raise ValueError('Série temporal inesperada.')
    if carregar_rede(root)[1]['snapshot_sha256'] != meta['network_snapshot_sha256']: raise ValueError('Rede global ativa diferente da série.')
    estrutura, emeta = carregar_estrutura(root, meta['snapshot_sha256'], assinatura_estrutura_esperada)
    if not executar:
        out = {'mode': 'DRY_RUN', 'annual_transitions': 31, 'reference_transitions': 18,
            'baseline_year': 1994, 'new_pair_categories': list(CATEGORIAS),
            'separate_existing_pair_reinforcement': True, 'api_calls': 0, 'neo4j_connections': 0, 'files_written': 0}
        print('[CONEXÕES]', json.dumps(out)); return out
    inicio = perf_counter()
    spec = {'schema': 'temporal-pair-formation-1', 'version': VERSION, 'code_sha256': sha(Path(__file__)),
        'network_snapshot_sha256': meta['network_snapshot_sha256'], 'temporal_snapshot_sha256': meta['snapshot_sha256'],
        'structural_snapshot_sha256': emeta['snapshot_sha256'], 'cutoff_years': list(ANOS),
        'reference_cutoff_years': meta['reference_cutoff_years'], 'baseline_year': 1994,
        'newness_scope': 'retained relation endpoints in previous cumulative snapshot',
        'pair_projection': 'simple undirected; sum occurrence weights for reinforcement only'}
    signature = json_sha(spec); base = root/'resultados/temporal/conexoes'; base.mkdir(parents=True, exist_ok=True)
    destino = base/signature[:20]; lock = base/'analise.lock'
    try: lock.mkdir()
    except FileExistsError: raise RuntimeError('Análise pode estar ativa. Confira o bloqueio antes de retomar.') from None
    temp = None
    try:
        if destino.exists():
            saved = validate_manifest(destino)
            if saved['snapshot_sha256'] != signature: raise ValueError('Assinatura de resultado incompatível.')
            resumo = saved['summary']
        else:
            temp = Path(tempfile.mkdtemp(prefix='.conexoes_', dir=base))
            coverage = pd.read_csv(origem/'cobertura_anual.csv')
            structural = pd.read_csv(estrutura/'evolucao_estrutural_anual.csv').set_index('cutoff_year')
            support, news = preparar_proveniencia(origem/'2025')
            annual_rows = []; reference_rows = []; annual_events = []; reference_events = []
            previous_nodes = previous_pairs = None
            ref_nodes = ref_pairs = None; ref_year = None
            for year in ANOS:
                folder = origem/str(year)
                nos = pd.read_csv(folder/'nos.csv.gz', dtype=str, keep_default_na=False)
                pairs = pd.read_csv(folder/'ponderada_nao_dirigida.csv.gz', dtype=str, keep_default_na=False)
                nodes = set(nos.entity_group_id.astype(int)); checked = _pares(pairs, nodes)
                s = structural.loc[year]
                if len(nodes) != s.nodes or len(pairs) != s.simple_undirected_edges or int(checked.weight.sum()) != s.weight_sum:
                    raise ValueError('Dimensões diferentes da caracterização estrutural.')
                if year == 1994:
                    baseline = {'year': 1994, 'nodes': len(nodes), 'pairs': len(pairs), 'occurrences': int(checked.weight.sum())}
                    first = support.loc[support.publication_year.eq(1994)]
                    if first.occurrence_count.sum() != baseline['occurrences'] or first.pair_id.nunique() != len(pairs): raise ValueError('Estoque inicial incompatível.')
                else:
                    events, row = classificar_transicao(previous_nodes, previous_pairs, nodes, pairs, year-1, year)
                    conferir_suporte(events, support, year-1, year)
                    if row['new_nodes'] != len(nodes)-len(previous_nodes): raise ValueError('Incremento de nós incompatível.')
                    annual_events.append(events); annual_rows.append(row)
                    print(f'[CONEXÕES] {year-1}→{year}: {row["new_pairs"]:,} pares novos; '
                          f'{row["reinforced_pairs"]:,} pares anteriores reforçados; conferido.', flush=True)
                if year in meta['reference_cutoff_years']:
                    if ref_year is not None:
                        events, row = classificar_transicao(ref_nodes, ref_pairs, nodes, pairs, ref_year, year)
                        conferir_suporte(events, support, ref_year, year)
                        reference_events.append(events); reference_rows.append(row)
                    ref_nodes, ref_pairs, ref_year = nodes, pairs, year
                previous_nodes, previous_pairs = nodes, pairs
            annual = adicionar_cobertura(annual_rows, coverage)
            reference = adicionar_cobertura(reference_rows, coverage)
            if int(annual.new_pairs.sum())+baseline['pairs'] != len(pairs): raise ValueError('Novos pares não recompõem o último corte.')
            if int(annual.added_occurrences.sum())+baseline['occurrences'] != int(checked.weight.sum()): raise ValueError('Pesos não recompõem o último corte.')
            if int(reference.new_pairs.sum()) != int(annual.new_pairs.sum()): raise ValueError('Totais das duas resoluções diferem.')
            for name, table in [('formacao_anual.csv', annual), ('formacao_marcos_referencia.csv', reference),
                ('eventos_pares_anuais.csv.gz', pd.concat(annual_events, ignore_index=True)),
                ('eventos_pares_marcos_referencia.csv.gz', pd.concat(reference_events, ignore_index=True)),
                ('pares_noticias.csv.gz', support), ('noticias_suporte.csv.gz', news),
                ('catalogo_entidades.csv.gz', nos[['entity_group_id', 'entity_group_name', 'ent_label']])]:
                write_csv(temp, name, table)
            atomic_json(temp/'estoque_inicial.json', baseline)
            write_csv(temp, 'catalogo_figuras.csv', gerar_figuras(temp, annual, reference))
            resumo = {'annual_transitions': len(annual), 'reference_transitions': len(reference),
                'baseline': baseline, 'new_pairs_after_baseline': int(annual.new_pairs.sum()),
                'new_pair_categories': {c: int(annual[c.lower()].sum()) for c in CATEGORIAS},
                'reinforced_pair_intervals': int(annual.reinforced_pairs.sum()),
                'occurrences_new_pairs': int(annual.occurrences_new_pairs.sum()),
                'occurrences_existing_pairs': int(annual.occurrences_existing_pairs.sum()),
                'all_pair_increments_verified_against_news': True, 'figure_files': 12,
                'api_calls': 0, 'neo4j_connections': 0, 'database_writes': 0,
                'network_modified': False, 'cumulative_advantage_tested': False}
            (temp/'LEIA_ME.md').write_text(NOTAS, encoding='utf-8')
            if carregar_redes_temporais(root, assinatura_rede_esperada)[1]['snapshot_sha256'] != meta['snapshot_sha256']:
                raise ValueError('Série temporal alterada durante a análise.')
            if carregar_estrutura(root, meta['snapshot_sha256'], assinatura_estrutura_esperada)[1]['snapshot_sha256'] != emeta['snapshot_sha256']:
                raise ValueError('Resultados estruturais alterados durante a análise.')
            atomic_json(temp/'manifesto.json', {**spec, 'snapshot_sha256': signature, 'summary': resumo,
                'created_at_utc': datetime.now(timezone.utc).isoformat(),
                'outputs_sha256': {p.name: sha(p) for p in sorted(temp.iterdir())}})
            validate_manifest(temp); temp.rename(destino); temp = None
        atomic_json(base/'atual.json', {'folder': destino.name, 'snapshot_sha256': signature})
    finally:
        if temp is not None and temp.exists(): shutil.rmtree(temp)
        lock.rmdir()
    pacote = base/f'Resumo_Formacao_Conexoes_{signature[:12]}_{uuid.uuid4().hex[:6]}.zip'
    with zipfile.ZipFile(pacote, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(destino.iterdir()): z.write(p, p.name)
    out = {**resumo, 'elapsed_seconds_this_run': perf_counter()-inicio,
        'snapshot_sha256': signature, 'output_directory': destino, 'package': pacote}
    print('[CONEXÕES]', json.dumps({k: v for k, v in out.items() if k not in ['output_directory', 'package']}, ensure_ascii=False))
    print('[CONEXÕES] Pacote:', pacote)
    return out


NOTAS = '''# Formação de conexões

São comparadas 31 transições anuais e 18 transições entre os 19 marcos
de referência. A rede de 1994 é o estoque inicial, não uma transição
desde um ano previamente observado. Ambas as resoluções utilizam todas
as relações disponíveis no respectivo intervalo e o mesmo último corte.

Um par novo conecta duas entidades antes sem conexão na projeção simples
não dirigida. As classes nova–nova, antiga–nova e antiga–antiga dependem
da presença dos extremos na rede acumulada no início do intervalo. Nova
significa primeira presença como extremo de relação retida nesta edição,
não primeira menção no corpus nem surgimento histórico da entidade.

O reforço conta novas ocorrências em pares já existentes. Rótulos ou
direções adicionais em um par anterior não são pares novos. Os pesos
agregam registros retidos e podem incluir inversas e repetições; não são
contagens de fatos independentes nem escores de confiança semântica.

Categorias dos intervalos de referência são recalculadas nas suas próprias
fronteiras; não se somam as classes anuais para obter classes de intervalos
maiores. A mesma entidade pode ser nova em um intervalo de três anos e
antiga no segundo ou terceiro ano quando a resolução é anual. Isso altera
a composição das classes, mesmo com o mesmo conjunto final de pares.

Reforços somados entre intervalos contam par-intervalo, não pares únicos.
As proporções têm denominador igual ao número de pares novos; não são
probabilidades de conexão entre todos os pares possíveis de cada classe.
A quantidade de oportunidades é diferente entre as classes. Predomínio
de antiga–nova ou reforço não demonstra conexão preferencial ou Efeito
Mateus. Essa investigação requer grau anterior, exposição e comparação.

O suporte por par/documento recompõe integralmente os incrementos de peso
e notícias de cada transição. Use pair_id para chegar a pares_noticias.csv.gz,
depois news_id e news_version_id para noticias_suporte.csv.gz, que preserva
títulos, links e categorias. source_id e target_id identificam entidades
no catálogo. Um documento pode apoiar vários pares: não some as linhas
do suporte para obter o total de notícias distintas.

Razões por notícia são descritivas e não corrigem cobertura ou seleção.
Anos sem suporte são lacunas nas curvas de razões; ausência de pares novos
pode ocorrer mesmo com extração disponível. A classificação utiliza apenas
arquivos persistidos, sem Neo4j, NER, RE ou novas resoluções de entidades.
Os resultados da rede global e das outras etapas permanecem preservados.
'''
