"""Evolução estrutural anual com cálculo GDS e conferência independente."""
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
from fontes_estrutural import PROJETAR as PROJETAR_FONTE, query, verificar_metricas
from redes_estrutural import executar_algoritmos, resumir_metricas
from redes_projecoes import verificar_projecao, valores_esperados, EXISTS
from neo4j_integracao import _configuration, _failure
from re_consolidacao import sha, json_sha, write_csv, validate_manifest
from re_execucao import atomic_json

VERSION = '1.0.0'
PROJETAR = PROJETAR_FONTE.replace('readConcurrency:4', 'readConcurrency:1')


def calcular_corte(session, nome, database, tag, nos, simples, arestas):
    """Cria uma projeção própria e sempre tenta liberar somente esse nome."""
    try:
        rows = [{'source_id': int(a), 'target_id': int(b)}
                for a, b in zip(simples.source_id, simples.target_id)]
        session.run(PROJETAR, rows=rows, tag=tag, name=nome).consume()
        info = verificar_projecao(session, nome, database, tag,
            set(nos.entity_group_id.astype(int)), valores_esperados('structural', arestas, simples))
        raw, estimates, tempos = executar_algoritmos(session, nome)
        f, componentes, graus, tamanhos, clustering, metricas = verificar_metricas(raw, nos, simples)
        n = nos[['entity_group_id', 'entity_group_name', 'ent_label']].copy()
        n['entity_group_id'] = n.entity_group_id.astype(int)
        f = f.merge(n, on='entity_group_id', validate='one_to_one')
        return {'metricas_nos.csv.gz': f, 'componentes.csv': componentes,
            'distribuicao_graus.csv': graus, 'tamanhos_componentes.csv': tamanhos,
            'clusterizacao.csv': clustering}, metricas, {
                'projection': info, 'estimates': estimates, 'algorithm_times_s': tempos}
    finally:
        if query(session, EXISTS, name=nome)[0]['exists']:
            session.run('CALL gds.graph.drop($name) YIELD graphName RETURN graphName', name=nome).consume()
            print('[ESTRUTURA TEMPORAL] PROJEÇÃO LIBERADA —', nome, flush=True)


def calcular_crescimento(estrutura, cobertura):
    """Razões de incrementos anuais; não são médias de novidade por documento."""
    t = estrutura.sort_values('cutoff_year').reset_index(drop=True).copy()
    if t.cutoff_year.tolist() != list(ANOS):
        raise ValueError('A evolução estrutural deve conter os 32 anos consecutivos.')
    cols = ['publication_year', 'corpus_news', 're_completed_strict', 're_partial',
            'support_news', 'retained_occurrences', 'strict_completion_share']
    t = t.merge(cobertura[cols], left_on='cutoff_year', right_on='publication_year',
                validate='one_to_one', suffixes=('', '_annual')).drop(columns='publication_year')
    for key, name in [('nodes', 'new_nodes'), ('simple_undirected_edges', 'new_undirected_pairs'),
                      ('typed_directed_edges', 'new_typed_edges'), ('weight_sum', 'new_occurrences')]:
        t[name] = t[key].diff().fillna(t[key]).astype('int64')
        if t[name].lt(0).any() or int(t[name].sum()) != int(t[key].iloc[-1]):
            raise ValueError('Incremento acumulado inconsistente: ' + key)
    if not t.new_occurrences.eq(t.retained_occurrences).all():
        raise ValueError('Incrementos de peso diferem das ocorrências anuais.')
    # Os totais acumulados já possuem os mesmos nomes; usa-se explicitamente a coluna anual.
    support = t['support_news_annual']
    if t.loc[support.eq(0), ['new_nodes', 'new_undirected_pairs', 'new_typed_edges', 'new_occurrences']].ne(0).any().any():
        raise ValueError('Incremento estrutural sem suporte relacional no ano.')
    t['network_evidence_available_in_year'] = support.gt(0)
    for key in ['new_nodes', 'new_undirected_pairs', 'new_typed_edges']:
        t[key+'_per_corpus_news'] = t[key]/t.corpus_news.where(t.corpus_news.gt(0))
        t[key+'_per_support_news'] = t[key]/support.where(support.gt(0))
    t['delta_gcc_percentage_points'] = 100*t.largest_component_share.diff()
    t['delta_mean_degree'] = t.mean_degree.diff()
    t['delta_transitivity'] = t.transitivity.diff()
    return t


def gerar_figuras(folder, crescimento):
    """Lê uma tabela persistida ou equivalente; não executa GDS."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    plt.rcParams.update({'font.size': 10, 'svg.fonttype': 'none', 'pdf.fonttype': 42})
    t = crescimento; years = t.cutoff_year; catalogo = []
    def salvar(fig, nome, objetivo, legenda):
        for ax in fig.axes:
            ax.grid(alpha=.2); ax.set_xticks(list(range(1994, 2026, 2)))
            ax.tick_params(axis='x', labelrotation=45)
        fig.tight_layout()
        for ext in ['svg', 'png', 'pdf']:
            arquivo = nome+'.'+ext
            fig.savefig(Path(folder)/arquivo, dpi=300, bbox_inches='tight')
            catalogo.append({'file': arquivo, 'objective': objetivo, 'caption': legenda})
        plt.close(fig)
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for ax, den, label in zip(axes, ['corpus_news', 'support_news'], ['Notícias no corpus', 'Notícias com relações retidas']):
        for metric, text, color, marker in [('new_nodes', 'Novas entidades', 'tab:blue', 'o'),
            ('new_undirected_pairs', 'Novos pares conectados', 'tab:orange', 's')]:
            valores = t[metric+'_per_'+den].where(t.network_evidence_available_in_year)
            ax.plot(years, valores, color=color, marker=marker, markersize=3, label=text)
        ax.set_ylabel('Incremento / notícia'); ax.set_title('Denominador: '+label.lower()); ax.legend(frameon=False)
    axes[-1].set_xlabel('Ano limite da rede acumulada')
    salvar(fig, '01_crescimento_por_noticia', 'Examinar novidade estrutural considerando o volume documental.',
        'Razões entre incrementos agregados de entidades ou pares distintos e o número de notícias anuais. '
        'O painel superior usa o corpus; o inferior, as notícias com relações retidas. Não são médias por documento '
        'nem correções de viés de seleção. Anos sem suporte relacional aparecem como lacunas nas curvas.')
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    axes[0].plot(years, 100*t.largest_component_share, color='tab:blue', marker='o', markersize=3)
    axes[0].set(ylabel='Nós na maior componente (%)', ylim=(0, 105))
    axes[1].bar(years, t.corpus_news, color='tab:blue', alpha=.25, label='Corpus')
    axes[1].plot(years, t.support_news_annual, color='tab:orange', marker='s', markersize=3, label='Com relações retidas')
    axes[1].set(ylabel='Notícias no ano', xlabel='Ano limite da rede acumulada'); axes[1].legend(frameon=False)
    salvar(fig, '02_integracao_e_volume', 'Relacionar integração da rede, volume e suporte documental.',
        'Proporção de entidades na maior componente das redes acumuladas, acompanhada do volume anual de notícias '
        'e suporte relacional em painel alinhado. Os eixos separados evitam sugerir equivalência entre unidades. '
        'A proporção pode diminuir mesmo que o tamanho absoluto da maior componente cresça.')
    fig, axes = plt.subplots(2, 2, figsize=(12, 7), sharex=True)
    for ax, campo, label, cor in zip(axes.flat,
        ['mean_degree', 'density', 'mean_local_clustering_degree_ge_two', 'transitivity'],
        ['Grau médio', 'Densidade', 'Clusterização média — grau ≥ 2', 'Transitividade'],
        ['tab:blue', 'tab:orange', 'tab:blue', 'tab:orange']):
        ax.plot(years, t[campo], color=cor, marker='o', markersize=3); ax.set_ylabel(label)
        if campo == 'density': ax.ticklabel_format(axis='y', style='sci', scilimits=(0, 0))
    for ax in axes[-1]: ax.set_xlabel('Ano limite')
    salvar(fig, '03_metricas_estruturais', 'Comparar conectividade e fechamento das vizinhanças.',
        'Métricas nas projeções simples não dirigidas e não ponderadas. A clusterização média considera grau ≥ 2; '
        'a transitividade pondera as vizinhanças pelo número de triplas conectadas. Densidade depende do tamanho '
        'da rede. Todas as curvas descrevem a evidência disponível, com cobertura variável entre anos.')
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    axes[0].plot(years, t.nodes, label='Entidades', color='tab:blue')
    axes[0].plot(years, t.simple_undirected_edges, label='Pares não dirigidos', color='tab:orange')
    axes[0].set_ylabel('Total acumulado'); axes[0].legend(frameon=False)
    axes[1].plot(years, t.connected_components, label='Componentes', color='tab:blue')
    axes[1].set(ylabel='Número de componentes', xlabel='Ano limite'); axes[1].legend(frameon=False)
    salvar(fig, '04_tamanho_e_fragmentacao', 'Examinar expansão e fragmentação da topologia.',
        'Entidades, pares distintos e componentes das redes acumuladas. Nós e pares não diminuem por construção; '
        'o número de componentes pode aumentar com novos grupos ou diminuir com conexões que unem grupos. '
        'Esses mecanismos requerem análise das transições, não são identificados apenas por esta figura.')
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    axes[0].bar(years, t.strict_completion_share, color='tab:orange')
    axes[0].set(ylim=(0, 1.05), ylabel='RE concluída / corpus'); axes[0].yaxis.set_major_formatter(PercentFormatter(1))
    axes[1].bar(years, t.retained_occurrences, color='tab:blue')
    axes[1].set(ylabel='Ocorrências retidas no ano', xlabel='Ano de publicação')
    salvar(fig, '05_cobertura_e_ocorrencias', 'Contextualizar mudanças aparentes com a disponibilidade das extrações.',
        'Conclusão estrita inclui SUCCESS e SUCCESS_ZERO, sem PARTIAL. Ocorrências retidas são registros '
        'agregados e não relações factuais independentes ou escores de confiança. Ausência de extração '
        'não representa ausência de atividade jornalística.')
    return pd.DataFrame(catalogo)


def analisar_estrutura_temporal(projeto, *, executar_gds=False, assinatura_rede_esperada=None,
                               assinatura_temporal_esperada=None, driver_factory=None):
    root = Path(projeto).resolve()
    if root.name == 'PROJECT_EXTRACAO': raise ValueError('Use o projeto de análise.')
    origem, meta = carregar_redes_temporais(root, assinatura_rede_esperada)
    if assinatura_temporal_esperada and meta['snapshot_sha256'] != assinatura_temporal_esperada:
        raise ValueError('A série temporal difere da edição esperada.')
    if carregar_rede(root)[1]['snapshot_sha256'] != meta['network_snapshot_sha256']:
        raise ValueError('A série temporal pertence a outra rede global ativa.')
    if not executar_gds:
        out = {'mode': 'DRY_RUN', 'snapshot_count': 32, 'algorithms': ['degree', 'triangleCount', 'wcc'],
            'projection_read_concurrency': 1, 'algorithm_concurrency': 4,
            'drop_projection_after_each_cutoff': True, 'independent_node_verification': True,
            'neo4j_connections': 0, 'database_writes': 0, 'api_calls': 0, 'files_written': 0}
        print('[ESTRUTURA TEMPORAL]', json.dumps(out)); return out
    spec = {'schema': 'annual-structural-evolution-1', 'version': VERSION,
        'code_sha256': sha(Path(__file__)), 'temporal_snapshot_sha256': meta['snapshot_sha256'],
        'network_snapshot_sha256': meta['network_snapshot_sha256'],
        'structural_code_sha256': sha(Path(resumir_metricas.__code__.co_filename)),
        'source_structural_code_sha256': sha(Path(verificar_metricas.__code__.co_filename)),
        'projection_code_sha256': sha(Path(verificar_projecao.__code__.co_filename)),
        'cutoff_years': list(ANOS), 'read_concurrency': 1, 'algorithm_concurrency': 4}
    assinatura = json_sha(spec)
    base = root/'resultados/temporal/estrutural'; base.mkdir(parents=True, exist_ok=True)
    destino = base/assinatura[:20]; destino.mkdir(exist_ok=True)
    lock = destino/'analise.lock'
    try: lock.mkdir()
    except FileExistsError: raise RuntimeError('Análise pode estar ativa. Confira o bloqueio antes de retomar.') from None
    driver = None; novos = reused = 0; inicio = perf_counter()
    try:
        resumos = []
        for ano in ANOS:
            sub = destino/str(ano)
            if sub.exists():
                salvo = validate_manifest(sub)
                if salvo['series_analysis_sha256'] != assinatura or salvo['cutoff_year'] != ano:
                    raise ValueError('Resultado temporal incompatível: '+str(ano))
                total = salvo['summary']; reused += 1
            else:
                if driver is None:
                    uri, user, password, database = _configuration(root)
                    if driver_factory is None:
                        from neo4j import GraphDatabase
                        driver_factory = GraphDatabase.driver
                    driver = driver_factory(uri, auth=(user, password), connection_timeout=15, max_transaction_retry_time=10)
                    driver.verify_connectivity()
                ler = lambda n: pd.read_csv(origem/str(ano)/n, dtype=str, keep_default_na=False)
                nos, simples, arestas = [ler(n) for n in ['nos.csv.gz', 'simples_nao_dirigida.csv.gz', 'arestas.csv.gz']]
                nome = f'newsai_temporal_{assinatura[:10]}_{ano}_{uuid.uuid4().hex[:8]}'
                tag = 'newsai_'+meta['network_snapshot_sha256'][:20]
                print(f'[ESTRUTURA TEMPORAL] {ano}: projeção com leitura sequencial.', flush=True)
                with driver.session(database=database) as session:
                    versao = query(session, 'RETURN gds.version() AS version')
                    tabelas, metricas, run = calcular_corte(session, nome, database, tag, nos, simples, arestas)
                child = validate_manifest(origem/str(ano))
                total = {'cutoff_year': ano, 'is_reference_cutoff': ano in meta['reference_cutoff_years'],
                         **child['summary'], **metricas, 'independent_topology_verified': True}
                if total['nodes'] != child['summary']['nodes'] or total['simple_undirected_edges'] != child['summary']['undirected_pairs']:
                    raise ValueError('Dimensões estruturais diferem da construção.')
                temp = Path(tempfile.mkdtemp(prefix=f'.{ano}_', dir=destino))
                try:
                    for arquivo, tabela in tabelas.items(): write_csv(temp, arquivo, tabela)
                    atomic_json(temp/'execucao_gds.json', {'database': database, 'gds_version': versao,
                        'graph_name': nome, 'projection_released': True, **run})
                    atomic_json(temp/'manifesto.json', {'schema': 'annual-structural-cutoff-1',
                        'snapshot_sha256': json_sha([assinatura, ano]), 'series_analysis_sha256': assinatura,
                        'cutoff_year': ano, 'summary': total,
                        'outputs_sha256': {p.name: sha(p) for p in sorted(temp.iterdir())}})
                    validate_manifest(temp); temp.rename(sub)
                finally:
                    if temp.exists(): shutil.rmtree(temp)
                novos += 1
            resumos.append(total)
            print(f'[ESTRUTURA TEMPORAL] {ano}: {total["connected_components"]:,} componentes; '
                  f'maior: {total["largest_component_share"]:.2%}; resultado salvo e conferido.', flush=True)
        tabela = pd.DataFrame(resumos)
        cobertura = pd.read_csv(origem/'cobertura_anual.csv')
        crescimento = calcular_crescimento(tabela, cobertura)
        write_csv(destino, 'evolucao_estrutural_anual.csv', tabela)
        write_csv(destino, 'evolucao_estrutural_marcos_referencia.csv', tabela.loc[tabela.is_reference_cutoff])
        write_csv(destino, 'crescimento_anual.csv', crescimento)
        write_csv(destino, 'catalogo_figuras.csv', gerar_figuras(destino, crescimento))
        (destino/'LEIA_ME.md').write_text(NOTAS, encoding='utf-8')
        if carregar_redes_temporais(root, assinatura_rede_esperada)[1]['snapshot_sha256'] != meta['snapshot_sha256']:
            raise ValueError('A série temporal mudou durante a análise.')
        resumo = {'snapshot_count': 32, 'reference_snapshot_count': 19,
            'all_node_metrics_independently_verified': True, 'figure_files': 15,
            'projections_released': True, 'last_snapshot': resumos[-1],
            'api_calls': 0, 'database_writes': 0, 'global_network_modified': False,
            'community_detection_computed': False, 'distance_metrics_computed': False}
        atomic_json(destino/'manifesto.json', {**spec, 'snapshot_sha256': assinatura, 'summary': resumo,
            'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'outputs_sha256': {p.name: sha(p) for p in sorted(destino.iterdir()) if p.is_file() and p.name != 'manifesto.json'},
            'cutoff_manifests_sha256': {str(y): sha(destino/str(y)/'manifesto.json') for y in ANOS}})
        validate_manifest(destino)
        atomic_json(base/'atual.json', {'folder': destino.name, 'snapshot_sha256': assinatura})
    except Exception as exc:
        print('[ESTRUTURA TEMPORAL] FALHA:', json.dumps(_failure(exc)))
        raise RuntimeError('Análise não concluída; os cortes já salvos permanecem disponíveis. Confira a falha antes de retomar.') from None
    finally:
        try:
            if driver is not None: driver.close()
        finally: lock.rmdir()
    pacote = base/f'Resumo_Estrutura_Temporal_{assinatura[:12]}_{uuid.uuid4().hex[:6]}.zip'
    with zipfile.ZipFile(pacote, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(destino.rglob('*')):
            if p.is_file(): z.write(p, p.relative_to(destino))
    resultado = {**resumo, 'new_cutoffs_this_run': novos, 'reused_cutoffs_this_run': reused,
        'elapsed_seconds_this_run': perf_counter()-inicio, 'snapshot_sha256': assinatura,
        'output_directory': destino, 'package': pacote}
    print('[ESTRUTURA TEMPORAL]', json.dumps({k: v for k, v in resultado.items() if k not in ['output_directory', 'package']}, ensure_ascii=False))
    print('[ESTRUTURA TEMPORAL] Pacote:', pacote)
    return resultado


NOTAS = '''# Evolução estrutural anual

São analisados os 32 cortes acumulados, de 1994 a 2025. Os 19 marcos de
referência são uma seleção da mesma série. Cada corte usa uma projeção
simples não dirigida, com peso unitário por par. O GDS calcula grau,
triângulos incidentes e componentes. Os resultados de todos os nós são
comparados com uma implementação independente baseada em adjacências.

A densidade é 2M/[N(N-1)]. A média principal de clusterização considera
grau pelo menos dois. Também se informa a média incluindo todos os nós.
A transitividade é 3T dividido pelo número de triplas conectadas. A maior
componente é escolhida pelo tamanho, com desempate pelo menor ID canônico.
Não se exige a presença de uma componente com fração arbitrária de nós.

Incrementos anuais e razões por notícia são descritivos. A divisão pelo
corpus e pelo suporte relacional usa denominadores diferentes; nenhuma
das razões elimina o viés de cobertura. O primeiro corte representa o
estoque inicial observado, não uma transição desde um ano anterior medido.
Anos sem suporte relacional aparecem como lacunas na figura de razões,
enquanto a topologia acumulada permanece representada nas demais figuras.

O número de componentes pode crescer com a incorporação de grupos separados
ou diminuir com a conexão entre grupos; a série agregada não identifica
sozinha esses mecanismos. Novas entidades não comprovam diversidade temática;
crescimento acumulado não comprova vantagem cumulativa. Não se ajusta lei
de potência nem se conclui sobre concentração apenas a partir destas figuras.

As projeções usam os nós persistidos da edição global já carregada no Neo4j.
São criadas uma por vez, com leitura sequencial, e liberadas após cada corte,
inclusive na ocorrência de falha, enquanto a conexão ao servidor permitir.
Não há escrita de nós ou relacionamentos persistentes. Os resultados por
ano ficam em disco e permitem retomada. O índice só muda após conclusão.

As figuras são geradas das tabelas persistidas e possuem catálogo com
objetivos e legendas. Ajustes gráficos podem reutilizar crescimento_anual.csv
e gerar_figuras sem executar o GDS novamente. As cores azul e laranja
preservam as séries correspondentes do padrão visual adotado.
'''
