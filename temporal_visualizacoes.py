"""Exploração temporal de subgrafos com posições estáveis e suporte documental."""
from pathlib import Path
from datetime import datetime, timezone
from time import perf_counter
import json
import math
import textwrap
import shutil
import tempfile
import re
import zipfile
import numpy as np
import pandas as pd
from temporal_redes import ANOS, carregar_redes_temporais
from temporal_caudas import carregar_trajetorias
from re_consolidacao import sha, json_sha, write_csv, validate_manifest
from re_execucao import atomic_json

VERSION = '3.0.0'
COLORS = {'PESSOA': '#4C78A8', 'ORGANIZACAO': '#F58518', 'LOCAL': '#54A24B'}
NAMES = {'PESSOA': 'Pessoas', 'ORGANIZACAO': 'Organizações', 'LOCAL': 'Locais'}


def registros(frame):
    return json.loads(frame.to_json(orient='records', force_ascii=False))


def json_seguro(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')


def destaques_automaticos(nodes, minimo=15):
    ordered=nodes.sort_values(['degree','entity_group_id'],ascending=[False,True])
    if len(ordered)<minimo:return ordered.copy()
    threshold=int(ordered.iloc[minimo-1].degree)
    return ordered.loc[ordered.degree.ge(threshold)].copy()


def selecionar_vista(nodes, pairs, *, foco=None, max_nos=100, max_pares=250):
    """Ranking no corte corrente; vizinhança de um salto para vistas focais."""
    if pairs[['source_id', 'target_id']].duplicated().any() or pairs.source_id.ge(pairs.target_id).any():
        raise ValueError('Pares devem ser únicos, ordenados e sem auto laços.')
    if foco is None:
        selected = nodes.sort_values(['degree', 'entity_group_id'], ascending=[False, True]).head(max_nos).copy()
    elif foco not in set(nodes.entity_group_id):
        return nodes.iloc[:0].copy(), pairs.iloc[:0].copy()
    else:
        incident = pairs.loc[pairs.source_id.eq(foco) | pairs.target_id.eq(foco)].copy()
        incident['neighbor'] = np.where(incident.source_id.eq(foco), incident.target_id, incident.source_id)
        incident['degree'] = incident.neighbor.map(nodes.set_index('entity_group_id').degree)
        neighbor_ids = incident.sort_values(['weight', 'degree', 'neighbor'], ascending=[False, False, True]).head(max_nos-1).neighbor
        selected = nodes.loc[nodes.entity_group_id.isin(set(neighbor_ids) | {foco})].copy()
    ids = set(selected.entity_group_id)
    edges = pairs.loc[pairs.source_id.isin(ids) & pairs.target_id.isin(ids)].copy()
    edges['focal_priority'] = (edges.source_id.eq(foco) | edges.target_id.eq(foco)).astype(int) if foco is not None else 0
    edges = edges.sort_values(['focal_priority', 'weight', 'source_id', 'target_id'], ascending=[False, False, True, True]).head(max_pares)
    return selected.sort_values('entity_group_id'), edges.drop(columns='focal_priority').reset_index(drop=True)


def conferir_evidencias(pairs, evidence, news, year):
    e = evidence.loc[evidence.publication_year.le(year)]
    stats = e.groupby('pair_id').agg(weight=('occurrence_count', 'sum'), docs=('news_id', 'nunique'))
    for row in pairs.itertuples(index=False):
        if row.pair_id not in stats.index or int(stats.loc[row.pair_id, 'weight']) != int(row.weight):
            raise ValueError('Peso exibido difere das notícias: '+str(year)+' / '+str(row.pair_id))
        if int(stats.loc[row.pair_id, 'docs']) != int(row.distinct_news_count):
            raise ValueError('Contagem de notícias do par incompatível.')
    if not set(e.news_id).issubset(set(news.news_id)):
        raise ValueError('Notícia referenciada ausente.')


def gerar_html(payload, script, asset_js, asset_css):
    return '''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Redes de notícias — evolução temporal</title>
<style>'''+asset_css+'''
*{box-sizing:border-box}body{margin:0;background:#f3f6fa;color:#172b3a;font:15px system-ui,sans-serif}
header{padding:22px 30px;background:#12384c;color:white}h1{font-size:25px;margin:0 0 8px}header p{margin:0;max-width:1000px;line-height:1.5}
.layout{display:grid;grid-template-columns:minmax(0,1fr) 365px;gap:16px;padding:18px}.card{background:white;border:1px solid #dbe3ea;border-radius:10px;padding:16px;margin-bottom:14px}
.controls{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px}button,select,input{font:inherit;padding:7px;border:1px solid #b5c5d0;border-radius:5px}button{cursor:pointer;background:white;color:#12384c}button:hover{background:#e9f1f7}input[type=range]{flex:1;min-width:150px}
#graph{height:620px;background:white;border:1px solid #dbe3ea;border-radius:8px}.metrics{display:flex;gap:12px;flex-wrap:wrap}.metric{padding:10px 14px;background:#edf3f8;border-radius:6px;min-width:130px}.metric b{display:block;font-size:21px}
.notice{padding:10px 13px;border-left:4px solid #da9a35;background:#fff7e8;line-height:1.5}.muted,small{color:#526674}small{display:block;margin:5px 0}.legend{display:flex;gap:15px;flex-wrap:wrap;margin:12px 0}.dot{width:12px;height:12px;display:inline-block;border-radius:50%;margin-right:5px}
aside{min-width:0}aside h2{font-size:18px}li{margin:12px 0;overflow-wrap:anywhere}a{color:#155f86}#news-list{padding-left:20px}#detail{line-height:1.6}#search-results button{margin:3px;font-size:13px}.full{width:100%}#evidence-count{font-weight:600}#ranking-list{display:grid;gap:4px;margin-bottom:12px;font-size:13px}.footer{padding:0 30px 20px;font-size:13px;color:#526674}
@media(max-width:1000px){.layout{grid-template-columns:1fr}#graph{height:500px}header{padding:18px}}
</style></head><body><header><h1>Redes de entidades: evolução temporal</h1><p>Folha de S.Paulo · redes acumuladas desde 1994 · vizinhos distintos, ocorrências semânticas e notícias de origem.</p></header>
<div class="layout"><main><div class="card"><div class="controls"><label for="year">Ano</label><select id="year"></select><input id="slider" type="range" min="1994" max="2025" value="2025" aria-label="Ano do corte"><button id="prev">Anterior</button><button id="next">Seguinte</button></div>
<div class="controls"><label for="view">Vista</label><select id="view"></select><label><input id="labels" type="checkbox" checked> Todos os nomes</label></div><div class="metrics" id="metrics"></div><p id="scope" class="notice"></p><p id="coverage" class="muted"></p><div class="legend" id="legend"></div><details><summary>Destaques centrais do ano — grau e empates</summary><p id="ranking-criterion"></p><div id="ranking-list"></div></details>
<div class="controls"><input id="find" placeholder="Buscar entidade por nome ou ID" aria-label="Buscar entidade"><button id="fit">Enquadrar</button><button id="reset">Restaurar posições</button><button id="physics">Desativar física</button><button id="png">PNG</button><button id="svg">SVG</button></div><p id="search-status" class="muted"></p><div id="search-results"></div><div id="graph"></div>
<p class="muted">Arraste nós, use o zoom e clique em uma entidade ou ligação para consultar os detalhes e as notícias. Cor de preenchimento: tipo. Tamanho: grau em escala logarítmica. Espessura: ocorrências do par.</p></div>
<div class="card"><h2>Como interpretar</h2><p>As vistas mostram subgrafos selecionados, não a rede completa. Uma entidade pode sair da seleção sem sair da rede acumulada. A disposição espacial é uma ajuda visual e não uma medida de distância semântica.</p><p>As âncoras visuais são compartilhadas pelos cortes; as entidades fora da seleção de referência recebem posições iniciais determinísticas. O movimento elástico é apenas visual. A física inicia ativada e sua preferência é mantida ao trocar de ano. Desativar estabiliza o desenho; restaurar posições desativa a física e recupera as âncoras. O movimento não altera métricas ou relações. As cores não representam comunidades; não houve detecção de comunidades temporais nesta etapa.</p><p>Os destaques são selecionados automaticamente por grau no corte escolhido, incluindo empates na 15ª posição. A busca cobre todas as entidades da série e mantém a entidade escolhida por ID ao trocar de ano. Os anos sem extração concluída exigem cautela: ausência de crescimento observado não significa ausência de relações nas notícias. As referências aos 19 marcos anteriores permanecem indicadas no seletor de ano.</p></div></main>
<aside><div class="card"><h2>Detalhes da seleção</h2><div id="detail"></div><button id="scope-news">Notícias da rede completa do corte</button><label><input id="all-mentions" type="checkbox"> Incluir menções sem participação relacional (nó)</label></div>
<div class="card"><h2 id="evidence-title">Notícias de suporte</h2><p id="evidence-count"></p><h3>Exemplos</h3><ol id="examples"></ol><details><summary>Lista completa, busca e exportação</summary><input class="full" id="news-search" placeholder="Título, data, categoria ou link" aria-label="Buscar notícias"><p><button id="csv">Baixar lista completa em CSV</button></p><ol id="news-list"></ol><div class="controls"><button id="news-prev">Anterior</button><span id="page"></span><button id="news-next">Seguinte</button></div></details></div></aside></div>
<p class="footer">Dados e recursos visuais incorporados ao HTML. Nenhuma API, servidor de grafos ou serviço externo é necessário para explorar o painel; abrir uma notícia acessa o site de origem.</p>
<script>'''+asset_js+'''</script><script id="research-data" type="application/json">'''+json_seguro(payload)+'''</script><script>'''+script+'''</script></body></html>'''


def figuras(folder, snapshots, positions, catalog_nodes, cases):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    catalog = []
    plt.rcParams.update({'svg.fonttype': 'none', 'pdf.fonttype': 42, 'font.size': 10})
    keys = [(y, 'global') for y in [1994, 2000, 2005, 2013, 2019, 2025]]+[(2025, str(i)) for i in cases]
    for year, scope in keys:
        view = snapshots[str(year)][scope]
        fig, ax = plt.subplots(figsize=(11, 8)); ax.axis('off')
        for e in view['edges']:
            a,b = positions[str(e['from'])], positions[str(e['to'])]
            ax.plot([a[0], b[0]], [a[1], b[1]], color='#87939a', alpha=.35, linewidth=min(4, .4+math.log1p(e['weight'])/3), zorder=1)
        for node in view['nodes']:
            info = catalog_nodes[str(node['id'])]; x,y = positions[str(node['id'])]
            ax.scatter([x], [y], s=(8+2.5*math.log1p(node['degree']))**2/3, color=COLORS[info['type']], edgecolors='white', linewidths=.4, zorder=2)
        chosen = sorted(view['nodes'], key=lambda n: (-n['degree'], n['id']))[:10]
        if scope != 'global' and int(scope) not in [n['id'] for n in chosen]:
            chosen += [n for n in view['nodes'] if n['id'] == int(scope)]
        if chosen:
            coords=np.array([positions[str(n['id'])] for n in view['nodes']])
            xmin,ymin=coords.min(axis=0);xmax,ymax=coords.max(axis=0)
            span=max(xmax-xmin,ymax-ymin,100.)
            ordered=sorted(chosen,key=lambda n:(positions[str(n['id'])][0],n['id']))
            for side,part in [('left',ordered[:len(ordered)//2]),('right',ordered[len(ordered)//2:])]:
                part=sorted(part,key=lambda n:(positions[str(n['id'])][1],n['id']))
                for n,ly in zip(part,np.linspace(ymin,ymax,len(part))):
                    xy=positions[str(n['id'])];lx=xmin-.12*span if side=='left' else xmax+.12*span
                    label=textwrap.fill(catalog_nodes[str(n['id'])]['name'],width=26)
                    ax.annotate(label,xy,xytext=(lx,ly),ha='right' if side=='left' else 'left',va='center',fontsize=8,
                        arrowprops={'arrowstyle':'-','color':'#87939a','lw':.6},zorder=3)
        if not view['nodes']: ax.text(.5,.5,'Entidade ainda ausente da rede neste corte',transform=ax.transAxes,ha='center')
        title = 'Seleção por grau' if scope == 'global' else 'Vizinhança de '+catalog_nodes[scope]['name']
        ax.set_title(f'{title} · rede acumulada até {year}\n{len(view["nodes"])} nós e {len(view["edges"])} pares exibidos', fontsize=13)
        ax.legend(handles=[Line2D([0],[0],marker='o',color='w',markerfacecolor=c,label=NAMES[t],markersize=8) for t,c in COLORS.items()],loc='lower center',bbox_to_anchor=(.5,-.07),ncol=3,frameon=False)
        ax.margins(.15);fig.tight_layout()
        stem=f'grafo_{year}_{scope}'
        caption='Subgrafo não dirigido ponderado; cores por tipo e posições iniciais comuns a todos os cortes. A seleção e a poda de pares não alteram a rede completa. Rótulos limitados aos destaques; dados e notícias completos da seleção no painel HTML.'
        for ext in ['svg','png','pdf']:
            filename=stem+'.'+ext;fig.savefig(folder/filename,dpi=220,bbox_inches='tight')
            catalog.append({'file':filename,'cutoff_year':year,'view':scope,'objective':'Inspecionar estrutura e protagonismo no corte acumulado.','caption':caption})
        plt.close(fig)
    return pd.DataFrame(catalog)


NOTAS = '''# Exploração temporal de entidades e destaques automáticos

Os 32 cortes são acumulados desde 1994. Os destaques são totalmente
seletivos por dados: grau decrescente da rede completa do corte, com
inclusão de todos os empatados na 15ª posição. Na presente edição há
15 a 25 destaques por ano. O ranking de competição preserva empates;
o ID apenas ordena a exibição dentro de um empate. Grau é número de
vizinhos distintos na projeção simples não dirigida, não PageRank,
força ponderada ou quantidade de notícias. Não há lista manual de casos.

A vista inicial mostra até max_nos entidades por grau. Ao selecionar uma
entidade no combobox Vista ou na busca, abre-se sua vizinhança de um salto,
limitada por peso do par, grau e ID. Pares entre nós escolhidos são
limitados por peso, priorizando os incidentes ao foco. Limites são
visuais, não filtros científicos. Nós sem ligação visível podem resultar
da poda. Entrar ou sair de uma seleção não é entrar ou sair da rede.
A busca inclui todas as 27.642 entidades da série. Resultados exibem tipo
e ID para distinguir homônimos. O texto e o ID selecionado persistem
ao mudar de ano; ausência anterior é informada, sem inventar grau zero.
O combobox Vista é recalculado pelo ano escolhido. O painel de destaques
inicia recolhido; sua lista é apenas textual, sem botões.

Todos os nomes estão inicialmente visíveis. A opção de desmarcá-los
preserva nomes dos destaques e da entidade acompanhada para reduzir
sobreposição. Preenchimento indica tipo; a entidade acompanhada ganha
borda vermelha e halo discreto; as correspondências da busca
na vista também ganham borda vermelha. Não há aumento de raio ou rótulo. Contorno escuro indica destaque.
Raio visual r=min(35,8+2,5*ln(1+k)), sem acréscimo para a busca. O tamanho não é diretamente proporcional ao grau.
A mesma transformação é usada em todos os anos. Não é escala de área
proporcional nem distância semântica. Espessura usa ocorrências do par.

A física ForceAtlas2Based inicia ativada e pode ser desativada; a opção
é mantida ao trocar de ano ou vista. Restaurar posições desativa a
física e recupera as âncoras. As posições iniciais dos nós que aparecem
nas vistas globais de referência e nos cinco principais focos finais
usam disposição por componentes com semente 42 e pesos finais log1p,
seguida de compressão radial asinh(r/40). As demais posições iniciais
usam círculo determinístico por ID, sendo reorganizadas pela física.
É uma apresentação retrospectiva. Mover nós não altera o grafo ou
qualquer métrica. A física faz a comparação espacial entre anos exigir
cautela; desligá-la e restaurar posições facilita a inspeção.

O HTML incorpora dados completos dos cortes e calcula subgrafos no
navegador, permitindo pesquisar entidades fora dos destaques. Todas
as notícias de suporte dos objetos escolhidos podem ser consultadas
até o ano do corte, com exemplos, busca, paginação e CSV. O CSV inclui
a lista completa da seleção, mesmo com busca textual ativa. Notícias
de nós exigem participação em relação retida por padrão; a opção
adicional inclui menções com NER mesmo sem RE concluída. Títulos,
links, categorias e atributos são preservados; textos integrais não
são incorporados. Links abrem apenas por ação do usuário.

Composição dirigida e tipada dos pares é preservada para inspeção;
a representação visual permanece não dirigida ponderada. Cores são
tipos, não comunidades. Não há detecção de comunidades temporais,
novas relações, fusões de entidades ou correção de tipos nesta etapa.
A classificação herdada de EUA como ORGANIZACAO continua sendo uma
limitação a corrigir nos dados de origem em edição própria; não existe
reclassificação cosmética no HTML. Os indicadores são os da edição
conferida. Cobertura e volume anual contextualizam o crescimento.
Em 2021 não há RE concluída e a topologia repete 2020.

Recursos estão incorporados: não há CDN, fetch, API ou Neo4j para
explorar o HTML. Dados compactos usam índices locais para notícias,
pares e rótulos, com catálogos para recuperar seus identificadores
originais. As tabelas exportadas preservam os identificadores científicos.
O HTML cresce por incluir a série e a rastreabilidade completas; isso
evita carregar milhares de arquivos ou depender de servidor local.
As figuras estáticas são seleções de apresentação: seis cortes globais
e os cinco maiores graus finais, sem restringir os outros anos no HTML.
'''


def limpar_visualizacoes_anteriores(base, target, package):
    """Remove somente saídas reconhecidas desta etapa, após validar a atual."""
    validate_manifest(target)
    with zipfile.ZipFile(package) as archive:
        if archive.testzip() is not None:
            raise ValueError('Pacote atual inválido; versões anteriores preservadas.')
    removed=[];warnings=[]
    for candidate in sorted(base.iterdir()):
        if candidate in (target, package) or candidate.is_symlink():
            continue
        recognized=False
        if candidate.is_dir() and re.fullmatch(r'[0-9a-f]{20}', candidate.name):
            try:
                manifest=json.loads((candidate/'manifesto.json').read_text(encoding='utf-8'))
                schema=manifest.get('schema', '')
                recognized=('temporal' in schema and 'visual' in schema
                    and str(manifest.get('snapshot_sha256','')).startswith(candidate.name)
                    and 'painel_temporal.html' in manifest.get('outputs_sha256', {}))
            except (OSError, ValueError, TypeError):
                continue
        elif candidate.is_dir() and re.fullmatch(r'\.vistas_[a-z0-9_]{8}', candidate.name):
            recognized=True
        elif candidate.is_file():
            recognized=bool(re.fullmatch(r'Resumo_Visualizacoes_Temporais_[0-9a-f]{12}(?:_[0-9a-f]{6})?\.zip', candidate.name))
        if recognized:
            try:
                if candidate.is_dir():shutil.rmtree(candidate)
                else:candidate.unlink()
                removed.append(candidate.name)
            except OSError as exc:
                warnings.append(candidate.name+': '+str(exc))
    return {'removed_previous_visualization_artifacts':removed,'cleanup_warnings':warnings}


def gerar_visualizacoes_temporais(projeto, *, executar=False, max_nos=100, max_pares=250,
                                  assinatura_temporal_esperada=None, assinatura_protagonismo_esperada=None):
    start=perf_counter();root=Path(projeto).resolve()
    if root.name=='PROJECT_EXTRACAO':raise ValueError('Use o projeto de análise.')
    if isinstance(max_nos,bool) or not isinstance(max_nos,int) or max_nos<25:
        raise ValueError('Use pelo menos 25 nós por vista para comportar os destaques e empates.')
    if isinstance(max_pares,bool) or not isinstance(max_pares,int) or max_pares<1:
        raise ValueError('Limite de pares deve ser inteiro positivo.')
    origem,meta=carregar_redes_temporais(root)
    if assinatura_temporal_esperada and meta['snapshot_sha256']!=assinatura_temporal_esperada:raise ValueError('Série temporal inesperada.')
    traj,pm=carregar_trajetorias(root,assinatura_protagonismo_esperada)
    if pm['temporal_snapshot_sha256']!=meta['snapshot_sha256']:raise ValueError('Trajetórias de outra edição.')
    if not executar:
        out={'mode':'DRY_RUN','snapshot_count':32,'automatic_highlights_minimum':15,'include_boundary_ties':True,
            'search_scope':'ALL_TEMPORAL_ENTITIES','persistent_search':True,'physics_initially_enabled':True,
            'all_labels_initially_visible':True,'api_calls':0,'neo4j_connections':0,'files_written':0}
        print('[VISTAS TEMPORAIS]',json.dumps(out));return out
    import networkx as nx
    import comunidades_visualizacao as vis
    assets,style=vis.ativos_vis();interface=Path(__file__).with_name('temporal_interface.js')
    spec={'schema':'temporal-evidence-visualization-2','version':VERSION,'code_sha256':sha(Path(__file__)),
        'interface_sha256':sha(interface),'layout_helper_sha256':sha(Path(vis.__file__)),
        'vis_assets_sha256':json_sha([assets,style]),'temporal_snapshot_sha256':meta['snapshot_sha256'],
        'protagonism_snapshot_sha256':pm['snapshot_sha256'],'max_nodes':max_nos,'max_pairs':max_pares,
        'highlight_criterion':'degree by current year; include ties at rank 15',
        'networkx_version':nx.__version__,'numpy_version':np.__version__}
    signature=json_sha(spec);base=root/'resultados/temporal/visualizacoes';base.mkdir(parents=True,exist_ok=True)
    target=base/signature[:20];lock=base/'geracao.lock';temp=None
    try:lock.mkdir()
    except FileExistsError:raise RuntimeError('Outra geração pode estar ativa; confira o bloqueio.') from None
    try:
        if target.exists():
            saved=validate_manifest(target)
            if saved['snapshot_sha256']!=signature:raise ValueError('Saída incompatível.')
            summary=saved['summary']
        else:
            temp=Path(tempfile.mkdtemp(prefix='.vistas_',dir=base))
            data=pd.read_csv(traj/'trajetorias_entidades.csv.gz');coverage=pd.read_csv(origem/'cobertura_anual.csv')
            final=origem/'2025';news=pd.read_csv(final/'noticias.csv.gz',keep_default_na=False).sort_values('news_id').reset_index(drop=True)
            news_index=dict(zip(news.news_id,range(len(news))))
            nn=pd.read_csv(final/'nos_noticias.csv.gz',keep_default_na=False)
            evidence=pd.read_csv(final/'arestas_noticias.csv.gz',keep_default_na=False)
            mapping=pd.read_csv(final/'vinculos_arestas_projecoes.csv.gz')
            pe=evidence.merge(mapping[['edge_id','pair_id']],on='edge_id',validate='many_to_one')
            pe=pe.groupby(['pair_id','news_id','news_version_id','publication_year'],as_index=False).occurrence_count.sum()
            finalpairs=pd.read_csv(final/'ponderada_nao_dirigida.csv.gz').sort_values('pair_id').reset_index(drop=True)
            pair_index=dict(zip(finalpairs.pair_id,range(len(finalpairs))))
            labels=sorted(pd.read_csv(final/'arestas.csv.gz').label.unique().tolist());label_index={v:i for i,v in enumerate(labels)}
            finalnodes=data.loc[data.cutoff_year.eq(2025)].sort_values('entity_group_id')
            catalog={str(r.entity_group_id):{'name':r.entity_group_name,'type':r.ent_label} for r in finalnodes.itertuples(index=False)}
            series={};ranks=[];main_nodes=[];main_pairs=[];snapshots={};anchor_ids=set()
            figure_ids=destaques_automaticos(finalnodes).head(5).entity_group_id.astype(int).tolist()
            for year in ANOS:
                nodes=data.loc[data.cutoff_year.eq(year)].copy()
                pairs=pd.read_csv(origem/str(year)/'ponderada_nao_dirigida.csv.gz')
                typed=pd.read_csv(origem/str(year)/'arestas.csv.gz')
                if nodes.duplicated('entity_group_id').any() or int(nodes.degree.sum())!=2*len(pairs):raise ValueError('Topologia e trajetórias incompatíveis.')
                prior=pe.loc[pe.publication_year.le(year)].groupby('pair_id').agg(weight=('occurrence_count','sum'),docs=('news_id','nunique'))
                expected=prior.reindex(pairs.pair_id)
                if not np.array_equal(expected.weight.to_numpy(),pairs.weight.to_numpy()) or not np.array_equal(expected.docs.to_numpy(),pairs.distinct_news_count.to_numpy()):raise ValueError('Evidências de pares incompatíveis com o corte.')
                support=nn.loc[nn.publication_year.le(year)]
                mentions=support.groupby('entity_group_id').news_id.nunique()
                related=support.loc[support.relation_participation_count.gt(0)].groupby('entity_group_id').news_id.nunique()
                if not np.array_equal(nodes.entity_group_id.map(mentions).fillna(0).to_numpy(),nodes.distinct_news_count.to_numpy()):raise ValueError('Menções documentais incompatíveis.')
                if not np.array_equal(nodes.entity_group_id.map(related).fillna(0).to_numpy(),nodes.relation_news_count.to_numpy()):raise ValueError('Suporte relacional incompatível.')
                leaders=destaques_automaticos(nodes);leader_ids=leaders.entity_group_id.astype(int).tolist()
                n,e=selecionar_vista(nodes,pairs,max_nos=max_nos,max_pares=max_pares)
                if not set(leader_ids).issubset(set(n.entity_group_id)):raise ValueError('Aumente max_nos para acomodar todos os destaques empatados.')
                main_nodes.append(n.assign(view='global'));main_pairs.append(e.assign(cutoff_year=year,view='global'))
                snapshots[str(year)]={}
                for scope,foco in [('global',None)]+([(str(i),i) for i in figure_ids] if year==2025 else []):
                    vn,ve=selecionar_vista(nodes,pairs,foco=foco,max_nos=max_nos,max_pares=max_pares)
                    anchor_ids.update(vn.entity_group_id.astype(int))
                    snapshots[str(year)][scope]={'nodes':[{'id':int(r.entity_group_id),'degree':int(r.degree)} for r in vn.itertuples(index=False)],
                        'edges':[{'id':r.pair_id,'from':int(r.source_id),'to':int(r.target_id),'weight':int(r.weight)} for r in ve.itertuples(index=False)]}
                ranks.append(leaders[['entity_group_id','entity_group_name','ent_label','degree','degree_rank','cutoff_year']])
                node_cols=['entity_group_id','degree','weighted_strength','degree_rank','new_neighbors','distinct_news_count','relation_news_count']
                nd=nodes[node_cols].copy()
                if year==1994:nd['new_neighbors']=-1
                pa=pairs[['pair_id','source_id','target_id','weight','distinct_news_count']].copy();pa['pair_id']=pa.pair_id.map(pair_index)
                td=typed[['source_id','target_id','label','weight']].copy();td['u']=td[['source_id','target_id']].min(axis=1);td['v']=td[['source_id','target_id']].max(axis=1)
                pmapping=pairs[['pair_id','source_id','target_id']].rename(columns={'source_id':'u','target_id':'v'})
                td=td.merge(pmapping,on=['u','v'],validate='many_to_one');td['pair_id']=td.pair_id.map(pair_index);td['label']=td.label.map(label_index)
                weights=td.groupby('pair_id').weight.sum()
                if not np.array_equal(pa.pair_id.map(weights).to_numpy(),pa.weight.to_numpy()):raise ValueError('Composição tipada não recompõe pesos dos pares.')
                series[str(year)]={'nodes':nd.astype('int64').values.tolist(),'pairs':pa.astype('int64').values.tolist(),
                    'typed':td[['pair_id','source_id','target_id','label','weight']].astype('int64').values.tolist(),'leaders':leader_ids}
                print(f'[VISTAS TEMPORAIS] {year}: {len(nodes):,} nós pesquisáveis; {len(leaders)} destaques automáticos; dados conferidos.',flush=True)
            anchors=finalnodes.loc[finalnodes.entity_group_id.isin(anchor_ids)]
            union=finalpairs.loc[finalpairs.source_id.isin(anchor_ids)&finalpairs.target_id.isin(anchor_ids)]
            pos=vis.layout_vista(anchors,union)
            center=np.median([pos[n['id']] for n in snapshots['2025']['global']['nodes']],axis=0);positions={}
            for gid,xy in pos.items():
                delta=np.array(xy)-center;r=float(np.linalg.norm(delta));point=delta*(300*math.asinh(r/40)/r) if r else np.zeros(2)
                positions[str(gid)]=point.tolist()
            for gid in catalog:
                if gid not in positions:
                    value=int(gid);angle=(value*.61803398875%1)*2*math.pi;radius=850+(value%251)
                    positions[gid]=[radius*math.cos(angle),radius*math.sin(angle)]
            node_refs={str(int(gid)):[[int(news_index[r.news_id]),int(r.relation_participation_count)] for r in g.itertuples(index=False)] for gid,g in nn.groupby('entity_group_id')}
            pair_refs={str(int(pair_index[pid])):sorted({int(news_index[nid]) for nid in g.news_id}) for pid,g in pe.groupby('pair_id')}
            columns=['news_id','news_version_id','title','link','author','source','publication_date','publication_year','category_grouped','ner_availability','re_state']
            payload={'version':2,'years':list(ANOS),'reference_years':meta['reference_cutoff_years'],'highlight_minimum':15,
                'max_nodes':max_nos,'max_pairs':max_pares,'series':series,'node_catalog':catalog,'positions':positions,
                'pair_catalog':finalpairs[['pair_id','source_id','target_id']].values.tolist(),'labels':labels,
                'news':registros(news[columns]),'node_news':node_refs,'pair_news':pair_refs,
                'support_news':sorted({int(news_index[x]) for x in evidence.news_id}),
                'coverage':{str(int(r['publication_year'])):r for r in registros(coverage)},'type_colors':COLORS,'type_names':NAMES}
            (temp/'painel_temporal.json').write_text(json_seguro(payload),encoding='utf-8')
            (temp/'painel_temporal.html').write_text(gerar_html(payload,interface.read_text(encoding='utf-8'),assets,style),encoding='utf-8')
            for name,table in [('destaques_automaticos.csv',pd.concat(ranks,ignore_index=True)),
                ('nos_vista_inicial.csv.gz',pd.concat(main_nodes,ignore_index=True)),('pares_vista_inicial.csv.gz',pd.concat(main_pairs,ignore_index=True)),
                ('nos_noticias.csv.gz',nn),('pares_noticias.csv.gz',pe),('noticias.csv.gz',news[columns]),
                ('posicoes.csv',pd.DataFrame([{'entity_group_id':int(k),'x':v[0],'y':v[1]} for k,v in positions.items()]))]:write_csv(temp,name,table)
            fc=figuras(temp,snapshots,positions,catalog,figure_ids);write_csv(temp,'catalogo_figuras.csv',fc)
            (temp/'LEIA_ME.md').write_text(NOTAS,encoding='utf-8')
            summary={'snapshot_count':32,'searchable_entities':len(catalog),'automatic_highlights_minimum':15,
                'include_boundary_ties':True,'annual_highlight_counts':{year:len(s['leaders']) for year,s in series.items()},
                'manual_case_ids':[],'html_files':1,'figure_files':len(fc),'support_news':len(payload['support_news']),
                'physics_initially_enabled':True,'all_labels_initially_visible':True,'persistent_search':True,
                'all_pair_weights_and_document_counts_verified':True,'complete_evidence_lists':True,
                'external_assets_required':False,'api_calls':0,'neo4j_connections':0,'network_modified':False,'entity_groups_merged':0,'canonical_types_changed':0}
            if carregar_redes_temporais(root)[1]['snapshot_sha256']!=meta['snapshot_sha256']:raise ValueError('Série temporal alterada.')
            if carregar_trajetorias(root,assinatura_protagonismo_esperada)[1]['snapshot_sha256']!=pm['snapshot_sha256']:raise ValueError('Trajetórias alteradas.')
            atomic_json(temp/'manifesto.json',{**spec,'snapshot_sha256':signature,'summary':summary,
                'created_at_utc':datetime.now(timezone.utc).isoformat(),'outputs_sha256':{p.name:sha(p) for p in sorted(temp.iterdir())}})
            validate_manifest(temp);temp.rename(target);temp=None
        package=base/f'Resumo_Visualizacoes_Temporais_{signature[:12]}.zip'
        package_temp=base/'.pacote_vistas.tmp'
        try:
            with zipfile.ZipFile(package_temp,'w',zipfile.ZIP_DEFLATED) as z:
                for p in sorted(target.iterdir()):z.write(p,p.name)
            with zipfile.ZipFile(package_temp) as z:
                if z.testzip() is not None:raise ValueError('Falha na validação do ZIP.')
            package_temp.replace(package)
        finally:
            package_temp.unlink(missing_ok=True)
        atomic_json(base/'atual.json',{'folder':target.name,'snapshot_sha256':signature})
        summary={**summary,**limpar_visualizacoes_anteriores(base,target,package)}
    finally:
        if temp is not None and temp.exists():shutil.rmtree(temp)
        lock.rmdir()
    print('[VISTAS TEMPORAIS]',json.dumps(summary,ensure_ascii=False));print('[VISTAS TEMPORAIS] Painel:',target/'painel_temporal.html');print('[VISTAS TEMPORAIS] Pacote:',package)
    return {**summary,'elapsed_seconds_this_run':perf_counter()-start,'output_directory':target,'index_html':target/'painel_temporal.html','package':package,'snapshot_sha256':signature}
