"""Caracterização editorial e visualizações de comunidades com proveniência navegável."""
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
import html
import colorsys
import json
import math
import os
import re
import shutil
import tempfile
import uuid
import zipfile
import numpy as np
import pandas as pd
from redes_comunidades import carregar_comunidades
from redes_construcao import carregar_rede
from redes_centralidades import TYPE_COLORS, TYPE_NAMES
from re_consolidacao import sha, json_sha, write_csv, validate_manifest
from re_execucao import atomic_json

VERSION='2.0.0'
SOURCE_COLORS={'CNN Brasil':'tab:blue','Folha de S.Paulo':'tab:orange','G1':'tab:green'}
CSS='''body{margin:0;font:15px system-ui,sans-serif;color:#263238;background:#f5f7fa}header{padding:18px 24px;background:white;border-bottom:1px solid #ccd6dd}h1{font-size:23px;margin:0 0 8px}h2{font-size:18px}p{line-height:1.45}button,input,select{font:inherit;padding:7px;border:1px solid #b6c3cc;border-radius:5px;background:white}button{cursor:pointer}button:hover{background:#e9f1f6}a{color:#175d94}small{display:block;color:#52636d;margin:4px 0 12px}.controls{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.layout{display:grid;grid-template-columns:minmax(0,1fr) 420px;gap:14px;padding:14px}.main,.panel{background:white;padding:14px;border-radius:8px}.panel{max-height:78vh;overflow:auto}#mynetwork{height:67vh;border:1px solid #d6e0e6}#node-results{max-height:110px;overflow:auto}#node-results button{font-size:12px;margin:2px}#legend span{display:inline-block;font-size:12px;margin:4px 12px 4px 0}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:8px;border-bottom:1px solid #e1e7eb;font-size:13px}#community-table{max-height:67vh;overflow:auto}li{margin-bottom:12px}ul{padding-left:20px}.notice{padding:10px;background:#fff6df;border-left:4px solid #d5a63e}details{margin-top:15px}@media(max-width:1000px){.layout{grid-template-columns:1fr}.panel{max-height:none}#mynetwork{height:65vh}}'''


def registros(frame):
    return json.loads(frame.to_json(orient='records',force_ascii=False))


def json_seguro(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e').replace('\u2028','\\u2028').replace('\u2029','\\u2029')


def noticias_comunidades(assignments,edges,evidence,news):
    """Une IDs de notícias; uma notícia pode apoiar mais de uma comunidade e papel."""
    if not news.news_id.is_unique or not edges.edge_id.is_unique:
        raise ValueError('Notícias ou arestas com IDs duplicados.')
    keys=['news_id','news_version_id']
    if evidence.duplicated(['edge_id']+keys).any():raise ValueError('Vínculo aresta-notícia repetido.')
    links=evidence[['edge_id']+keys].merge(edges[['edge_id','source_id','target_id']],on='edge_id',validate='many_to_one',how='left')
    if links.source_id.isna().any():raise ValueError('Evidência sem aresta correspondente.')
    known=links.merge(news[keys],on=keys,how='left',indicator=True,validate='many_to_one')
    if not known['_merge'].eq('both').all():raise ValueError('Evidência sem versão de notícia correspondente.')
    result=[]
    for run,part in assignments.groupby('run_id',sort=False):
        if not part.entity_group_id.is_unique:raise ValueError('Partição com entidade repetida.')
        mapping=part.set_index('entity_group_id').community_id
        x=links.copy();x['a']=x.source_id.map(mapping);x['b']=x.target_id.map(mapping)
        if x[['a','b']].isna().any().any():raise ValueError('Extremo de relação sem comunidade.')
        x['internal_support']=x.a.eq(x.b);x['boundary_support']=~x.internal_support
        both=pd.concat([x[['a']+keys+['internal_support','boundary_support']].rename(columns={'a':'community_id'}),
                        x[['b']+keys+['internal_support','boundary_support']].rename(columns={'b':'community_id'})])
        both=both.groupby(['community_id']+keys,as_index=False,sort=True)[['internal_support','boundary_support']].max()
        both.insert(0,'run_id',run);result.append(both)
    result=pd.concat(result,ignore_index=True)
    result=result.merge(news,on=keys,validate='many_to_one',how='left')
    for dimension in ['source','publication_year','category_grouped']:
        result[dimension]=result[dimension].fillna('').astype(str).replace('', 'SEM_INFORMACAO')
    return result


def caracterizar_suporte(community_news,stats):
    key=['run_id','community_id'];counts=[];profiles=[]
    for scope,mask in [('any',np.ones(len(community_news),dtype=bool)),
                       ('internal',community_news.internal_support),('boundary',community_news.boundary_support)]:
        subset=community_news.loc[mask]
        count=subset.groupby(key).news_id.nunique().rename(scope+'_news').reset_index();counts.append(count)
        for dimension in ['source','publication_year','category_grouped']:
            profile=subset.groupby(key+[dimension]).news_id.nunique().rename('news_count').reset_index().rename(columns={dimension:'value'})
            profile['dimension']=dimension;profile['scope']=scope;profiles.append(profile)
    metrics=stats.copy()
    for count in counts:metrics=metrics.merge(count,on=key,how='left',validate='one_to_one')
    for name in ['any_news','internal_news','boundary_news']:metrics[name]=metrics[name].fillna(0).astype('int64')
    if (metrics.any_news<metrics.internal_news).any() or (metrics.any_news<metrics.boundary_news).any():
        raise ValueError('Contagem de suporte inconsistente.')
    profile=pd.concat(profiles,ignore_index=True)
    for scope in ['any','internal','boundary']:
        for dimension in ['source','publication_year','category_grouped']:
            observed=profile.loc[profile.scope.eq(scope)&profile.dimension.eq(dimension)].groupby(key).news_count.sum()
            expected=metrics.set_index(key)[scope+'_news']
            if not observed.reindex(expected.index,fill_value=0).eq(expected).all():
                raise ValueError('Distribuição editorial não recompõe a quantidade de notícias.')
    return metrics,profile


def selecionar_vista(nodes,edges,*,community_id=None,max_nodes=100,max_edges=250):
    """Seleciona pares não dirigidos e preserva suas direções para inspeção."""
    scope_nodes=nodes if community_id is None else nodes.loc[nodes.community_id.eq(community_id)]
    ids=set(scope_nodes.entity_group_id)
    full=edges.loc[edges.source_id.isin(ids)&edges.target_id.isin(ids)].copy()
    strength=pd.concat([full[['source_id','weight']].rename(columns={'source_id':'entity_group_id'}),
                        full[['target_id','weight']].rename(columns={'target_id':'entity_group_id'})]).groupby('entity_group_id').weight.sum()
    ranked=scope_nodes.copy();ranked['scope_strength']=ranked.entity_group_id.map(strength).fillna(0)
    chosen=ranked.sort_values(['scope_strength','entity_group_id'],ascending=[False,True]).head(max_nodes).copy()
    selected=set(chosen.entity_group_id)
    visible=full.loc[full.source_id.isin(selected)&full.target_id.isin(selected)].copy()
    columns=['visual_edge_id','source_id','target_id','weight','typed_edge_ids','labels']
    if visible.empty:
        pair_frame=pd.DataFrame(columns=columns);directed=pd.DataFrame(columns=columns)
    else:
        visible['u']=visible[['source_id','target_id']].min(axis=1)
        visible['v']=visible[['source_id','target_id']].max(axis=1)
        pair_frame=visible.groupby(['u','v'],as_index=False).agg(weight=('weight','sum'),
            typed_edge_ids=('edge_id',lambda x:sorted(x)),labels=('label',lambda x:sorted(set(x))))
        pair_frame=pair_frame.rename(columns={'u':'source_id','v':'target_id'})
        pair_frame=pair_frame.sort_values(['weight','source_id','target_id'],ascending=[False,True,True]).head(max_edges).reset_index(drop=True)
        pair_frame['visual_edge_id']=['u'+str(a)+'_'+str(b) for a,b in zip(pair_frame.source_id,pair_frame.target_id)]
        selected_pairs=set(zip(pair_frame.source_id,pair_frame.target_id))
        visible=visible.loc[[pair in selected_pairs for pair in zip(visible.u,visible.v)]]
        directed=visible.groupby(['source_id','target_id'],as_index=False).agg(weight=('weight','sum'),
            typed_edge_ids=('edge_id',lambda x:sorted(x)),labels=('label',lambda x:sorted(set(x))))
        directed=directed.sort_values(['source_id','target_id']).reset_index(drop=True)
        directed['visual_edge_id']=['d'+str(a)+'_'+str(b) for a,b in zip(directed.source_id,directed.target_id)]
        if float(pair_frame.weight.sum())!=float(directed.weight.sum()):raise ValueError('Pesos incompatíveis entre as duas representações.')
    visible_ids=set(pair_frame.source_id).union(pair_frame.target_id)
    return chosen,pair_frame,directed,{'full_nodes':len(scope_nodes),'full_typed_edges':len(full),
        'displayed_nodes':len(chosen),'displayed_undirected_pairs':len(pair_frame),'inspection_directed_pairs':len(directed),
        'nodes_without_visible_edges':len(selected-visible_ids),
        'criterion':'Top nodes by incident record weight; top unordered pairs by weights summed over both directions and all labels; ties by IDs.'}


def paleta_comunidades(community_ids):
    initial=['#1f77b4','#ff7f0e','#2ca02c','#d62728','#9467bd','#8c564b','#e377c2','#7f7f7f','#bcbd22','#17becf',
             '#aec7e8','#ffbb78','#98df8a','#ff9896','#c5b0d5','#c49c94','#f7b6d2','#c7c7c7','#dbdb8d','#9edae5']
    colors={}
    for i,c in enumerate(community_ids):
        if i<len(initial):color=initial[i]
        else:
            rgb=colorsys.hsv_to_rgb((i*.38196601125)%1,.65,.8)
            color='#'+''.join(f'{int(round(v*255)):02x}' for v in rgb)
        colors[int(c)]=color
    return colors


def layout_vista(nodes,pairs):
    import networkx as nx
    graph=nx.Graph();graph.add_nodes_from(map(int,nodes.entity_group_id))
    for row in pairs.itertuples(index=False):
        a,b=int(row.source_id),int(row.target_id)
        if graph.has_edge(a,b):graph[a][b]['raw_weight']+=float(row.weight)
        else:graph.add_edge(a,b,raw_weight=float(row.weight))
    if not graph:return {}
    for a,b in graph.edges:graph[a][b]['layout_weight']=math.log1p(graph[a][b]['raw_weight'])
    parts=sorted(nx.connected_components(graph),key=lambda p:(-len(p),min(p)))
    positions={}
    for index,part in enumerate(parts):
        sub=graph.subgraph(sorted(part))
        scale=500 if index==0 else min(260,65*math.sqrt(len(part)))
        angle=2*math.pi*(index-1)/max(1,len(parts)-1)
        center=(0,0) if index==0 else (850*math.cos(angle),850*math.sin(angle))
        pos=nx.spring_layout(sub,seed=42,weight='layout_weight',iterations=200,scale=scale)
        for key,value in pos.items():positions[int(key)]=[float(value[0]+center[0]),float(-value[1]+center[1])]
    return positions


def ativos_vis():
    import pyvis
    base=Path(pyvis.__file__).parent/'templates/lib/vis-9.1.2'
    if not (base/'vis-network.min.js').exists():
        raise RuntimeError('Instale pyvis==0.3.2 para disponibilizar os recursos vis-network previstos.')
    return (base/'vis-network.min.js').read_text(encoding='utf-8'),(base/'vis-network.css').read_text(encoding='utf-8')


def pagina_html(payload,*,title,note,graph=False):
    interface=Path(__file__).with_name('comunidades_interface.js').read_text(encoding='utf-8')
    asset_script,asset_style=ativos_vis() if graph else ('','')
    main=('''<div class="controls"><select id="representation"><option value="community">Comunidades — não dirigida</option><option value="semantic">Inspecionar relações semânticas — dirigida</option></select><select id="color-mode"><option value="community">Cor por comunidade</option><option value="type">Cor por tipo de entidade</option></select></div><p id="representation-note" class="notice"></p><div class="controls"><input id="find-node" placeholder="Buscar entidade ou ID"><label><input type="checkbox" id="show-labels">Todos os nomes</label></div><div id="node-results"></div><div id="legend"></div><div id="mynetwork"></div><div class="controls"><button id="fit">Enquadrar</button><button id="physics">Ativar física</button><button id="png">Exportar PNG</button><button id="svg">Exportar SVG</button></div>'''
        if graph else '''<div class="controls"><select id="partition"></select><input id="community-search" placeholder="Buscar ID ou entidades em destaque"><select id="support-scope"><option value="internal">Suporte interno</option><option value="any">Qualquer relação incidente</option></select></div><p id="community-count"></p><div id="community-table"><table><thead><tr><th>Comunidade</th><th>Entidades</th><th>Notícias internas</th><th>Conectividade</th><th>Destaques por PageRank global</th></tr></thead><tbody id="community-rows"></tbody></table></div>''')
    panel='''<aside class="panel"><h2 id="selection-title"></h2><div id="selection-detail"></div><a id="open-graph" hidden>Abrir vista do grafo desta comunidade</a><h2 id="evidence-title"></h2><h3>Exemplos</h3><ul id="examples"></ul><details><summary>Lista completa de notícias</summary><input id="news-search" placeholder="Filtrar notícias"><p id="news-count"></p><button id="csv">Exportar lista completa em CSV</button><ul id="full-news"></ul></details></aside>'''
    return '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)+'</title><style>'+asset_style+CSS+'</style></head><body><header><h1>'+html.escape(title)+'</h1><p>'+html.escape(note)+'</p><a href="indice_comunidades.html">Painel de comunidades</a></header><div class="layout"><main class="main">'+main+'</main>'+panel+'</div><script>'+asset_script+'</script><script id="research-data" type="application/json">'+json_seguro(payload)+'</script><script>'+interface+'</script></body></html>'


def noticia_lookup(news):
    columns=['news_id','news_version_id','title','link','source','publication_date','category_grouped','author']
    return {r['news_id']:r for r in registros(news[columns].fillna(''))}


def preparar_grafo(nodes,pairs,semantic_pairs,*,positions,node_news,edge_news,news_lookup,scope_news,selection_note,default_color_mode='community'):
    from pyvis.network import Network
    net=Network(directed=False,cdn_resources='in_line',height='700px')
    communities=nodes.groupby('community_id').size().sort_index().sort_values(ascending=False,kind='stable')
    colors=(nodes.groupby('community_id').community_color.first().to_dict() if 'community_color' in nodes else paleta_comunidades(communities.index))
    details={};edge_details={}
    label_ids=set(nodes.nlargest(15,'scope_strength').entity_group_id)
    for row in nodes.itertuples(index=False):
        gid=int(row.entity_group_id);name=str(row.entity_group_name)
        color=TYPE_COLORS[row.ent_label] if default_color_mode=='type' else colors[int(row.community_id)]
        details[str(gid)]={'name':name,'type':row.ent_label,'community_id':int(row.community_id),
            'neighbor_degree':int(row.neighbor_degree),'weighted_strength':int(row.weighted_strength),
            'type_color':TYPE_COLORS[row.ent_label],'community_color':colors[int(row.community_id)]}
        x,y=positions[gid];size=min(35,8+2.5*math.log1p(float(row.scope_strength)))
        net.add_node(gid,label=name if gid in label_ids else '',title=html.escape(name)+'<br>Grupo '+str(gid),
                     x=x,y=y,size=size,color=color)
    names={int(r.entity_group_id):str(r.entity_group_name) for r in nodes.itertuples(index=False)}
    def add_details(row,directed):
        aid=str(row.visual_edge_id);a,b=int(row.source_id),int(row.target_id)
        edge_details[aid]={'from_name':names[a],'to_name':names[b],'weight':int(row.weight),
            'labels':row.labels,'typed_edge_ids':row.typed_edge_ids,'news_count':len(edge_news.get(aid,[])),'directed':directed}
    for row in pairs.itertuples(index=False):
        add_details(row,False);a,b=int(row.source_id),int(row.target_id);aid=str(row.visual_edge_id)
        original=semantic_pairs.loc[((semantic_pairs.source_id==a)&(semantic_pairs.target_id==b))|((semantic_pairs.source_id==b)&(semantic_pairs.target_id==a))]
        edge_details[aid]['original_directions']=[names[int(r.source_id)]+' → '+names[int(r.target_id)]+': '+', '.join(r.labels) for r in original.itertuples(index=False)]
        net.add_edge(a,b,id=aid,width=min(6,1+math.log1p(row.weight)/2),
            color={'color':'#87939a','opacity':.4},arrows='',title='Associação não dirigida; peso '+str(int(row.weight)))
    semantic_edges=[]
    for row in semantic_pairs.itertuples(index=False):
        add_details(row,True)
        semantic_edges.append({'id':str(row.visual_edge_id),'from':int(row.source_id),'to':int(row.target_id),
            'width':min(6,1+math.log1p(row.weight)/2),'color':{'color':'#87939a','opacity':.4},'arrows':'to',
            'title':html.escape(', '.join(row.labels)),'smooth':{'enabled':True,'type':'curvedCW','roundness':.12}})
    needed=set(scope_news)
    for value in list(node_news.values())+list(edge_news.values()):needed.update(value)
    payload={'mode':'graph','default_color_mode':default_color_mode,'semantic_edges':semantic_edges,
        'graph':{'nodes':net.nodes,'edges':net.edges,'options':{
        'nodes':{'shape':'dot','font':{'size':12}},'edges':{'smooth':{'enabled':False}},
        'interaction':{'hover':True,'keyboard':True},'physics':{'enabled':False,'solver':'forceAtlas2Based',
            'forceAtlas2Based':{'gravitationalConstant':-55,'centralGravity':.01,'springLength':120,'springConstant':.05,'damping':.4,'avoidOverlap':.4}},
        'layout':{'randomSeed':42}}},'news':{k:news_lookup[k] for k in sorted(needed)},
        'nodeDetails':details,'edgeDetails':edge_details,'nodeNews':node_news,'edgeNews':edge_news,
        'scopeNews':scope_news,'selection_note':selection_note,
        'communityLegend':[{'name':'C'+str(c),'color':colors[int(c)]} for c in communities.index]}
    return payload


def figuras_grafo(folder,stem,nodes,pairs,positions,title,*,tamanho_fonte=10,largura=10,altura=8,max_rotulos=15,color_mode='community'):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    plt.rcParams.update({'font.size':tamanho_fonte,'svg.fonttype':'none','pdf.fonttype':42})
    fig,ax=plt.subplots(figsize=(largura,altura));ax.set_title(title+'\nProjeção não dirigida ponderada — vista parcial; posições sem significado geográfico',fontsize=tamanho_fonte+1)
    for row in pairs.itertuples(index=False):
        a,b=positions[int(row.source_id)],positions[int(row.target_id)]
        ax.plot([a[0],b[0]],[-a[1],-b[1]],color='#87939a',alpha=.3,lw=min(3,.4+math.log1p(row.weight)/3))
    community_colors=(nodes.groupby('community_id').community_color.first().to_dict() if 'community_color' in nodes else paleta_comunidades(sorted(nodes.community_id.unique())))
    if color_mode=='type':groups=[(TYPE_NAMES[k],v,nodes.loc[nodes.ent_label.eq(k)]) for k,v in TYPE_COLORS.items()]
    else:groups=[('C'+str(k),v,nodes.loc[nodes.community_id.eq(k)]) for k,v in community_colors.items()]
    for label,color,part in groups:
        xy=[positions[int(i)] for i in part.entity_group_id]
        if xy:ax.scatter([p[0] for p in xy],[-p[1] for p in xy],s=[40+24*math.log1p(float(x)) for x in part.scope_strength],color=color,alpha=.85,edgecolors='white',linewidths=.5)
    labeled=nodes.sort_values(['scope_strength','entity_group_id'],ascending=[False,True]).head(max_rotulos).copy()
    labeled['px']=[positions[int(i)][0] for i in labeled.entity_group_id]
    labeled['py']=[-positions[int(i)][1] for i in labeled.entity_group_id]
    labeled=labeled.sort_values(['px','entity_group_id'])
    coordinates=np.array(list(positions.values()))
    for side,part in [('left',labeled.iloc[:len(labeled)//2]),('right',labeled.iloc[len(labeled)//2:])]:
        if part.empty:continue
        part=part.sort_values(['py','entity_group_id'])
        ys=np.linspace(float(-coordinates[:,1].max()),float(-coordinates[:,1].min()),len(part))
        label_x=float(coordinates[:,0].min()-130) if side=='left' else float(coordinates[:,0].max()+130)
        for row,label_y in zip(part.itertuples(index=False),ys):
            ax.annotate(str(row.entity_group_name),(row.px,row.py),xytext=(label_x,label_y),textcoords='data',
                ha='right' if side=='left' else 'left',va='center',fontsize=max(6,tamanho_fonte-3),
                arrowprops={'arrowstyle':'-','color':'#87939a','lw':.5})
    ax.legend(handles=[Line2D([0],[0],marker='o',color='w',markerfacecolor=color,label=label,markersize=8) for label,color,part in groups if len(part)],loc='upper left',fontsize=8,ncol=2 if len(groups)>8 else 1)
    ax.axis('off');ax.margins(.2);fig.tight_layout()
    for ext in ['svg','png','pdf']:fig.savefig(folder/f'{stem}.{ext}',dpi=200,bbox_inches='tight')
    plt.close(fig)


def figuras_editoriais(folder,metrics,profiles,runs):
    import matplotlib.pyplot as plt
    for run in runs:
        chosen=metrics.loc[metrics.run_id.eq(run)].head(10)
        fig,ax=plt.subplots(figsize=(10,6));left=np.zeros(len(chosen))
        for source,color in SOURCE_COLORS.items():
            subset=profiles.loc[profiles.run_id.eq(run)&profiles.scope.eq('internal')&profiles.dimension.eq('source')&profiles.value.eq(source)]
            values=subset.set_index('community_id').news_count.reindex(chosen.community_id,fill_value=0).to_numpy()
            ax.barh(np.arange(len(chosen)),values,left=left,label=source,color=color);left+=values
        ax.set_yticks(np.arange(len(chosen)),['C'+str(int(x)) for x in chosen.community_id]);ax.invert_yaxis()
        ax.set(xlabel='Notícias distintas que sustentam relações internas',title='Suporte editorial das dez maiores comunidades — '+run)
        ax.legend();fig.tight_layout()
        for ext in ['svg','png','pdf']:fig.savefig(folder/f'fontes_comunidades_{run}.{ext}',dpi=200)
        plt.close(fig)


def limpar_saidas_anteriores(base,atual,pacote_atual):
    """Remove somente saídas reconhecidas da etapa, após conferir a nova versão."""
    base=Path(base).resolve();atual=Path(atual).resolve();pacote_atual=Path(pacote_atual).resolve()
    if base.name!='visualizacoes' or base.parent.name!='resultados' or atual.parent!=base or pacote_atual.parent!=base:
        raise ValueError('Escopo de limpeza inválido.')
    current=validate_manifest(atual)
    if current['schema']!='community-evidence-visualization-2':raise ValueError('A limpeza exige a nova representação validada.')
    with zipfile.ZipFile(pacote_atual) as z:
        if json.loads(z.read('manifesto.json'))['snapshot_sha256']!=current['snapshot_sha256'] or z.testzip() is not None:
            raise ValueError('Pacote atual inválido; limpeza cancelada.')
    report={'removed':[],'preserved_unrecognized':[],'errors':[]}
    def directory(folder,schemas):
        if folder.is_symlink() or not re.fullmatch(r'[0-9a-f]{20}',folder.name):return False
        try:
            meta=validate_manifest(folder)
            expected=set(meta['outputs_sha256'])|{'manifesto.json'}
            children=list(folder.iterdir())
            if meta.get('schema') not in schemas or {p.name for p in children}!=expected or any(p.is_symlink() or not p.is_file() for p in children):return False
            shutil.rmtree(folder);report['removed'].append(folder.relative_to(base).as_posix());return True
        except Exception as exc:
            report['errors'].append({'path':folder.relative_to(base).as_posix(),'error_type':type(exc).__name__});return False
    schemas={'community-evidence-visualization-1','community-evidence-visualization-2'}
    for path in list(base.iterdir()):
        if path.resolve() in {atual,pacote_atual} or path.name in {'atual.json','execucao.lock','limpeza_atual.json'}:continue
        if path.is_symlink():report['preserved_unrecognized'].append(path.name);continue
        if path.is_dir() and path.name=='edicoes_figuras':
            for child in list(path.iterdir()):
                if not child.is_dir() or not directory(child,{'static-figure-edition-1'}):report['preserved_unrecognized'].append(child.relative_to(base).as_posix())
            if not list(path.iterdir()):path.rmdir()
        elif path.is_dir():
            if not directory(path,schemas):report['preserved_unrecognized'].append(path.name)
        elif path.is_file() and re.fullmatch(r'Resumo_Visualizacoes_[0-9a-f]{12}_[0-9a-f]{6}\.zip',path.name):
            try:
                with zipfile.ZipFile(path) as z:recognized=json.loads(z.read('manifesto.json')).get('schema') in schemas
                if recognized:path.unlink();report['removed'].append(path.name)
                else:report['preserved_unrecognized'].append(path.name)
            except Exception as exc:report['errors'].append({'path':path.name,'error_type':type(exc).__name__})
        else:report['preserved_unrecognized'].append(path.name)
    report['status']='COMPLETE' if not report['errors'] and not report['preserved_unrecognized'] else 'REVIEW_REMAINING'
    report['current_folder']=atual.name;report['current_package']=pacote_atual.name
    atomic_json(base/'limpeza_atual.json',report)
    print('[VISUALIZAÇÕES] LIMPEZA —',json.dumps(report,ensure_ascii=False))
    return report


def gerar_visualizacoes(projeto,*,executar=False,comunidades_por_particao=3,max_nos=100,max_arestas=250,
                         assinatura_rede_esperada=None,manter_apenas_atual=False):
    root=Path(projeto).resolve();c_folder,c_meta=carregar_comunidades(root);n_folder,n_meta=carregar_rede(root)
    if assinatura_rede_esperada and n_meta['snapshot_sha256']!=assinatura_rede_esperada:raise ValueError('Rede ativa diferente da edição esperada.')
    if any(isinstance(x,bool) or not isinstance(x,int) or x<1 for x in [comunidades_por_particao,max_nos,max_arestas]):raise ValueError('Limites devem ser inteiros positivos.')
    if not isinstance(manter_apenas_atual,bool):raise ValueError('manter_apenas_atual deve ser True ou False.')
    runs=['louvain',c_meta['reference_leiden']]
    if not executar:
        result={'mode':'DRY_RUN','partitions':runs,'nodes':n_meta['summary']['nodes'],'community_views_per_partition':comunidades_por_particao,
                'max_nodes_per_view':max_nos,'max_undirected_pairs_per_view':max_arestas,
                'default_representation':'UNDIRECTED_WEIGHTED','directed_semantic_inspection':True,
                'cleanup_after_success':manter_apenas_atual,'files_deleted':0,'api_calls':0,'neo4j_connections':0}
        print('[VISUALIZAÇÕES]',json.dumps(result,ensure_ascii=False));return result
    try:
        import networkx as nx
        import pyvis
        import matplotlib
    except ImportError:raise RuntimeError('Instale pyvis==0.3.2 e matplotlib no kernel do notebook; NetworkX é dependência do PyVis.') from None
    interface=Path(__file__).with_name('comunidades_interface.js')
    js,css=ativos_vis()
    spec={'schema':'community-evidence-visualization-2','version':VERSION,'network_snapshot_sha256':n_meta['snapshot_sha256'],
          'community_snapshot_sha256':c_meta['snapshot_sha256'],'code_sha256':sha(Path(__file__)),'interface_sha256':sha(interface),
          'partitions':runs,'communities_per_partition':comunidades_por_particao,'max_nodes':max_nos,'max_undirected_pairs':max_arestas,
          'default_representation':'UNDIRECTED_WEIGHTED','semantic_inspection':True,
          'networkx_version':nx.__version__,'pyvis_version':pyvis.__version__,'layout_seed':42,'layout_iterations':200,
          'layout_weight_transform':'log1p','layout_components':'largest centered; remaining placed around it'}
    signature=json_sha(spec);base=root/'resultados/visualizacoes';base.mkdir(parents=True,exist_ok=True);target=base/signature[:20]
    lock=base/'execucao.lock';temp=None
    try:lock.mkdir()
    except FileExistsError:raise RuntimeError('Outra geração de visualizações pode estar ativa. Confira o bloqueio.') from None
    try:
        if target.exists():
            meta=validate_manifest(target)
            if meta['snapshot_sha256']!=signature:raise ValueError('Colisão de assinatura de visualizações.')
        else:
            assignments=pd.read_csv(c_folder/'particoes_nos.csv.gz',keep_default_na=False)
            assignments=assignments.loc[assignments.run_id.isin(runs)].copy()
            stats=pd.read_csv(c_folder/'metricas_comunidades.csv.gz');stats=stats.loc[stats.run_id.isin(runs)].copy()
            edges=pd.read_csv(n_folder/'arestas.csv.gz',keep_default_na=False)
            evidence=pd.read_csv(n_folder/'arestas_noticias.csv.gz',keep_default_na=False)
            node_support=pd.read_csv(n_folder/'nos_noticias.csv.gz',keep_default_na=False)
            node_support=node_support.loc[pd.to_numeric(node_support.relation_participation_count).gt(0)]
            news=pd.read_csv(n_folder/'noticias.csv.gz',keep_default_na=False)
            support=noticias_comunidades(assignments,edges,evidence,news)
            metrics,profiles=caracterizar_suporte(support,stats)
            temp=Path(tempfile.mkdtemp(prefix='.gerando_',dir=base))
            write_csv(temp,'comunidades_noticias.csv.gz',support)
            write_csv(temp,'caracterizacao_comunidades.csv.gz',metrics)
            write_csv(temp,'distribuicoes_editoriais.csv.gz',profiles)
            lookup=noticia_lookup(news);community_lists={};communities=[];catalog=[];view_files={}
            top=assignments.sort_values(['run_id','community_id','pagerank','entity_group_id'],ascending=[True,True,False,True]).groupby(['run_id','community_id']).head(3)
            top_names=top.groupby(['run_id','community_id']).entity_group_name.agg(' · '.join)
            grouped_support={(run,int(cid)):part.sort_values(['publication_date','news_id'])
                             for (run,cid),part in support.groupby(['run_id','community_id'],sort=False)}
            for row in metrics.itertuples(index=False):
                key=row.run_id+':'+str(row.community_id);ordered=grouped_support[(row.run_id,int(row.community_id))]
                community_lists[key]={'any':ordered.news_id.tolist(),'internal':ordered.loc[ordered.internal_support].news_id.tolist()}
                communities.append({'key':key,'run_id':row.run_id,'community_id':int(row.community_id),'nodes':int(row.nodes),
                    'any_news':int(row.any_news),'internal_news':int(row.internal_news),'connected_pieces':int(row.connected_pieces),
                    'top_names':str(top_names.get((row.run_id,row.community_id),'')),'graph_file':''})
            edge_support={str(k):sorted(set(v.news_id)) for k,v in evidence.groupby('edge_id',sort=False)}
            node_links={str(k):sorted(set(v.news_id)) for k,v in node_support.groupby('entity_group_id',sort=False)}
            visible_nodes=[];visible_pairs=[]
            for run in runs:
                nodes=assignments.loc[assignments.run_id.eq(run)].copy()
                colors=paleta_comunidades(metrics.loc[metrics.run_id.eq(run)].community_id)
                chosen_comms=metrics.loc[metrics.run_id.eq(run)].head(comunidades_por_particao).community_id.tolist()
                for cid in [None]+chosen_comms:
                    selected,pairs,semantic_pairs,detail=selecionar_vista(nodes,edges,community_id=cid,max_nodes=max_nos,max_edges=max_arestas)
                    selected['community_color']=selected.community_id.map(colors)
                    color_mode='community' if cid is None else 'type'
                    stem='grafo_'+run+('_global' if cid is None else '_C'+str(cid))
                    title=('Rede global' if cid is None else 'Comunidade C'+str(cid))+' — '+run
                    if cid is None:scope_news=sorted(set(evidence.news_id));pieces_note='Recorte visual da rede inteira.'
                    else:
                        key=run+':'+str(cid);scope_news=community_lists[key]['any'];view_files[key]=stem+'.html'
                        pieces=int(metrics.loc[metrics.run_id.eq(run)&metrics.community_id.eq(cid),'connected_pieces'].iloc[0])
                        pieces_note=f'A comunidade completa possui {pieces} parte(s) conexa(s).'
                    note=(f'{detail["displayed_nodes"]} de {detail["full_nodes"]} entidades; {len(pairs)} pares não dirigidos. '
                          'Comunidades detectadas na projeção não dirigida ponderada; direções originais disponíveis na opção de inspeção semântica. '+pieces_note)
                    selected_node_links={str(int(i)):node_links.get(str(int(i)),[]) for i in selected.entity_group_id}
                    pair_links={r.visual_edge_id:sorted(set().union(*(set(edge_support.get(eid,[])) for eid in r.typed_edge_ids)))
                                for frame in [pairs,semantic_pairs] for r in frame.itertuples(index=False)}
                    positions=layout_vista(selected,pairs)
                    selected['layout_x']=[positions[int(i)][0] for i in selected.entity_group_id]
                    selected['layout_y']=[positions[int(i)][1] for i in selected.entity_group_id]
                    payload=preparar_grafo(selected,pairs,semantic_pairs,positions=positions,node_news=selected_node_links,edge_news=pair_links,
                        news_lookup=lookup,scope_news=scope_news,selection_note=note,default_color_mode=color_mode)
                    (temp/(stem+'.html')).write_text(pagina_html(payload,title=title,note=note,graph=True),encoding='utf-8')
                    figuras_grafo(temp,stem,selected,pairs,positions,title,color_mode=color_mode)
                    selected['view_id']=stem;visible_nodes.append(selected)
                    for representation,frame in [('community',pairs),('semantic',semantic_pairs)]:
                        frame=frame.copy();frame['view_id']=stem;frame['representation']=representation
                        frame['typed_edge_ids']=frame.typed_edge_ids.map(json.dumps);frame['labels']=frame.labels.map(json.dumps);visible_pairs.append(frame)
                    catalog.append({'view_id':stem,'run_id':run,'community_id':'' if cid is None else int(cid),**detail,
                        'html_file':stem+'.html','default_color_mode':color_mode,'objective':'Compreender comunidades na mesma projeção da detecção e consultar evidências originais.',
                        'caption':note+' Layout por molas, semente 42; tamanho por força no recorte; cores por '+('comunidade.' if cid is None else 'tipo de entidade.')})
                    print('[VISUALIZAÇÕES]',stem,detail['displayed_nodes'],'nós;',len(pairs),'pares não dirigidos;',len(semantic_pairs),'direções para inspeção; arquivos salvos.',flush=True)
            for item in communities:item['graph_file']=view_files.get(item['key'],'')
            all_news=set().union(*(set(x['any']) for x in community_lists.values()))
            payload={'mode':'index','partitions':runs,'communities':communities,'communityNews':community_lists,
                     'news':{k:lookup[k] for k in sorted(all_news)}}
            (temp/'indice_comunidades.html').write_text(pagina_html(payload,title='Comunidades e notícias de suporte',
                note='Todas as comunidades das partições de referência. Categorias editoriais não equivalem a temas inferidos. Notícias podem apoiar várias comunidades.'),encoding='utf-8')
            figuras_editoriais(temp,metrics,profiles,runs)
            write_csv(temp,'catalogo_visualizacoes.csv',pd.DataFrame(catalog))
            write_csv(temp,'nos_exibidos.csv.gz',pd.concat(visible_nodes,ignore_index=True))
            write_csv(temp,'pares_exibidos.csv.gz',pd.concat(visible_pairs,ignore_index=True))
            atomic_json(temp/'ambiente.json',{'numpy':np.__version__,'pandas':pd.__version__,'matplotlib':matplotlib.__version__,
                'networkx':nx.__version__,'pyvis':pyvis.__version__,'vis_network':'9.1.2 bundled with PyVis; license retained in inline library'})
            (temp/'LEIA_ME.md').write_text('# Visualizações e suporte editorial\n\nAbra indice_comunidades.html no navegador. '
                'O painel inclui todas as comunidades de Louvain e Leiden de referência. As vistas de grafos são recortes explícitos; '
                'não substituem as métricas da rede completa. Nó e conexão permitem consultar exemplos e a lista completa de notícias.\n\n'
                'A vista principal é não dirigida, somando os pesos das duas direções e dos rótulos, como na projeção de comunidades. '
                'A opção de inspeção semântica recupera as direções originais dos mesmos pares selecionados. '
                'Notícias distintas são contadas pela união dos IDs. Suporte interno e de fronteira podem se sobrepor. '
                'Categorias são editoriais e não rotulam automaticamente comunidades. Não há nova extração, fusão de grupos ou '
                'correção automática de comunidades desconectadas. As cores por comunidade são apenas visuais e os nomes são rótulos.\n',encoding='utf-8')
            summary={'partitions':runs,'community_rows':len(metrics),'support_news':len(all_news),'community_news_links':len(support),
                'graph_views':len(catalog),'html_files':1+len(catalog),'graph_figure_files':3*len(catalog),
                'editorial_figure_files':3*len(runs),'complete_news_lists':True,'external_assets_required':False,
                'default_representation':'UNDIRECTED_WEIGHTED','directed_semantic_inspection':True,
                'api_calls':0,'neo4j_connections':0,'database_writes':0,'partitions_modified':False}
            meta={**spec,'snapshot_sha256':signature,'summary':summary,'created_at_utc':datetime.now(timezone.utc).isoformat(),
                  'outputs_sha256':{p.name:sha(p) for p in sorted(temp.iterdir())}}
            atomic_json(temp/'manifesto.json',meta);validate_manifest(temp)
            if carregar_comunidades(root)[1]['snapshot_sha256']!=c_meta['snapshot_sha256']:raise ValueError('As comunidades ativas mudaram durante a geração.')
            os.rename(temp,target);temp=None
        atomic_json(base/'atual.json',{'folder':target.name,'snapshot_sha256':signature})
        package=base/f'Resumo_Visualizacoes_{signature[:12]}_{uuid.uuid4().hex[:6]}.zip'
        with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
            for path in sorted(target.iterdir()):z.write(path,path.name)
        cleanup=limpar_saidas_anteriores(base,target,package) if manter_apenas_atual else {'status':'NOT_REQUESTED','removed':[]}
        print('[VISUALIZAÇÕES]',json.dumps(meta['summary'],ensure_ascii=False));print('[VISUALIZAÇÕES] Painel:',target/'indice_comunidades.html');print('[VISUALIZAÇÕES] Pacote:',package)
        return {**meta['summary'],'output_directory':target,'index_html':target/'indice_comunidades.html','package':package,'snapshot_sha256':signature,'cleanup':cleanup}
    finally:
        if temp is not None:shutil.rmtree(temp,ignore_errors=True)
        lock.rmdir()


def reexportar_figuras(projeto,*,tamanho_fonte=10,largura=10,altura=8,max_rotulos=15,manter_apenas_atual=False):
    """Atualiza a apresentação estática usando os dados e as posições salvas."""
    if tamanho_fonte<6 or largura<=0 or altura<=0 or max_rotulos<0:
        raise ValueError('Dimensões, fonte ou quantidade de rótulos inválidas.')
    if not isinstance(manter_apenas_atual,bool):raise ValueError('manter_apenas_atual deve ser True ou False.')
    root=Path(projeto).resolve();base=root/'resultados/visualizacoes'
    pointer=json.loads((base/'atual.json').read_text(encoding='utf-8'))
    if Path(pointer['folder']).name!=pointer['folder']:raise ValueError('Apontador de visualizações inválido.')
    source=base/pointer['folder'];meta=validate_manifest(source)
    if pointer['snapshot_sha256']!=meta['snapshot_sha256']:raise ValueError('Versão de visualizações incompatível.')
    style={'tamanho_fonte':tamanho_fonte,'largura':largura,'altura':altura,'max_rotulos':max_rotulos}
    spec={k:v for k,v in meta.items() if k not in ['snapshot_sha256','outputs_sha256','created_at_utc','summary']}
    spec.update({'schema':'community-evidence-visualization-2','code_sha256':sha(Path(__file__)),
                 'static_presentation_style':style,'recomputes_scientific_metrics':False})
    signature=json_sha(spec);target=base/signature[:20];temp=None;lock=base/'execucao.lock'
    try:lock.mkdir()
    except FileExistsError:raise RuntimeError('Outra atualização de visualizações pode estar ativa.') from None
    try:
        if target.exists():validate_manifest(target)
        else:
            temp=Path(tempfile.mkdtemp(prefix='.exportando_',dir=base))
            for name in meta['outputs_sha256']:shutil.copyfile(source/name,temp/name)
            nodes=pd.read_csv(source/'nos_exibidos.csv.gz');pairs=pd.read_csv(source/'pares_exibidos.csv.gz')
            catalog=pd.read_csv(source/'catalogo_visualizacoes.csv',keep_default_na=False)
            for row in catalog.itertuples(index=False):
                selected=nodes.loc[nodes.view_id.eq(row.view_id)]
                visible=pairs.loc[pairs.view_id.eq(row.view_id)]
                if 'representation' in visible:visible=visible.loc[visible.representation.eq('community')]
                positions={int(r.entity_group_id):[float(r.layout_x),float(r.layout_y)] for r in selected.itertuples(index=False)}
                cid=getattr(row,'community_id','');run=getattr(row,'run_id','')
                title=('Rede global' if cid=='' else 'Comunidade C'+str(int(float(cid))))+' — '+run
                figuras_grafo(temp,row.view_id,selected,visible,positions,title,color_mode=getattr(row,'default_color_mode','community'),**style)
            metrics=pd.read_csv(source/'caracterizacao_comunidades.csv.gz');profiles=pd.read_csv(source/'distribuicoes_editoriais.csv.gz',dtype={'value':str})
            figuras_editoriais(temp,metrics,profiles,meta['partitions'])
            atomic_json(temp/'manifesto.json',{**spec,'snapshot_sha256':signature,'summary':meta.get('summary',{}),
                        'created_at_utc':datetime.now(timezone.utc).isoformat(),
                        'outputs_sha256':{p.name:sha(p) for p in sorted(temp.iterdir())}})
            validate_manifest(temp);os.rename(temp,target);temp=None
        atomic_json(base/'atual.json',{'folder':target.name,'snapshot_sha256':signature})
        package=base/f'Resumo_Visualizacoes_{signature[:12]}_{uuid.uuid4().hex[:6]}.zip'
        with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
            for path in sorted(target.iterdir()):z.write(path,path.name)
        cleanup=limpar_saidas_anteriores(base,target,package) if manter_apenas_atual else {'status':'NOT_REQUESTED','removed':[]}
    finally:
        if temp is not None:shutil.rmtree(temp,ignore_errors=True)
        lock.rmdir()
    print('[FIGURAS] Apresentação atualizada:',target,'; métricas científicas recalculadas: 0.')
    return {'output_directory':target,'package':package,'scientific_recomputations':0,
            'source_snapshot_sha256':meta['snapshot_sha256'],'cleanup':cleanup}
