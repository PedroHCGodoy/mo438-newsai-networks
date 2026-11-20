"""Análise documental e estrutural offline, sem alterar redes ou partições.

Uso a partir de PROJECT:
    python ferramentas/analisar_entidades_relatorio.py
Entradas congeladas em relatorio/entradas_entidades; saídas em relatorio/analise_entidades.
Requer pandas, numpy e matplotlib. Nenhuma chamada de API ou conexão Neo4j.
"""
import hashlib
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def analisar(project):
    base = Path(project) / 'relatorio'
    inp, out = base / 'entradas_entidades', base / 'analise_entidades'
    out.mkdir(parents=True, exist_ok=True)
    c = pd.read_csv(inp / 'centralidades.csv.gz')
    a = pd.read_csv(inp / 'arestas.csv.gz')
    d = pd.read_csv(inp / 'participacoes_documentais.csv.gz')
    f = pd.read_csv(inp / 'formacao_anual.csv')
    # Cada linha é uma entidade em uma notícia com participação relacional.
    assert not d.duplicated(['entity_group_id', 'news_id']).any()
    assert (d.relation_participation_count > 0).all()
    counts = d.groupby('entity_group_id').news_id.nunique().sort_index()
    assert counts.equals(c.set_index('entity_group_id').relation_news_count.sort_index())
    assert len(c) == 40627 and d.news_id.nunique() == 9113
    assert int(a.weight.sum()) == 181348
    assert int(c.neighbor_degree.sum()) == 115072
    assert int(c.weighted_strength.sum()) == 362696
    n_docs, total = int(d.news_id.nunique()), int(counts.sum())
    c['percentual_noticias_rede'] = 100 * c.relation_news_count / n_docs
    top = c.sort_values(['neighbor_degree', 'entity_group_id'], ascending=[False, True]).head(6)
    cases = pd.concat([
        g.sort_values(['neighbor_degree', 'entity_group_id'], ascending=[False, True]).head(2)
        for _, g in c.groupby('ent_label')
    ])
    top.to_csv(out / 'seis_lideres_grau.csv', index=False)
    cases.to_csv(out / 'seis_casos_por_tipo.csv', index=False)
    names = c.set_index('entity_group_id').entity_group_name
    rows = []
    for entity_id in cases.entity_group_id:
        incident = a[(a.source_id == entity_id) | (a.target_id == entity_id)].copy()
        incident['neighbor_id'] = np.where(incident.source_id == entity_id, incident.target_id, incident.source_id)
        for neighbor, weight in incident.groupby('neighbor_id').weight.sum().sort_values(ascending=False).head(3).items():
            rows.append({'entity_group_id': int(entity_id), 'entity_group_name': names[entity_id],
                         'neighbor_id': int(neighbor), 'neighbor_name': names[neighbor], 'weight': int(weight)})
    pd.DataFrame(rows).to_csv(out / 'vizinhos_mais_recorrentes.csv', index=False)
    c.sort_values(['relation_news_count', 'entity_group_id'], ascending=[False, True]).to_csv(out / 'visibilidade_documental.csv.gz', index=False)
    ordered = c.sort_values(['relation_news_count', 'entity_group_id'], ascending=[False, True])
    concentration = []
    for fraction in (.01, .05, .1):
        size = math.ceil(len(c) * fraction)
        incidences = int(ordered.head(size).relation_news_count.sum())
        concentration.append({'fraction_requested': fraction, 'entities': size,
                              'entity_news_incidences': incidences, 'share_incidences': incidences / total})
    values = np.sort(counts.to_numpy())
    gini = float(2 * np.arange(1, len(values) + 1) @ values / (len(values) * values.sum()) - (len(values) + 1) / len(values))
    # Checagem por integração da curva de Lorenz, por procedimento distinto.
    lorenz = np.r_[0, np.cumsum(values) / values.sum()]
    pop = np.linspace(0, 1, len(values) + 1)
    assert abs(gini - (1 - 2 * np.trapezoid(lorenz, pop))) < 1e-12
    classes = f[['new_new', 'old_new', 'old_old']].sum().to_numpy(dtype=int)
    assert classes.tolist() == [13700, 18611, 4703]
    summary = {'network_entities': len(c), 'network_news': n_docs,
               'entity_news_incidences': total, 'gini_documentary_visibility': gini,
               'concentration': concentration, 'case_selection': 'two highest degrees per type; entity_group_id ascending for ties',
               'visibility_definition': 'distinct news with retained relational participation; one count per entity-news pair',
               'overlap_note': 'A news item may count for several entities; shares of news must not be summed.',
               'new_pairs_classes': classes.tolist(),
               'input_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inp.iterdir()) if p.is_file()}}
    (out / 'resumo.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    pd.DataFrame(concentration).to_csv(out / 'concentracao_visibilidade.csv', index=False)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11, 'pdf.fonttype': 42,
                         'axes.spines.top': False, 'axes.spines.right': False})
    fig, ax = plt.subplots(figsize=(6.6, 2.2), layout='constrained')
    ax.plot(100 * pop, 100 * lorenz, color='#245b86', lw=2, label='Visibilidade observada')
    ax.plot([0, 100], [0, 100], '--', color='#808080', label='Distribuição igualitária')
    ax.set(xlabel='Entidades, da menor para a maior visibilidade (%)', ylabel='Aparições entidade–notícia (%)', xlim=(0, 100), ylim=(0, 100))
    ax.legend(loc='upper left', frameon=False)
    fig.savefig(base / 'figuras' / 'visibilidade.pdf')
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(6.6, 2.1), layout='constrained')
    labels = ['Nova–nova', 'Antiga–nova', 'Antiga–antiga']
    shares = 100 * classes / classes.sum()
    ax.barh(labels[::-1], shares[::-1], color=['#8ca6bb', '#245b86', '#60a195'][::-1], height=.56)
    for y, (number, share) in enumerate(zip(classes[::-1], shares[::-1])):
        value = f'{int(number):,}'.replace(',', '.')
        percentage = f'{share:.2f}'.replace('.', ',')
        ax.text(share + 1, y, f'{value} | {percentage}%', va='center', fontsize=11)
    ax.set(xlabel='Participação nos pares novos (%)', xlim=(0, 69))
    ax.set_xticks([0, 10, 20, 30, 40, 50, 60])
    fig.savefig(base / 'figuras' / 'connections.pdf')
    plt.close(fig)
    figuras_relatorio(base, c)
    trajetorias(base)
    return summary


def figuras_relatorio(base, centralities):
    """Redesenha as demais figuras com letras legíveis no tamanho impresso."""
    evidence = base / 'evidencias'
    plt.rcParams.update({'font.size': 11, 'axes.labelsize': 11, 'legend.fontsize': 10,
                         'xtick.labelsize': 10, 'ytick.labelsize': 10})

    def save(fig, name):
        fig.savefig(base / 'figuras' / f'{name}.pdf')
        plt.close(fig)

    def ccdf(degrees):
        frequencies = pd.Series(degrees).value_counts().sort_index()
        return frequencies.index.to_numpy(), frequencies.iloc[::-1].cumsum().iloc[::-1].to_numpy() / frequencies.sum()

    fig, ax = plt.subplots(figsize=(6.6, 2.7), layout='constrained')
    x, y = ccdf(centralities.neighbor_degree)
    ax.loglog(x, y, '.', color='#245b86', markersize=3)
    ax.set(xlabel='Grau (vizinhos distintos)', ylabel='P(K ≥ k)')
    save(fig, 'global_ccdf')

    source_degrees = pd.read_csv(evidence / 'sources/distribuicoes_graus.csv')
    fig, ax = plt.subplots(figsize=(6.6, 2.5), layout='constrained')
    colors = {'cnn': '#245b86', 'folha': '#c06528', 'g1': '#328754'}
    labels = {'cnn': 'CNN Brasil', 'folha': 'Folha', 'g1': 'G1'}
    for source, group in source_degrees.groupby('source'):
        group = group.sort_values('degree')
        y = group['count'].iloc[::-1].cumsum().iloc[::-1] / group['count'].sum()
        ax.loglog(group.degree, y, label=labels[source], color=colors[source], lw=1.5)
    ax.set(xlabel='Grau (vizinhos distintos)', ylabel='P(K ≥ k)')
    ax.legend(frameon=False)
    save(fig, 'sources_ccdf')

    coverage = pd.read_csv(evidence / 'temporal/cobertura_anual.csv')
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.8), layout='constrained')
    axes[0].plot(coverage.publication_year, coverage.cumulative_nodes / 1000, label='Entidades', color='#245b86')
    axes[0].plot(coverage.publication_year, coverage.cumulative_undirected_pairs / 1000, label='Pares', color='#c06528')
    axes[0].set(ylabel='Quantidade acumulada (mil)', xlabel='Ano')
    axes[0].legend(frameon=False, loc='upper left')
    axes[1].plot(coverage.publication_year, 100 * coverage.strict_completion_share, '.-', color='#328754')
    axes[1].set(ylabel='Notícias com RE concluída (%)', xlabel='Ano', ylim=(-4, 104))
    for ax in axes:
        ax.set_xticks([1994, 2005, 2015, 2025])
    save(fig, 'temporal_growth')

    tail = pd.read_csv(evidence / 'tails/distribuicoes_graus.csv')
    tail = tail[tail.cutoff_year == 2025]
    curve = pd.read_csv(evidence / 'tails/curva_ajustada_2025.csv')
    fig, ax = plt.subplots(figsize=(6.6, 2.6), layout='constrained')
    ax.loglog(tail.degree, tail.ccdf_ge_k, '.', color='#245b86', label='Graus observados', markersize=3)
    ax.loglog(curve.degree, curve.ccdf_power_law_scaled, color='#c06528', label='Lei de potência: k ≥ 2', lw=1.5)
    ax.set(xlabel='Grau (vizinhos distintos)', ylabel='P(K ≥ k)')
    ax.legend(frameon=False)
    save(fig, 'tail')

    associations = pd.read_csv(evidence / 'advantage/associacoes_anuais.csv')
    selected = associations[(associations.entity_type == 'ALL') & (associations.scope == 'ALL_PREEXISTING') & (associations.outcome == 'new_neighbors')].sort_values('cutoff_year')
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.8), layout='constrained')
    axes[0].plot(selected.cutoff_year, selected.spearman_rho, '.-', color='#245b86')
    axes[0].set(xlabel='Ano de chegada dos ganhos', ylabel='Correlação de Spearman', ylim=(0, .35))
    axes[1].plot(coverage.publication_year, 100 * coverage.strict_completion_share, '.-', color='#328754')
    axes[1].set(xlabel='Ano', ylabel='Notícias com RE concluída (%)', ylim=(-4, 104))
    for ax in axes:
        ax.set_xticks([1995, 2005, 2015, 2025])
    save(fig, 'advantage')


def trajetorias(base):
    data = pd.read_csv(base / 'entradas_entidades/trajetorias_seis_entidades.csv')
    years = np.arange(1994, 2026)
    groups = [('LOCAL', 'Locais'), ('ORGANIZACAO', 'Organizações'), ('PESSOA', 'Pessoas')]
    fig, axes = plt.subplots(3, 1, figsize=(6.6, 4.8), sharex=True, layout='constrained')
    for ax, (kind, label) in zip(axes, groups):
        for idx, (entity_id, d) in enumerate(data[data.ent_label == kind].groupby('entity_group_id')):
            d = d.sort_values('cutoff_year')
            # Ausência antes da entrada não é imputada como grau zero.
            degree = d.set_index('cutoff_year').degree.reindex(years)
            name = d.entity_group_name.iloc[0].replace('Universidade de São Paulo', 'USP').replace('Luiz Inácio Lula da Silva', 'Lula')
            ax.plot(years, degree, color=['#245b86', '#c06528'][idx], label=name, lw=1.7)
        ax.axvspan(2020.5, 2021.5, color='#dddddd', alpha=.8)
        ax.set_ylabel('Grau')
        ax.set_title(label, fontsize=10, loc='left', pad=1)
        ax.legend(loc='upper left', frameon=False, fontsize=9, ncols=2)
        ax.set_ylim(bottom=0)
    axes[-1].set_xticks([1994, 2000, 2005, 2010, 2015, 2020, 2025])
    axes[-1].set_xlabel('Ano do corte acumulado da Folha')
    fig.savefig(base / 'figuras/trajetorias_seis.pdf')
    plt.close(fig)
    data[data.cutoff_year.isin([2013, 2019, 2024, 2025])][['entity_group_id', 'entity_group_name', 'cutoff_year', 'degree', 'degree_rank', 'annual_relation_news']].to_csv(base / 'analise_entidades/trajetorias_marcos.csv', index=False)


if __name__ == '__main__':
    print(json.dumps(analisar(Path(__file__).resolve().parents[1]), ensure_ascii=False, indent=2))
