"""Revisão local das pendências 1, 3 e 5; sem API, Neo4j ou alteração das partições."""
from pathlib import Path
from datetime import datetime, timezone
from collections import deque
import hashlib, json, math, os, re, shutil, tempfile, zipfile
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.special import log_ndtr, zeta

VERSION='1.0.0'
SCHEMA='mo438-revisao-pendencias-1'
COLORS={'PESSOA':'#4C78A8','ORGANIZACAO':'#F58518','LOCAL':'#54A24B'}

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def write_json(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def csv(path,frame):
    frame.to_csv(path,index=False,encoding='utf-8-sig',compression='gzip' if str(path).endswith('.gz') else None)

def load(root,relative,receipts):
    base=root/relative;p=json.loads((base/'atual.json').read_text(encoding='utf-8'))
    folder=base/p['folder']
    if not folder.resolve().is_relative_to(base.resolve()):raise ValueError('Ponteiro fora da etapa.')
    m=json.loads((folder/'manifesto.json').read_text(encoding='utf-8'))
    if p['snapshot_sha256']!=m['snapshot_sha256']:raise ValueError('Assinatura de ponteiro incompatível.')
    receipts[relative]={'folder':str(folder.relative_to(root)),'snapshot_sha256':m['snapshot_sha256']}
    return folder,m

def read(folder,manifest,name,checks):
    expected=manifest.get('outputs_sha256',{}).get(name)
    if expected is None or sha(folder/name)!=expected:raise ValueError('Arquivo sem hash válido: '+name)
    checks[str(folder/name)]=expected
    return pd.read_csv(folder/name,keep_default_na=False)

def connectivity(frame,pairs):
    """Componentes via matriz esparsa, independente do union-find do pipeline."""
    f=frame.sort_values('entity_group_id').reset_index(drop=True).copy()
    if not f.entity_group_id.is_unique:raise ValueError('Entidade duplicada na partição.')
    if (pairs.weight<=0).any() or pairs[['source_id','target_id']].duplicated().any() or (pairs.source_id>=pairs.target_id).any():
        raise ValueError('Projeção deve conter pares únicos, ordenados, com pesos positivos.')
    index=pd.Index(f.entity_group_id);a=index.get_indexer(pairs.source_id);b=index.get_indexer(pairs.target_id)
    if (a<0).any() or (b<0).any():raise ValueError('Projeção e partição têm universos diferentes.')
    c=f.community_id.to_numpy();inside=c[a]==c[b]
    sparse=coo_matrix((np.ones(int(inside.sum())),(a[inside],b[inside])),shape=(len(f),len(f))).tocsr()
    _,part=connected_components(sparse,directed=False)
    f['independent_piece_id']=pd.Series(f.entity_group_id).groupby(part).transform('min').to_numpy()
    # Recompute modularity, counting every undirected pair once.
    w=pairs.weight.to_numpy(float);W=w.sum();node_strength=np.bincount(a,weights=w,minlength=len(f))+np.bincount(b,weights=w,minlength=len(f))
    strength=pd.Series(node_strength).groupby(c).sum();internal=pd.Series(w[inside]).groupby(c[a[inside]]).sum()
    q=float(internal.sum()/W-np.square(strength/(2*W)).sum())
    counts=f.groupby('community_id').independent_piece_id.nunique();bad=counts[counts>1]
    summary={'nodes':len(f),'communities':int(counts.size),'disconnected_communities':len(bad),'weighted_modularity_independent':q}
    return f,summary

def bfs_parts(ids,pairs):
    """Second, independent connectivity reference used for affected groups only."""
    ids=set(map(int,ids));adj={i:[] for i in ids}
    for a,b in zip(pairs.source_id,pairs.target_id):
        if int(a) in ids and int(b) in ids:adj[int(a)].append(int(b));adj[int(b)].append(int(a))
    result={};remaining=set(ids)
    while remaining:
        start=min(remaining);todo=deque([start]);remaining.remove(start);piece=[]
        while todo:
            a=todo.popleft();piece.append(a)
            for b in adj[a]:
                if b in remaining:remaining.remove(b);todo.append(b)
        for a in piece:result[a]=min(piece)
    return result

def lognormal_logpmf(x,mu,sigma,xmin):
    """Stable rounded lognormal, same unbounded round convention as powerlaw 1.5."""
    x=np.asarray(x,dtype=float)
    if sigma<=0 or xmin<1 or np.any(x<xmin):raise ValueError('Parâmetros ou graus inválidos.')
    left=log_ndtr(-(np.log(x-.5)-mu)/sigma)
    right=log_ndtr(-(np.log(x+.5)-mu)/sigma)
    norm=log_ndtr(-(np.log(xmin-.5)-mu)/sigma)
    result=left+np.log(-np.expm1(right-left))-norm
    if not np.isfinite(result).all():raise ValueError('Log-verossimilhança não finita.')
    return result

def review_2012(folder,m,output,checks):
    comparisons=read(folder,m,'comparacao_modelos.csv',checks)
    fits=read(folder,m,'ajustes_cauda.csv',checks)
    distribution=read(folder,m,'distribuicoes_graus.csv',checks)
    row=comparisons[(comparisons.cutoff_year==2012)&(comparisons.alternative=='lognormal')].iloc[0]
    fit=fits[fits.cutoff_year==2012].iloc[0];params=json.loads(row.parameters);xmin=float(fit.xmin)
    tail=distribution[(distribution.cutoff_year==2012)&(distribution.degree>=xmin)].copy()
    x=tail.degree.to_numpy(float);n=tail.nodes.to_numpy(int)
    lp=lognormal_logpmf(x,params['mu'],params['sigma'],xmin)
    power=-float(fit.alpha)*np.log(x)-np.log(zeta(float(fit.alpha),xmin))
    ratio=float(np.dot(n,power-lp));difference=abs(ratio-float(row.log_likelihood_ratio))
    if difference>1e-6:raise ValueError('Razão arquivada não reproduzida pelo cálculo estável.')
    tail['logpmf_lognormal_stable']=lp;tail['logpmf_powerlaw']=power
    csv(output/'lognormal_2012_por_grau.csv',tail)
    result={'year':2012,'xmin':xmin,'tail_nodes':int(n.sum()),'mu_saved':params['mu'],'sigma_saved':params['sigma'],
        'saved_status':row.status,'saved_warning':row.warnings,'saved_R':float(row.log_likelihood_ratio),
        'stable_R_same_parameters':ratio,'absolute_difference_R':difference,
        'saved_p_iid_diagnostic':float(row.p_iid_diagnostic),'all_final_log_probabilities_finite':True,
        'parameters_reestimated':False,'old_output_modified':False,
        'verdict':'FINAL_POINT_REPRODUCED_PARAMETER_STABILITY_NOT_ESTABLISHED',
        'interpretation':'O valor final foi reproduzido de forma estável; isso não demonstra um máximo estável ou parâmetros identificáveis. Sem preferência conclusiva entre os modelos; alerta original preservado.'}
    write_json(output/'lognormal_2012_revisao.json',result);return result

def layout(nodes,pairs,community=False):
    """Deterministic presentation only; spatial distance has no analytical meaning."""
    ids=nodes.entity_group_id.to_numpy(int);positions={}
    if community:
        groups=sorted(nodes.groupby('community_id'),key=lambda v:(-len(v[1]),int(v[0])))
        count=len(groups);cols=max(1,int(math.ceil(math.sqrt(count))))
        for i,(cid,g) in enumerate(groups):
            ordered=sorted(map(int,g.entity_group_id));scale=.25+.65*math.sqrt(len(g)/max(1,len(groups[0][1])))
            for j,gid in enumerate(ordered):
                angle=j*math.pi*(3-math.sqrt(5));radius=scale*math.sqrt((j+.5)/len(g))
                positions[gid]=(2*(i%cols)+radius*math.cos(angle),2*(i//cols)+radius*math.sin(angle))
        return positions
    rng=np.random.default_rng(42);xy=rng.normal(size=(len(ids),2));index={v:i for i,v in enumerate(ids)}
    a=np.array([index[int(v)] for v in pairs.source_id]);b=np.array([index[int(v)] for v in pairs.target_id])
    for step in range(250):
        diff=xy[:,None,:]-xy[None,:,:];dist=np.maximum(np.linalg.norm(diff,axis=2),.03)
        force=(diff/(dist[:,:,None]**2)).sum(axis=1)*.035
        edge=xy[b]-xy[a];length=np.maximum(np.linalg.norm(edge,axis=1),.03)
        spring=edge*(length[:,None]-.8)*.015
        np.add.at(force,a,spring);np.add.at(force,b,-spring)
        force-=xy*.01;norm=np.maximum(np.linalg.norm(force,axis=1),.01)
        xy+=force/norm[:,None]*np.minimum(norm,.10*(1-step/260))[:,None]
    return dict(zip(map(int,ids),map(tuple,xy)))

def graphml(path,nodes,pairs):
    ns='http://graphml.graphdrawing.org/xmlns';ET.register_namespace('',ns)
    root=ET.Element('{'+ns+'}graphml')
    for k,t in [('name','string'),('entity_type','string'),('degree','int'),('strength','double'),('community','string'),('weight','double')]:
        ET.SubElement(root,'{'+ns+'}key',id=k,**{'for':'edge' if k=='weight' else 'node','attr.name':k,'attr.type':t})
    graph=ET.SubElement(root,'{'+ns+'}graph',id='G',edgedefault='undirected')
    for r in nodes.itertuples(index=False):
        el=ET.SubElement(graph,'{'+ns+'}node',id=str(r.entity_group_id))
        for k,v in [('name',r.entity_group_name),('entity_type',r.ent_label),('degree',r.neighbor_degree),('strength',r.weighted_strength),('community',getattr(r,'community_id',''))]:ET.SubElement(el,'{'+ns+'}data',key=k).text=str(v)
    for i,r in enumerate(pairs.itertuples(index=False)):
        el=ET.SubElement(graph,'{'+ns+'}edge',id=str(i),source=str(r.source_id),target=str(r.target_id));ET.SubElement(el,'{'+ns+'}data',key='weight').text=str(r.weight)
    ET.ElementTree(root).write(path,encoding='utf-8',xml_declaration=True)

def figures(output,allnodes,pairs,partitions):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from matplotlib.colors import to_hex
    plt.rcParams.update({'svg.fonttype':'none','pdf.fonttype':42})
    byid=allnodes.set_index('entity_group_id')
    contributions=pd.concat([pairs[['source_id','weight']].rename(columns={'source_id':'entity_group_id'}),pairs[['target_id','weight']].rename(columns={'target_id':'entity_group_id'})])
    expected_strength=contributions.groupby('entity_group_id').weight.sum().reindex(byid.index,fill_value=0)
    expected_degree=contributions.groupby('entity_group_id').size().reindex(byid.index,fill_value=0)
    if not np.array_equal(expected_strength.to_numpy(),byid.weighted_strength.to_numpy()) or not np.array_equal(expected_degree.to_numpy(),byid.neighbor_degree.to_numpy()):
        raise ValueError('Grau ou força global difere da projeção de pares.')
    ranked=allnodes.sort_values(['weighted_strength','entity_group_id'],ascending=[False,True])
    top=ranked.head(50).copy();chosen=set(top.entity_group_id)
    top_pairs=pairs[pairs.source_id.isin(chosen)&pairs.target_id.isin(chosen)].copy()
    threshold=float(top.weighted_strength.iloc[-1]);ties=ranked[ranked.weighted_strength==threshold]
    csv(output/'top50_forca_nos.csv',top);csv(output/'top50_forca_pares.csv',top_pairs)
    topview={'view':'top50_forca','nodes':50,'pairs':len(top_pairs),'scope':'GLOBAL','edge_pruning':False,
             'criterion':'weighted_strength desc; entity_group_id asc','boundary_strength':threshold,
             'boundary_ties_total':len(ties),'boundary_ties_selected':int(top.weighted_strength.eq(threshold).sum())}
    views=[(topview,top,top_pairs,False)]
    for run in ['louvain','leiden_seed_42']:
        part=partitions[partitions.run_id==run].copy();counts=part.groupby('component_id').size();gcc=counts[counts==counts.max()].index.min()
        n=part[part.component_id==gcc].copy();chosen=set(n.entity_group_id);e=pairs[pairs.source_id.isin(chosen)&pairs.target_id.isin(chosen)].copy()
        views.append(({'view':'gcc_'+run,'nodes':len(n),'pairs':len(e),'scope':'GCC','partition':run,
                      'edge_pruning':False,'community_detection_rerun':False},n,e,True))
    catalog=[]
    for info,n,e,community in views:
        pos=layout(n,e,community=community);name=info['view'];graphml(output/(name+'.graphml'),n,e)
        csv(output/(name+'_posicoes.csv'),pd.DataFrame([{'entity_group_id':k,'x':v[0],'y':v[1]} for k,v in pos.items()]))
        fig,ax=plt.subplots(figsize=(12,10));segments=[[pos[int(a)],pos[int(b)]] for a,b in zip(e.source_id,e.target_id)]
        ax.add_collection(LineCollection(segments,linewidths=.14 if community else .35,colors='#607581',alpha=.17 if community else .45))
        xy=np.array([pos[int(gid)] for gid in n.entity_group_id])
        if community:
            cs=sorted(n.community_id.unique());palette={c:to_hex(plt.cm.hsv((i*.61803398875)%1)) for i,c in enumerate(cs)}
            colors=n.community_id.map(palette);sizes=np.clip(1.2+np.log1p(n.neighbor_degree),1.5,8)
        else:colors=n.ent_label.map(COLORS);sizes=10+8*np.log1p(n.neighbor_degree)
        ax.scatter(xy[:,0],xy[:,1],s=sizes,c=list(colors),edgecolors='white' if not community else 'none',linewidths=.25,zorder=3)
        if community:
            # Label communities rather than overlapping entity names in the full GCC.
            largest=n.groupby('community_id').size().sort_values(ascending=False).head(8)
            for cid,count in largest.items():
                coords=np.array([pos[int(gid)] for gid in n.loc[n.community_id==cid,'entity_group_id']]);center=coords.mean(axis=0)
                ax.annotate('C'+str(cid),center,xytext=(0,-13),ha='center',textcoords='offset points',fontsize=7,color='#172b3a')
        else:
            from matplotlib.lines import Line2D
            from matplotlib.text import Text
            ax.legend(handles=[Line2D([],[],marker='o',linestyle='',color=c,label=t) for t,c in COLORS.items()],loc='upper left',frameon=False,fontsize=8)
            annotations=[]
            for row in n.itertuples(index=False):
                label=str(row.entity_group_name);label=label if len(label)<=40 else label[:37]+'…'
                annotations.append(ax.annotate(label,pos[int(row.entity_group_id)],xytext=(4,3),textcoords='offset points',fontsize=7,color='#172b3a',arrowprops={'arrowstyle':'-','lw':.3,'color':'#aaa'}))
            # Deterministic label spacing in display coordinates; no graph data changes.
            for iteration in range(18):
                fig.canvas.draw();renderer=fig.canvas.get_renderer();moved=False
                for i in range(len(annotations)):
                    for j in range(i):
                        first=annotations[i];second=annotations[j]
                        if Text.get_window_extent(first,renderer).overlaps(Text.get_window_extent(second,renderer)):
                            x,y=first.get_position();first.set_position((x,y+3));moved=True
                if not moved:break
        title='50 entidades por força global — subgrafo induzido completo' if not community else 'Comunidades na GCC completa — '+info['partition']
        ax.set_title(title+'\n'+f'{len(n):,} entidades · {len(e):,} pares'.replace(',','.'),fontsize=13)
        ax.autoscale_view();ax.margins(.12);ax.axis('off')
        fig.text(.02,.018,'Cores: '+('comunidades da partição original. Layout por grupos; distância não é semântica.' if community else 'tipos de entidade. Tamanho: grau global em escala logarítmica; seleção: força global.')+'\nTodos os pares induzidos foram mantidos. Nomes completos e IDs estão nas tabelas e no GraphML.',fontsize=8)
        fig.subplots_adjust(bottom=.09)
        for ext in ['svg','png','pdf']:fig.savefig(output/(name+'.'+ext),dpi=200)
        plt.close(fig);catalog.append(info)
    csv(output/'catalogo_visualizacoes.csv',pd.DataFrame(catalog));return catalog

def executar_revisao(projeto,*,executar=False):
    root=Path(projeto).resolve()
    if root.name=='PROJECT_EXTRACAO':raise ValueError('Use PROJECT, não a pasta de extração.')
    receipts={};checks={}
    comm,cm=load(root,'resultados/comunidades',receipts)
    src,sm=load(root,'resultados/comparacao_fontes/comunidades',receipts)
    projection,pm=load(root,'dados/processados/redes/projecoes',receipts)
    sources,ss=load(root,'dados/processados/redes/fontes',receipts)
    central,ct=load(root,'resultados/centralidades',receipts)
    tails,tm=load(root,'resultados/temporal/caudas',receipts)
    if cm['network_snapshot_sha256']!=ct['network_snapshot_sha256'] or cm['projection_snapshot_sha256']!=pm['snapshot_sha256']:
        raise ValueError('Edições globais incompatíveis.')
    if not executar:return {'mode':'DRY_RUN','input_stages':receipts,'files_written':0,'api_calls':0,'neo4j_connections':0}
    code_sha=sha(__file__);signature=hashlib.sha256(json.dumps({'version':VERSION,'inputs':receipts,'code_sha256':code_sha},sort_keys=True).encode()).hexdigest()
    base=root/'resultados/revisao_pendencias';base.mkdir(parents=True,exist_ok=True);lock=base/'execucao.lock'
    try:lock.mkdir()
    except FileExistsError:raise RuntimeError('Outra revisão pode estar em execução.') from None
    output=Path(tempfile.mkdtemp(prefix='.revisao_',dir=base));target=base/signature[:20]
    try:
        audits=[];cases=[];pieces=[];details=[];part_global=None;globalpairs=None
        configurations=[('GLOBAL',comm,cm,projection,pm,'ponderada_nao_dirigida.csv.gz',''),*[(key,src,sm,sources,ss,key+'_ponderada_nao_dirigida.csv.gz',key+'_') for key in ['cnn','folha','g1']]]
        for scope,folder,m,pfolder,pmeta,pfile,prefix in configurations:
            parts=read(folder,m,prefix+'particoes_nos.csv.gz',checks);pairs=read(pfolder,pmeta,pfile,checks)
            metric_name=prefix+'metricas_comunidades.csv.gz';saved_stats=read(folder,m,metric_name,checks)
            if scope=='GLOBAL':part_global=parts;globalpairs=pairs
            for run,frame in parts.groupby('run_id'):
                f,summary=connectivity(frame,pairs)
                expected=saved_stats[saved_stats.run_id==run].set_index('community_id').connected_pieces
                calculated=f.groupby('community_id').independent_piece_id.nunique()
                if not calculated.sort_index().equals(expected.sort_index()):raise ValueError('Contagem de partes diverge do snapshot.')
                if not (f.internal_piece_id.to_numpy()==f.independent_piece_id.to_numpy()).all():raise ValueError('Identificadores de partes divergentes.')
                checkpoint_base=root/'resultados'/('comunidades' if scope=='GLOBAL' else 'comparacao_fontes/comunidades')/'execucoes'/folder.name
                cp=checkpoint_base/(run if scope=='GLOBAL' else scope+'/'+run)/'particao.csv.gz'
                if not cp.is_file():raise FileNotFoundError('Checkpoint necessário para auditar a exportação: '+str(cp))
                meta=json.loads((cp.parent/'manifesto.json').read_text(encoding='utf-8'));digest=sha(cp)
                if digest!=meta['outputs_sha256']['particao.csv.gz']:raise ValueError('Checkpoint alterado.')
                checks[str(cp)]=digest;raw=pd.read_csv(cp).sort_values('entity_group_id')
                if not np.array_equal(raw[['entity_group_id','raw_community_id','community_id']].to_numpy(),f[['entity_group_id','raw_community_id','community_id']].to_numpy()):raise ValueError('Partição final difere do checkpoint.')
                summary.update(scope=scope,run_id=run,gds_version=meta['execution']['gds_version'],checkpoint_matches=True,pieces_match_saved=True,bfs_affected_groups_checked=0)
                saved_q=float(saved_stats.loc[saved_stats.run_id==run,'modularity_contribution'].sum())
                if not np.isclose(summary['weighted_modularity_independent'],saved_q,rtol=0,atol=1e-10):raise ValueError('Modularidade diverge do snapshot.')
                summary['saved_modularity_reproduced']=True
                bad=calculated[calculated>1].index
                for cid in bad:
                    group=f[f.community_id==cid].copy();ids=set(group.entity_group_id);edges=pairs[pairs.source_id.isin(ids)&pairs.target_id.isin(ids)]
                    reference=bfs_parts(ids,edges)
                    if any(reference[int(r.entity_group_id)]!=int(r.independent_piece_id) for r in group.itertuples()):raise ValueError('BFS e matriz esparsa divergem.')
                    summary['bfs_affected_groups_checked']+=1
                    cases.append({'scope':scope,'run_id':run,'community_id':int(cid),'nodes':len(group),'pairs':len(edges),'pieces':len(set(reference.values())),
                                  'piece_sizes':json.dumps(sorted(group.groupby('independent_piece_id').size().tolist(),reverse=True))})
                    group.insert(0,'scope',scope);details.append(group)
                    for piece,g in group.groupby('independent_piece_id'):
                        pieces.append({'scope':scope,'run_id':run,'community_id':int(cid),'piece_id':int(piece),'nodes':len(g),'node_ids':json.dumps(sorted(map(int,g.entity_group_id)))})
                audits.append(summary)
                print(f'[REVISÃO] {scope} / {run}: {len(bad)} comunidades desconexas; checkpoint e duas referências conferidos.',flush=True)
        csv(output/'auditoria_particoes.csv',pd.DataFrame(audits));csv(output/'comunidades_desconexas.csv',pd.DataFrame(cases));csv(output/'partes_comunidades.csv',pd.DataFrame(pieces))
        csv(output/'entidades_comunidades_desconexas.csv.gz',pd.concat(details,ignore_index=True))
        tail=review_2012(tails,tm,output,checks)
        nodes=read(central,ct,'centralidades_nos.csv.gz',checks)
        catalog=figures(output,nodes,globalpairs,part_global)
        summary={'partition_runs':len(audits),'all_saved_connectivity_counts_reproduced':True,'all_checkpoints_match':True,
            'disconnected_leiden_community_occurrences':sum(c['run_id'].startswith('leiden') for c in cases),
            'leiden_root_cause':'NOT_ESTABLISHED_OFFLINE','partitions_modified':False,'lognormal_2012':tail,
            'visualizations':catalog,'api_calls':0,'neo4j_connections':0,'network_modified':False,'entity_groups_merged':0,
            'source_cnn_review_performed':False,'joint_2025_network_constructed':False}
        write_json(output/'resumo.json',summary)
        manifest={'schema':SCHEMA,'version':VERSION,'snapshot_sha256':signature,'input_stages':receipts,'input_files_sha256':checks,
                  'created_at_utc':datetime.now(timezone.utc).isoformat(),'summary':summary,
                  'outputs_sha256':{p.name:sha(p) for p in sorted(output.iterdir())}}
        write_json(output/'manifesto.json',manifest)
        if target.exists():
            old=json.loads((target/'manifesto.json').read_text(encoding='utf-8'))
            if old.get('schema')!=SCHEMA:raise ValueError('Destino não pertence à revisão.')
            shutil.rmtree(target)
        output.rename(target);output=None
        package=base/f'Resumo_Revisao_Pendencias_{signature[:12]}.zip';temporary=base/'.pacote.tmp'
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as z:
            for p in sorted(target.iterdir()):z.write(p,p.name)
        with zipfile.ZipFile(temporary) as z:
            if z.testzip() is not None:raise ValueError('ZIP não validado.')
        temporary.replace(package);write_json(base/'atual.json',{'folder':target.name,'snapshot_sha256':signature})
        removed=[]
        for old in list(base.iterdir()):
            if old in [target,package] or old.is_symlink():continue
            if old.is_dir() and re.fullmatch('[a-f0-9]{20}',old.name) and (old/'manifesto.json').is_file():
                if json.loads((old/'manifesto.json').read_text(encoding='utf-8')).get('schema')==SCHEMA:shutil.rmtree(old);removed.append(old.name)
            elif old.is_file() and re.fullmatch('Resumo_Revisao_Pendencias_[a-f0-9]{12}\\.zip',old.name):old.unlink();removed.append(old.name)
        result={**summary,'output_directory':str(target),'package':str(package),'removed_previous_revision_artifacts':removed}
        print('[REVISÃO] Saídas:',target,flush=True);print('[REVISÃO] Pacote:',package,flush=True);return result
    finally:
        if output is not None and output.exists():shutil.rmtree(output)
        lock.rmdir()
