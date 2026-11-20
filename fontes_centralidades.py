"""Protagonismo estrutural das entidades em redes de fontes distintas."""
from pathlib import Path
from datetime import datetime, timezone
from itertools import combinations
import json
import shutil
import tempfile
import uuid
import zipfile
import pandas as pd
from fontes_estrutural import carregar_fontes, query
from redes_fontes import FONTES
from redes_projecoes import verificar_projecao, valores_esperados, EXISTS
from redes_centralidades import calcular_conectividade, executar_pagerank, validar_pagerank, gerar_rankings, PAGERANK_CONFIG, TYPE_COLORS, TYPE_NAMES
from re_consolidacao import sha, json_sha, write_csv, validate_manifest
from re_execucao import atomic_json
from neo4j_integracao import _configuration, _failure

VERSION = '1.1.0'
METRICAS = ['neighbor_degree', 'weighted_strength', 'pagerank_share']
PROJETAR = '''UNWIND $rows AS row
MATCH (source:NewsAIEntity {graph_tag:$tag, entity_group_id:row.source_id})
MATCH (target:NewsAIEntity {graph_tag:$tag, entity_group_id:row.target_id})
WITH gds.graph.project($name, source, target,
 {sourceNodeProperties:{entity_group_id:source.entity_group_id},
  targetNodeProperties:{entity_group_id:target.entity_group_id},
  relationshipType:'SOURCE_SEMANTIC',
  relationshipProperties:{weight:toFloat(row.weight), distance:1.0/toFloat(row.weight)}},
 {readConcurrency:1}) AS g
RETURN g.graphName AS graphName, g.nodeCount AS nodeCount, g.relationshipCount AS relationshipCount'''


def pagerank_projetado(session, *, name, expected_name, tag, database, frame, edges, simple):
    """Cria, verifica, calcula e libera somente a projeção exata desta execução."""
    if name != expected_name or not name.startswith('newsai_fontes_') or '_directed_' not in name:
        raise ValueError('Nome fora do escopo da projeção temporária.')
    existe = query(session, EXISTS, name=name)[0]['exists']
    try:
        if not existe:
            rows = [{'source_id':int(a), 'target_id':int(b), 'weight':int(w)}
                    for a,b,w in zip(edges.source_id,edges.target_id,edges.weight)]
            session.run(PROJETAR, rows=rows, tag=tag, name=name).consume()
        projection = verificar_projecao(session, name, database, tag, set(frame.entity_group_id),
                                       valores_esperados('directed', edges, simple))
        raw, info = executar_pagerank(session, name)
        return raw, info, projection, bool(existe)
    finally:
        try:
            session.run('CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName', name=name).consume()
            print('[PROTAGONISMO] PROJEÇÃO LIBERADA —', name, flush=True)
        except Exception as cleanup_error:
            print('[PROTAGONISMO] LIBERAÇÃO PENDENTE —', json.dumps(_failure(cleanup_error)), flush=True)


def carregar_estrutura_fontes(root, meta):
    base = root/'resultados/comparacao_fontes/estrutural'
    pointer = json.loads((base/'atual.json').read_text(encoding='utf-8'))
    if Path(pointer['folder']).name != pointer['folder']:
        raise ValueError('Apontador da comparação estrutural inválido.')
    folder = base/pointer['folder']; estrutural = validate_manifest(folder)
    if estrutural['schema'] != 'source-structural-comparison-1' or estrutural['snapshot_sha256'] != pointer['snapshot_sha256']:
        raise ValueError('Edição estrutural incompatível.')
    if estrutural['source_networks_snapshot_sha256'] != meta['snapshot_sha256']:
        raise ValueError('Estrutura e redes por fonte pertencem a edições diferentes.')
    return folder, estrutural


def comparar_rankings(frames):
    comparacao = []; overlaps = []
    for slug, frame in frames.items():
        for metrica in METRICAS:
            rank = frame[metrica].rank(method='min', ascending=False).astype(int)
            for i, row in enumerate(frame.itertuples(index=False)):
                comparacao.append({'source_key': slug, 'source': FONTES[slug], 'entity_group_id': int(row.entity_group_id),
                    'entity_group_name': row.entity_group_name, 'ent_label': row.ent_label,
                    'metric': metrica, 'value': float(getattr(row, metrica)), 'rank': int(rank.iloc[i])})
    for a, b in combinations(frames, 2):
        for metrica in METRICAS:
            def top(slug):
                return set(frames[slug].sort_values([metrica, 'entity_group_id'], ascending=[False, True]).head(20).entity_group_id)
            x, y = top(a), top(b)
            overlaps.append({'source_a': a, 'source_b': b, 'metric': metrica, 'top_limit': 20,
                'size_a': len(x), 'size_b': len(y), 'intersection': len(x & y), 'union': len(x | y),
                'jaccard': len(x & y)/len(x | y) if x | y else None,
                'tie_policy': 'score descending; entity_group_id ascending'})
    return pd.DataFrame(comparacao), pd.DataFrame(overlaps)


def noticias_suporte(frame, node_news, news):
    keys = ['news_id', 'news_version_id']
    if news.news_id.duplicated().any() or node_news.duplicated(['entity_group_id']+keys).any():
        raise ValueError('Notícia ou vínculo de entidade duplicado.')
    nn = node_news.copy(); nn['entity_group_id'] = nn.entity_group_id.astype(int)
    nn = nn.loc[pd.to_numeric(nn.relation_participation_count).gt(0),
        ['entity_group_id']+keys+['mention_count', 'relation_participation_count']]
    linked = nn.merge(news, on=keys, how='left', indicator=True, validate='many_to_one')
    if not linked['_merge'].eq('both').all():
        raise ValueError('Notícia de suporte ausente ou versão divergente.')
    counts = linked.groupby('entity_group_id').news_id.nunique()
    expected = frame.set_index('entity_group_id').relation_news_count.astype(int)
    if not counts.reindex(expected.index, fill_value=0).eq(expected).all():
        raise ValueError('Suporte documental não recompõe as contagens dos nós.')
    return linked.drop(columns='_merge')


def figuras(folder, frames):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    from matplotlib.ticker import PercentFormatter
    import textwrap
    plt.rcParams.update({'font.size': 9, 'svg.fonttype': 'none', 'pdf.fonttype': 42})
    catalogo = []
    for metrica, titulo, eixo in [('neighbor_degree', 'Grau de vizinhança', 'Vizinhos distintos'),
            ('weighted_strength', 'Força total', 'Ocorrências relacionais incidentes'),
            ('pagerank_share', 'PageRank ponderado', 'Parcela do escore PageRank na própria rede')]:
        fig, axes = plt.subplots(1, 3, figsize=(18, 6))
        limite = max(float(f[metrica].max()) for f in frames.values())
        for ax, (slug, f) in zip(axes, frames.items()):
            part = f.sort_values([metrica, 'entity_group_id'], ascending=[False, True]).head(7).iloc[::-1]
            labels = ['\n'.join(textwrap.wrap(str(r.entity_group_name), 23))+' ['+str(r.entity_group_id)+']' for r in part.itertuples()]
            ax.barh(range(len(part)), part[metrica], color=[TYPE_COLORS[x] for x in part.ent_label])
            ax.set_yticks(range(len(part)), labels); ax.set_title(FONTES[slug]); ax.set_xlabel(eixo)
            ax.set_xlim(0, limite*1.08 if limite > 0 else 1)
            if metrica == 'pagerank_share': ax.xaxis.set_major_formatter(PercentFormatter(xmax=1))
            ax.grid(axis='x', alpha=.2)
        fig.suptitle(titulo+' — entidades de maior escore', y=1.01)
        fig.legend(handles=[Patch(color=c, label=TYPE_NAMES[t]) for t,c in TYPE_COLORS.items()], loc='lower center', ncol=3, frameon=False)
        fig.tight_layout(rect=(0, .06, 1, 1))
        legenda = ('Sete primeiras entidades por fonte; cores indicam tipo de entidade. Empates de escore são ordenados por ID. '
                   'IDs são compartilhados entre fontes e distinguem nomes iguais. '+
            ('PageRank é calculado na rede dirigida ponderada; a parcela divide o escore pela soma da própria rede. Não é uma escala universal de importância entre veículos.' if metrica=='pagerank_share' else
                    'O grau usa vizinhos distintos sem direção.' if metrica=='neighbor_degree' else
                    'A força soma os pesos de entrada e saída; rótulos inversos e ocorrências repetidas permanecem representados.'))+' Os painéis usam a mesma escala horizontal por métrica.'
        for ext in ['svg', 'png', 'pdf']:
            nome = metrica+'_fontes.'+ext; fig.savefig(folder/nome, dpi=220, bbox_inches='tight')
            catalogo.append({'file': nome, 'objective': 'Comparar entidades protagonistas por '+titulo.lower()+'.', 'caption': legenda})
        plt.close(fig)
    return pd.DataFrame(catalogo)


def analisar_centralidades_fontes(projeto, *, executar_gds=False, assinatura_rede_esperada=None,
                                  assinatura_fontes_esperada=None, driver_factory=None):
    root = Path(projeto).resolve(); origem, meta = carregar_fontes(root, assinatura_rede_esperada)
    if assinatura_fontes_esperada and meta['snapshot_sha256'] != assinatura_fontes_esperada:
        raise ValueError('Redes por fonte diferentes da edição esperada.')
    estrutura, s_meta = carregar_estrutura_fontes(root, meta)
    if not executar_gds:
        return {'mode': 'DRY_RUN', 'sources': list(FONTES.values()), 'pagerank_configuration': PAGERANK_CONFIG,
            'complete_news_lists': True, 'neo4j_connections': 0, 'files_written': 0, 'api_calls': 0}
    spec = {'schema': 'source-entity-centralities-1', 'version': VERSION, 'code_sha256': sha(Path(__file__)),
        'source_networks_snapshot_sha256': meta['snapshot_sha256'], 'structural_snapshot_sha256': s_meta['snapshot_sha256'],
        'network_snapshot_sha256': meta['network_snapshot_sha256'],
        'centrality_code_sha256': sha(Path(validar_pagerank.__code__.co_filename)),
        'projection_code_sha256': sha(Path(verificar_projecao.__code__.co_filename)),
        'pagerank_configuration': PAGERANK_CONFIG, 'top_limit': 20,
        'projection_read_concurrency': 1, 'release_source_projection_after_pagerank': True}
    assinatura = json_sha(spec);base = root/'resultados/comparacao_fontes/centralidades';base.mkdir(parents=True, exist_ok=True)
    destino = base/assinatura[:20];lock = base/'execucao.lock'
    try: lock.mkdir()
    except FileExistsError: raise RuntimeError('Análise de centralidades pode estar ativa; confira o bloqueio.') from None
    driver = None; temp = None; source_in_progress = None
    try:
        if destino.exists():
            salvo = validate_manifest(destino)
            if salvo['snapshot_sha256'] != assinatura: raise ValueError('Assinatura da saída incompatível.')
            resumo = salvo['summary']
        else:
            uri,user,password,database = _configuration(root)
            if driver_factory is None:
                from neo4j import GraphDatabase
                driver_factory = GraphDatabase.driver
            driver = driver_factory(uri, auth=(user,password), connection_timeout=15, max_transaction_retry_time=10)
            driver.verify_connectivity();temp = Path(tempfile.mkdtemp(prefix='.centralidades_', dir=base))
            frames = {}; resumos = []; execucao = {}; all_ranks = []
            with driver.session(database=database) as session:
                for slug, fonte in FONTES.items():
                    source_in_progress = fonte
                    def ler(nome): return pd.read_csv(origem/(slug+'_'+nome), dtype=str, keep_default_na=False)
                    nodes, edges, simple = ler('nos.csv.gz'), ler('arestas.csv.gz'), ler('simples_nao_dirigida.csv.gz')
                    structural = pd.read_csv(estrutura/(slug+'_metricas_nos.csv.gz'))
                    frame, totals = calcular_conectividade(nodes, edges, simple, structural)
                    name = 'newsai_fontes_'+meta['snapshot_sha256'][:12]+'_'+slug+'_directed_'+assinatura[:8]
                    tag = 'newsai_'+meta['network_snapshot_sha256'][:20]
                    print('[PROTAGONISMO] PROJEÇÃO —', fonte, '; leitura com 1 trabalhador; liberação após PageRank.', flush=True)
                    raw, info, projection, exists = pagerank_projetado(session, name=name, expected_name=name,
                        tag=tag, database=database, frame=frame, edges=edges, simple=simple)
                    frame, proof = validar_pagerank(frame, raw, edges)
                    frame['strength_share'] = frame.weighted_strength/frame.weighted_strength.sum()
                    frame, ranks = gerar_rankings(frame)
                    frame['rank_pagerank_share'] = frame.pagerank_share.rank(method='min', ascending=False).astype(int)
                    links = noticias_suporte(frame, ler('nos_noticias.csv.gz'), ler('noticias.csv.gz'))
                    frames[slug] = frame;ranks.insert(0,'source_key',slug);all_ranks.append(ranks)
                    write_csv(temp, slug+'_centralidades.csv.gz', frame)
                    write_csv(temp, slug+'_noticias_suporte.csv.gz', links)
                    row = {'source_key':slug, 'source':fonte, **totals,
                        'pagerank_sum':float(frame.pagerank.sum()), 'pagerank_share_sum':float(frame.pagerank_share.sum()),
                        'pagerank_max':float(frame.pagerank.max()), 'all_pagerank_nodes_verified':True,
                        'support_links':len(links), 'support_news':int(links.news_id.nunique())}
                    resumos.append(row);execucao[slug] = {'projection':projection, 'projection_reused':bool(exists),
                        'projection_release_attempted':True, 'graph_name':name, 'pagerank':info, 'independent_verification':proof}
                    print('[PROTAGONISMO]',json.dumps(row, ensure_ascii=False),flush=True)
            comparison, overlaps = comparar_rankings(frames)
            write_csv(temp,'comparacao_entidades.csv.gz',comparison);write_csv(temp,'sobreposicao_top20.csv',overlaps)
            write_csv(temp,'rankings_top20.csv.gz',pd.concat(all_ranks,ignore_index=True))
            write_csv(temp,'resumo_centralidades.csv',pd.DataFrame(resumos));write_csv(temp,'catalogo_figuras.csv',figuras(temp,frames))
            atomic_json(temp/'execucao_gds.json',{'database':database,'runs':execucao})
            resumo = {'networks':resumos,'complete_news_lists':True,'all_pagerank_nodes_verified':True,
                'figure_files':9,'database_writes':0,'api_calls':0,'global_network_modified':False,
                'betweenness_computed':False,'closeness_computed':False,'community_detection_computed':False}
            (temp/'LEIA_ME.md').write_text(
                '# Protagonismo das entidades\n\nGrau de vizinhança, grau tipado e força seguem as definições da análise global. '
                'PageRank é dirigido e ponderado; todos os escores GDS são confrontados com a referência independente na escala nativa. '
                'pagerank_share é a fração da soma dos escores da própria rede, sem alterar o algoritmo ou sua posição no ranking.\n\n'
                'Comparações usam IDs globais. Ausência na tabela longa de uma fonte significa ausência da entidade nessa rede; '
                'não deve ser imputada como escore ou posição zero. Empates têm a mesma posição pelo método min, '
                'mas o top 20 usa ID crescente para limitar a lista.\n\n'
                'Os arquivos noticias_suporte contêm a lista completa de documentos com participação relacional de cada entidade, '
                'com títulos, links, versões e metadados. Menções sem participação relacional continuam disponíveis na seção de construção das redes.\n\n'
                'Estes escores descrevem protagonismo estrutural na representação extraída. Não demonstram influência social, '
                'causalidade ou importância jornalística intrínseca. As diferenças de cobertura e resolução permanecem limitações.\n',encoding='utf-8')
            atomic_json(temp/'manifesto.json',{**spec,'snapshot_sha256':assinatura,'summary':resumo,
                'created_at_utc':datetime.now(timezone.utc).isoformat(),
                'outputs_sha256':{p.name:sha(p) for p in sorted(temp.iterdir())}})
            validate_manifest(temp);temp.rename(destino);temp = None
        atomic_json(base/'atual.json',{'folder':destino.name,'snapshot_sha256':assinatura})
        pacote = base/('Resumo_Protagonismo_Fontes_'+assinatura[:12]+'_'+uuid.uuid4().hex[:6]+'.zip')
        with zipfile.ZipFile(pacote,'w',zipfile.ZIP_DEFLATED) as z:
            for p in sorted(destino.iterdir()):z.write(p,p.name)
        print('[PROTAGONISMO] Pacote:',pacote)
        return {**resumo,'output_directory':destino,'package':pacote,'snapshot_sha256':assinatura}
    except Exception as exc:
        falha = {**_failure(exc), 'source':source_in_progress}
        if 'Java heap space' in str(getattr(exc, 'message', exc)):
            falha['cause'] = 'JAVA_HEAP_SPACE'
            falha['action'] = 'Reinicie o Neo4j; confira o limite de heap e a memória disponível antes de retomar.'
        print('[PROTAGONISMO] FALHA:',json.dumps(falha, ensure_ascii=False))
        raise RuntimeError('Análise não concluída; confira o diagnóstico acima. Entradas científicas preservadas.') from None
    finally:
        try:
            if driver is not None:driver.close()
        finally:
            if temp is not None and temp.exists():shutil.rmtree(temp)
            lock.rmdir()
