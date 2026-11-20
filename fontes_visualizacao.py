"""Painéis de comunidades por fonte e inspeção de conectividade com evidências."""
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
import html
import json
import shutil
import tempfile
import uuid
import zipfile
import pandas as pd
from fontes_estrutural import carregar_fontes
from redes_fontes import FONTES
import comunidades_visualizacao as vis
from re_consolidacao import sha, json_sha, write_csv, validate_manifest
from re_execucao import atomic_json

VERSION='1.0.0'


def carregar_particoes(root,meta):
    base=root/'resultados/comparacao_fontes/comunidades'
    pointer=json.loads((base/'atual.json').read_text(encoding='utf-8'))
    folder=(base/pointer['folder']).resolve()
    if base.resolve() not in folder.parents:raise ValueError('Apontador de comunidades inválido.')
    cm=validate_manifest(folder)
    if cm['schema']!='source-weighted-communities-1' or cm['snapshot_sha256']!=pointer['snapshot_sha256']:
        raise ValueError('Edição de comunidades incompatível.')
    if cm['source_networks_snapshot_sha256']!=meta['snapshot_sha256']:
        raise ValueError('Partições e redes por fonte pertencem a edições diferentes.')
    return folder,cm


def selecionar_comunidades(metrics,run,limite):
    grupo=metrics.loc[metrics.run_id.eq(run)]
    maiores=grupo.sort_values(['nodes','community_id'],ascending=[False,True]).head(limite).community_id.tolist()
    sinalizadas=grupo.loc[grupo.connected_pieces.gt(1)].community_id.tolist()
    return list(dict.fromkeys(map(int,maiores+sinalizadas)))


def inspecionar_partes(assignments,stats,pairs):
    """Busca independente no subgrafo induzido de cada comunidade sinalizada."""
    adj=defaultdict(set)
    for a,b in zip(pairs.source_id,pairs.target_id):adj[int(a)].add(int(b));adj[int(b)].add(int(a))
    members=[];resumos=[]
    for row in stats.loc[stats.connected_pieces.gt(1)].itertuples(index=False):
        part=assignments.loc[assignments.run_id.eq(row.run_id)&assignments.community_id.eq(row.community_id)]
        ids=set(map(int,part.entity_group_id));unseen=set(ids);pieces=[]
        while unseen:
            start=min(unseen);unseen.remove(start);stack=[start];piece=[]
            while stack:
                a=stack.pop();piece.append(a)
                for b in adj[a]:
                    if b in unseen:unseen.remove(b);stack.append(b)
            pieces.append(sorted(piece))
        if len(pieces)!=int(row.connected_pieces):raise ValueError('Conectividade diverge da detecção.')
        for piece in pieces:
            for gid in piece:members.append({'run_id':row.run_id,'community_id':int(row.community_id),
                'entity_group_id':gid,'piece_id':min(piece),'piece_nodes':len(piece)})
        resumos.append({'run_id':row.run_id,'community_id':int(row.community_id),'nodes':len(ids),
            'connected_pieces':len(pieces),'piece_sizes':json.dumps(sorted(map(len,pieces),reverse=True))})
    m=pd.DataFrame(members,columns=['run_id','community_id','entity_group_id','piece_id','piece_nodes'])
    if not m.empty:m=m.merge(assignments[['run_id','entity_group_id','entity_group_name','ent_label']],on=['run_id','entity_group_id'],validate='one_to_one')
    return m,pd.DataFrame(resumos,columns=['run_id','community_id','nodes','connected_pieces','piece_sizes'])


def pagina(payload,title,note,index_file,graph=False):
    page=vis.pagina_html(payload,title=title,note=note,graph=graph)
    page=page.replace('href="indice_comunidades.html"','href="'+index_file+'"',1)
    return page.replace('<th>Destaques por PageRank global</th>','<th>Destaques por PageRank da fonte</th>')


def gerar_visualizacoes_fontes(projeto,*,executar=False,comunidades_por_particao=2,max_nos=100,
                               max_arestas=250,max_nos_inspecao=200,
                               assinatura_rede_esperada=None,assinatura_fontes_esperada=None):
    root=Path(projeto).resolve();origem,meta=carregar_fontes(root,assinatura_rede_esperada)
    if assinatura_fontes_esperada and meta['snapshot_sha256']!=assinatura_fontes_esperada:
        raise ValueError('Redes por fonte diferentes da edição esperada.')
    comunidades,cm=carregar_particoes(root,meta);runs=['louvain',cm['reference_leiden']]
    if any(isinstance(x,bool) or not isinstance(x,int) or x<1 for x in [comunidades_por_particao,max_nos,max_arestas,max_nos_inspecao]):
        raise ValueError('Limites devem ser inteiros positivos.')
    if not executar:
        return {'mode':'DRY_RUN','sources':list(FONTES.values()),'partitions':runs,
            'community_views_per_partition':comunidades_por_particao,'include_all_flagged_communities':True,
            'max_nodes_regular_view':max_nos,'max_nodes_flagged_view':max_nos_inspecao,
            'max_undirected_pairs':max_arestas,'default_representation':'UNDIRECTED_WEIGHTED',
            'complete_news_lists':True,'files_written':0,'api_calls':0,'neo4j_connections':0}
    import networkx as nx
    import pyvis
    interface=Path(vis.__file__).with_name('comunidades_interface.js')
    vis.ativos_vis()
    spec={'schema':'source-community-evidence-visualization-1','version':VERSION,'code_sha256':sha(Path(__file__)),
        'visualization_code_sha256':sha(Path(vis.__file__)),'interface_sha256':sha(interface),
        'source_networks_snapshot_sha256':meta['snapshot_sha256'],'community_snapshot_sha256':cm['snapshot_sha256'],
        'network_snapshot_sha256':meta['network_snapshot_sha256'],'partitions':runs,
        'communities_per_partition':comunidades_por_particao,'max_nodes_regular':max_nos,
        'max_nodes_flagged':max_nos_inspecao,'max_undirected_pairs':max_arestas,
        'networkx_version':nx.__version__,'pyvis_version':pyvis.__version__,'layout_seed':42}
    assinatura=json_sha(spec);base=root/'resultados/comparacao_fontes/visualizacoes';base.mkdir(parents=True,exist_ok=True)
    destino=base/assinatura[:20];lock=base/'execucao.lock';temp=None
    try:lock.mkdir()
    except FileExistsError:raise RuntimeError('Geração de visualizações pode estar ativa; confira o bloqueio.') from None
    try:
        if destino.exists():
            salvo=validate_manifest(destino)
            if salvo['snapshot_sha256']!=assinatura:raise ValueError('Assinatura de saída incompatível.')
            resumo=salvo['summary']
        else:
            temp=Path(tempfile.mkdtemp(prefix='.visualizacoes_',dir=base));summaries=[];catalog=[];visible_nodes=[];visible_pairs=[];diagnostics=[]
            for slug,fonte in FONTES.items():
                def ler(folder,nome):return pd.read_csv(folder/(slug+'_'+nome),keep_default_na=False)
                assignments=ler(comunidades,'particoes_nos.csv.gz');assignments=assignments.loc[assignments.run_id.isin(runs)].copy()
                stats=ler(comunidades,'metricas_comunidades.csv.gz');stats=stats.loc[stats.run_id.isin(runs)].copy()
                edges,evidence,nn,news=[ler(origem,n) for n in ['arestas.csv.gz','arestas_noticias.csv.gz','nos_noticias.csv.gz','noticias.csv.gz']]
                nn=nn.loc[pd.to_numeric(nn.relation_participation_count).gt(0)]
                support=vis.noticias_comunidades(assignments,edges,evidence,news)
                metrics,profiles=vis.caracterizar_suporte(support,stats)
                pieces,diag=inspecionar_partes(assignments,stats,ler(origem,'simples_nao_dirigida.csv.gz'))
                for name,frame in [('comunidades_noticias.csv.gz',support),('caracterizacao_comunidades.csv.gz',metrics),
                    ('distribuicoes_editoriais.csv.gz',profiles),('partes_conexas_entidades.csv.gz',pieces)]:write_csv(temp,slug+'_'+name,frame)
                diag.insert(0,'source_key',slug);diag.insert(1,'source',fonte);diagnostics.append(diag)
                lookup=vis.noticia_lookup(news);community_lists={};items=[];view_files={};index_file=slug+'_indice_comunidades.html';source_views=0
                top=assignments.sort_values(['run_id','community_id','pagerank','entity_group_id'],ascending=[True,True,False,True]).groupby(['run_id','community_id']).head(3)
                top_names=top.groupby(['run_id','community_id']).entity_group_name.agg(' · '.join)
                grouped={(run,int(cid)):p.sort_values(['publication_date','news_id']) for (run,cid),p in support.groupby(['run_id','community_id'],sort=False)}
                for row in metrics.itertuples(index=False):
                    key=row.run_id+':'+str(row.community_id);ordered=grouped[(row.run_id,int(row.community_id))]
                    community_lists[key]={'any':ordered.news_id.tolist(),'internal':ordered.loc[ordered.internal_support].news_id.tolist()}
                    items.append({'key':key,'run_id':row.run_id,'community_id':int(row.community_id),'nodes':int(row.nodes),
                        'any_news':int(row.any_news),'internal_news':int(row.internal_news),'connected_pieces':int(row.connected_pieces),
                        'top_names':str(top_names.get((row.run_id,row.community_id),'')),'graph_file':''})
                edge_support={str(k):set(p.news_id) for k,p in evidence.groupby('edge_id',sort=False)}
                node_links={str(k):sorted(set(p.news_id)) for k,p in nn.groupby('entity_group_id',sort=False)}
                for run in runs:
                    nodes=assignments.loc[assignments.run_id.eq(run)].copy()
                    colors=vis.paleta_comunidades(metrics.loc[metrics.run_id.eq(run)].community_id)
                    for cid in [None]+selecionar_comunidades(metrics,run,comunidades_por_particao):
                        stat=None if cid is None else metrics.loc[metrics.run_id.eq(run)&metrics.community_id.eq(cid)].iloc[0]
                        flagged=stat is not None and int(stat.connected_pieces)>1
                        limit=max_nos_inspecao if flagged else max_nos
                        selected,pairs,semantic,detail=vis.selecionar_vista(nodes,edges,community_id=cid,max_nodes=limit,max_edges=max_arestas)
                        selected['community_color']=selected.community_id.map(colors);color_mode='community' if cid is None else 'type'
                        stem=slug+'_grafo_'+run+('_rede' if cid is None else '_C'+str(cid))
                        title=fonte+' — '+('rede da fonte' if cid is None else 'comunidade C'+str(cid))+' — '+run
                        if cid is None:scope_news=sorted(set(evidence.news_id));piece_note='Recorte visual da rede completa da fonte.'
                        else:
                            key=run+':'+str(cid);scope_news=community_lists[key]['any'];view_files[key]=stem+'.html'
                            piece_note='A comunidade completa possui '+str(int(stat.connected_pieces))+' parte(s) conexa(s).'
                        note=(str(detail['displayed_nodes'])+' de '+str(detail['full_nodes'])+' entidades; '+str(len(pairs))+' pares exibidos. '
                            'Vista principal não dirigida ponderada; inspeção dirigida opcional. '+piece_note+
                            ' Limites visuais podem omitir entidades ou conexões; conectividade reportada usa o subgrafo completo.')
                        nl={str(int(i)):node_links.get(str(int(i)),[]) for i in selected.entity_group_id}
                        el={r.visual_edge_id:sorted(set().union(*(edge_support.get(eid,set()) for eid in r.typed_edge_ids)))
                            for frame in [pairs,semantic] for r in frame.itertuples(index=False)}
                        positions=vis.layout_vista(selected,pairs)
                        selected['layout_x']=[positions[int(i)][0] for i in selected.entity_group_id]
                        selected['layout_y']=[positions[int(i)][1] for i in selected.entity_group_id]
                        payload=vis.preparar_grafo(selected,pairs,semantic,positions=positions,node_news=nl,edge_news=el,
                            news_lookup=lookup,scope_news=scope_news,selection_note=note,default_color_mode=color_mode)
                        (temp/(stem+'.html')).write_text(pagina(payload,title,note,index_file,True),encoding='utf-8')
                        vis.figuras_grafo(temp,stem,selected,pairs,positions,title,color_mode=color_mode)
                        selected['view_id']=stem;visible_nodes.append(selected)
                        for representation,frame in [('community',pairs),('semantic',semantic)]:
                            frame=frame.copy();frame['view_id']=stem;frame['representation']=representation
                            frame['typed_edge_ids']=frame.typed_edge_ids.map(json.dumps);frame['labels']=frame.labels.map(json.dumps);visible_pairs.append(frame)
                        catalog.append({'source_key':slug,'view_id':stem,'run_id':run,'community_id':'' if cid is None else int(cid),
                            'flagged_disconnected':bool(flagged),'complete_community_nodes':bool(cid is not None and detail['displayed_nodes']==detail['full_nodes']),
                            **detail,'html_file':stem+'.html','default_color_mode':color_mode,'caption':note})
                        source_views+=1;print('[VISTAS FONTES]',stem,'—',len(selected),'nós;',len(pairs),'pares.',flush=True)
                for item in items:item['graph_file']=view_files.get(item['key'],'')
                all_news=set().union(*(set(x['any']) for x in community_lists.values()))
                payload={'mode':'index','partitions':runs,'communities':items,'communityNews':community_lists,'news':{k:lookup[k] for k in sorted(all_news)}}
                (temp/index_file).write_text(pagina(payload,fonte+' — comunidades e notícias',
                    'Todas as comunidades das duas partições de referência. Categorias são editoriais; não determinam temas automaticamente.',index_file),encoding='utf-8')
                summaries.append({'source_key':slug,'source':fonte,'community_rows':len(metrics),'support_news':len(all_news),
                    'community_news_links':len(support),'graph_views':source_views,'flagged_communities':len(diag),'index_html':index_file})
            diagnostic=pd.concat(diagnostics,ignore_index=True);write_csv(temp,'diagnostico_conectividade.csv',diagnostic)
            write_csv(temp,'catalogo_visualizacoes.csv',pd.DataFrame(catalog));write_csv(temp,'nos_exibidos.csv.gz',pd.concat(visible_nodes,ignore_index=True))
            write_csv(temp,'pares_exibidos.csv.gz',pd.concat(visible_pairs,ignore_index=True))
            cards=''.join('<li><a href="'+s['index_html']+'">'+html.escape(s['source'])+'</a>: '+str(s['community_rows'])+' comunidades nas duas partições.</li>' for s in summaries)
            rows=''
            for d in diagnostic.itertuples():
                stem=d.source_key+'_grafo_'+d.run_id+'_C'+str(d.community_id)+'.html'
                rows+='<tr><td>'+html.escape(d.source)+'</td><td>'+html.escape(d.run_id)+'</td><td><a href="'+stem+'">C'+str(d.community_id)+'</a></td><td>'+str(d.nodes)+'</td><td>'+str(d.connected_pieces)+'</td><td>'+html.escape(d.piece_sizes)+'</td></tr>'
            (temp/'indice_comunidades_fontes.html').write_text('<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Comunidades por fonte</title><style>'+vis.CSS+'</style><main class="main"><h1>Comunidades por fonte — 2025</h1><ul>'+cards+'</ul><h2>Inspeção de comunidades desconectadas</h2><p>Partições preservadas. Partes calculadas no subgrafo completo, sem limitar nós ou arestas. IDs não estabelecem equivalência entre fontes.</p><table><tr><th>Fonte</th><th>Partição</th><th>Comunidade</th><th>Nós</th><th>Partes</th><th>Tamanhos das partes</th></tr>'+rows+'</table><p><a href="diagnostico_conectividade.csv">Tabela completa de diagnóstico</a></p><p>Use os painéis por fonte para consultar exemplos, listas completas e exportação de notícias. Os desenhos são recortes explícitos e não alteram as comunidades.</p></main></html>',encoding='utf-8')
            resumo={'sources':summaries,'partitions':runs,'graph_views':len(catalog),'html_files':len(catalog)+4,
                'graph_figure_files':3*len(catalog),'flagged_communities':len(diagnostic),'complete_news_lists':True,
                'external_assets_required':False,'api_calls':0,'neo4j_connections':0,'database_writes':0,'partitions_modified':False}
            (temp/'LEIA_ME.md').write_text('# Comunidades por fonte e evidências\n\nAbra indice_comunidades_fontes.html. '
                'Os painéis contêm todas as comunidades de Louvain e Leiden de referência. As vistas incluem a rede '
                'da fonte, as maiores comunidades e todas as comunidades desconectadas dessas duas partições. '
                'Cores por comunidade são locais à partição e à fonte; IDs ou cores iguais não garantem equivalência.\n\n'
                'Os desenhos usam limites de nós e arestas. A conectividade diagnosticada considera todos os membros '
                'e todas as conexões da comunidade. As listas de notícias e partes conexas permanecem completas, '
                'independentemente do desenho. Categorias editoriais não são temas inferidos. Nenhuma partição é '
                'corrigida, fundida ou dividida automaticamente. As posições visuais são persistidas para ajustes futuros.\n',encoding='utf-8')
            atomic_json(temp/'manifesto.json',{**spec,'snapshot_sha256':assinatura,'summary':resumo,
                'created_at_utc':datetime.now(timezone.utc).isoformat(),
                'outputs_sha256':{p.name:sha(p) for p in sorted(temp.iterdir())}})
            validate_manifest(temp);temp.rename(destino);temp=None
        atomic_json(base/'atual.json',{'folder':destino.name,'snapshot_sha256':assinatura})
        pacote=base/('Resumo_Visualizacoes_Fontes_'+assinatura[:12]+'_'+uuid.uuid4().hex[:6]+'.zip')
        with zipfile.ZipFile(pacote,'w',zipfile.ZIP_DEFLATED) as z:
            for p in sorted(destino.iterdir()):z.write(p,p.name)
        print('[VISTAS FONTES] Painel:',destino/'indice_comunidades_fontes.html');print('[VISTAS FONTES] Pacote:',pacote)
        return {**resumo,'output_directory':destino,'index_html':destino/'indice_comunidades_fontes.html','package':pacote,'snapshot_sha256':assinatura}
    finally:
        if temp is not None and temp.exists():shutil.rmtree(temp)
        lock.rmdir()
