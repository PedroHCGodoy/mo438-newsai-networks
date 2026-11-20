"""Caracterização exata da topologia simples, não dirigida e não ponderada."""
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
import json
import math
import os
import shutil
import tempfile
import time
import uuid
import zipfile
import numpy as np
import pandas as pd
from redes_construcao import carregar_rede
from redes_projecoes import carregar_projecoes, verificar_projecao, valores_esperados
from re_consolidacao import sha, json_sha, write_csv, validate_manifest
from re_execucao import atomic_json
from neo4j_integracao import _configuration, _failure

VERSION='1.0.0'
ALGORITHMS={'degree':('gds.degree','score'), 'triangles':('gds.triangleCount','triangleCount'),
            'components':('gds.wcc','componentId')}


def _read(path):return pd.read_csv(path,dtype=str,keep_default_na=False)


def calcular_referencia(nodes,pairs):
    """Conferência independente em memória: adjacências, triângulos e componentes."""
    ids=sorted(map(int,nodes));adj={i:set() for i in ids}
    seen=set()
    for a,b in pairs:
        a,b=int(a),int(b)
        if a not in adj or b not in adj or a==b:raise ValueError('Extremo inválido ou autolaço.')
        pair=tuple(sorted((a,b)))
        if pair in seen:raise ValueError('Par repetido na projeção simples.')
        seen.add(pair);adj[a].add(b);adj[b].add(a)
    degrees={i:len(adj[i]) for i in ids}
    forward={i:{j for j in adj[i] if (degrees[i],i)<(degrees[j],j)} for i in ids}
    triangles={i:0 for i in ids}
    for a in ids:
        for b in forward[a]:
            for c in forward[a]&forward[b]:
                triangles[a]+=1;triangles[b]+=1;triangles[c]+=1
    components={};unseen=set(ids)
    for start in ids:
        if start not in unseen:continue
        stack=[start];unseen.remove(start);members=[]
        while stack:
            a=stack.pop();members.append(a)
            for b in adj[a]:
                if b in unseen:unseen.remove(b);stack.append(b)
        canonical=min(members)
        for a in members:components[a]=canonical
    return pd.DataFrame({'entity_group_id':ids,'degree':[degrees[i] for i in ids],
        'triangle_count':[triangles[i] for i in ids], 'component_id':[components[i] for i in ids]})


def resumir_metricas(frame, edge_count):
    f=frame.copy()
    if not f.entity_group_id.is_unique or f.empty:raise ValueError('IDs duplicados ou conjunto de nós vazio.')
    for key in ['entity_group_id','degree','triangle_count','component_id']:
        values=pd.to_numeric(f[key],errors='raise')
        if not np.isfinite(values).all() or not values.eq(np.floor(values)).all():
            raise ValueError('Valor não inteiro ou não finito nas métricas.')
        f[key]=values.astype('int64')
    if f.degree.lt(0).any() or f.triangle_count.lt(0).any():raise ValueError('Métrica negativa.')
    # IDs de componentes são arbitrários; canonização pelo menor ID de grupo.
    minimum=f.groupby('component_id').entity_group_id.min()
    f['component_id']=f.component_id.map(minimum).astype('int64')
    f['connected_triples']=f.degree*(f.degree-1)//2
    if (f.triangle_count>f.connected_triples).any():raise ValueError('Triângulos maiores que triplas possíveis.')
    if int(f.degree.sum())!=2*edge_count:raise ValueError('Soma dos graus diferente de 2M.')
    incidence=int(f.triangle_count.sum())
    if incidence%3:raise ValueError('Soma de triângulos incidentes não é múltipla de três.')
    f['local_clustering']=np.divide(f.triangle_count.to_numpy(dtype=float),
        f.connected_triples.to_numpy(dtype=float),out=np.zeros(len(f)),where=f.connected_triples.to_numpy()>0)
    if not f.local_clustering.between(0,1).all():raise ValueError('Clusterização fora de [0,1].')
    eligible=f.degree.ge(2);triples=int(f.connected_triples.sum());N=len(f)
    components=f.groupby('component_id').size().rename('nodes').reset_index().sort_values(
        ['nodes','component_id'],ascending=[False,True],kind='stable').reset_index(drop=True)
    components.insert(0,'rank',np.arange(1,len(components)+1))
    components['node_share']=components.nodes/N
    degree=f.groupby('degree').size().rename('nodes').reset_index().sort_values('degree')
    degree['probability']=degree.nodes/N
    degree['ccdf_ge_k']=degree.nodes.iloc[::-1].cumsum().iloc[::-1]/N
    sizes=components.groupby('nodes').size().rename('components').reset_index().rename(columns={'nodes':'component_size'})
    bins=np.linspace(0,1,21);hist,limits=np.histogram(f.local_clustering,bins=bins)
    clustering_dist=pd.DataFrame({'bin_left':limits[:-1],'bin_right':limits[1:],'nodes':hist})
    summary={'nodes':N,'simple_undirected_edges':int(edge_count),
        'degree_sum':int(f.degree.sum()),'mean_degree':2*edge_count/N,
        'density':2*edge_count/(N*(N-1)) if N>1 else 0.0,
        'min_degree':int(f.degree.min()),'max_degree':int(f.degree.max()),
        'median_degree':float(f.degree.median()),'isolated_nodes':int(f.degree.eq(0).sum()),
        'degree_one_nodes':int(f.degree.eq(1).sum()),'degree_le_two_nodes':int(f.degree.le(2).sum()),
        'nodes_degree_ge_two':int(eligible.sum()),
        'triangles':incidence//3,'connected_triples':triples,
        'mean_local_clustering_degree_ge_two':float(f.loc[eligible,'local_clustering'].mean()) if eligible.any() else None,
        'mean_local_clustering_all_nodes':float(f.local_clustering.mean()),
        'transitivity':incidence/triples if triples else None,
        'zero_clustering_nodes':int(f.local_clustering.eq(0).sum()),
        'connected_components':len(components),'largest_component_nodes':int(components.iloc[0].nodes),
        'largest_component_share':float(components.iloc[0].node_share),
        'distance_metrics_computed':False,'community_detection_computed':False}
    return f,components,degree,sizes,clustering_dist,summary


def _query(session,q,**params):return session.execute_read(lambda tx:[row.data() for row in tx.run(q,**params)])


def executar_algoritmos(session,graph_name):
    results={};estimates={};timings={}
    for key,(algorithm,value) in ALGORITHMS.items():
        estimate=f'''CALL {algorithm}.stream.estimate($name, {{concurrency:4}})
            YIELD nodeCount, relationshipCount, bytesMin, bytesMax, requiredMemory
            RETURN nodeCount, relationshipCount, bytesMin, bytesMax, requiredMemory'''
        estimates[key]=_query(session,estimate,name=graph_name)
        query=f'''CALL {algorithm}.stream($name, {{concurrency:4}}) YIELD nodeId, {value}
            RETURN gds.util.asNode(nodeId).entity_group_id AS entity_group_id, {value} AS value'''
        started=time.monotonic();rows=_query(session,query,name=graph_name)
        timings[key]=round(time.monotonic()-started,3)
        data=pd.DataFrame(rows)
        if data.empty or not data.entity_group_id.is_unique:raise ValueError('Retorno de algoritmo vazio ou duplicado.')
        results[key]=data
        print(f'[ESTRUTURA] {key}: {len(data):,} nós; {timings[key]:.2f}s.',flush=True)
    frame=None
    for key,column in [('degree','degree'),('triangles','triangle_count'),('components','component_id')]:
        part=results[key].rename(columns={'value':column})
        part['entity_group_id']=pd.to_numeric(part.entity_group_id,errors='raise').astype('int64')
        if frame is None:frame=part
        else:
            if set(frame.entity_group_id)!=set(part.entity_group_id):raise ValueError('Algoritmos retornaram universos diferentes.')
            frame=frame.merge(part,on='entity_group_id',validate='one_to_one')
    return frame,estimates,timings


def gerar_figuras(folder,nodes,degree,sizes,clustering_dist,summary):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    folder=Path(folder);catalog=[]
    plt.rcParams.update({'font.size':10,'svg.fonttype':'none','pdf.fonttype':42})
    def save(fig,stem,objective,caption):
        fig.tight_layout()
        for ext in ['svg','png','pdf']:
            name=stem+'.'+ext
            fig.savefig(folder/name,dpi=220,bbox_inches='tight')
            catalog.append({'file':name,'objective':objective,'caption':caption})
        plt.close(fig)
    fig,ax=plt.subplots(figsize=(6.5,4))
    positive=degree.loc[degree.degree.gt(0)]
    ax.scatter(positive.degree,positive.ccdf_ge_k,s=13,color='tab:blue',edgecolors='none')
    ax.set(xscale='log',yscale='log',xlabel='Grau k — vizinhos distintos',ylabel='P(K ≥ k)',
        title='Distribuição acumulada complementar dos graus')
    ax.grid(alpha=.2,which='both')
    save(fig,'01_graus_ccdf','Examinar a heterogeneidade dos graus.',
        'CCDF empírica na projeção simples não dirigida. Eixos logarítmicos; a figura não constitui teste de lei de potência. Nós de grau zero, se existentes, não aparecem no eixo logarítmico.')
    fig,ax=plt.subplots(figsize=(6.5,4))
    nonzero=clustering_dist.loc[clustering_dist.nodes.gt(0)]
    ax.bar(nonzero.bin_left,nonzero.nodes,width=.05,align='edge',color='tab:blue',edgecolor='black',linewidth=.4)
    ax.set(yscale='log',xlim=(0,1),xlabel='Coeficiente de clusterização local',ylabel='Número de nós — escala log',
        title='Distribuição da clusterização local')
    save(fig,'02_clusterizacao_local','Examinar o fechamento das vizinhanças.',
        'Histograma com 20 intervalos de largura 0,05; o último inclui 1. Nós com grau menor que dois têm coeficiente local zero. A média principal reportada considera somente grau ≥ 2.')
    fig,axes=plt.subplots(1,2,figsize=(10,4))
    positions=np.arange(len(sizes));big=summary['largest_component_nodes']
    axes[0].bar(positions,sizes.components,color=['tab:orange' if int(x)==big else 'tab:blue' for x in sizes.component_size])
    axes[0].set(yscale='log',xlabel='Tamanho da componente — categorias observadas',ylabel='Número de componentes — escala log')
    step=max(1,math.ceil(len(sizes)/18));ticks=positions[::step]
    axes[0].set_xticks(ticks,[f'{int(sizes.iloc[i].component_size):,}'.replace(',', '.') for i in ticks],rotation=60,ha='right')
    axes[0].set_title('Distribuição dos tamanhos')
    values=[big,summary['nodes']-big]
    bars=axes[1].bar(['Maior componente','Demais'],values,color=['tab:orange','tab:blue'])
    axes[1].yaxis.set_major_formatter(FuncFormatter(lambda x,pos:f'{x:,.0f}'.replace(',', '.')))
    axes[1].set_ylabel('Número de nós');axes[1].set_title('Participação da maior componente')
    axes[1].set_ylim(0,max(values)*1.2 if max(values)>0 else 1)
    axes[1].bar_label(bars,labels=[f'{v:,}'.replace(',', '.')+'\n('+f'{v/summary["nodes"]:.1%}'.replace('.', ',')+')' for v in values],padding=3)
    save(fig,'03_componentes','Examinar fragmentação e concentração dos nós.',
        'Tamanhos de componentes em eixo categórico, com frequência logarítmica; laranja destaca o maior tamanho. O painel da direita separa uma maior componente das demais. Em caso de empate, a componente com menor ID canônico é a referência.')
    return pd.DataFrame(catalog)


def caracterizar_rede(projeto, *, executar_gds=False, assinatura_rede_esperada=None, driver_factory=None):
    root=Path(projeto).resolve();p_folder,p_meta=carregar_projecoes(root);n_folder,n_meta=carregar_rede(root)
    if assinatura_rede_esperada and n_meta['snapshot_sha256']!=assinatura_rede_esperada:
        raise ValueError('A rede ativa difere da edição esperada.')
    graph_name=p_meta['graph_names']['structural']
    if not executar_gds:
        summary={'mode':'DRY_RUN','neo4j_connections':0,'graph_name':graph_name,
            'nodes':p_meta['summary']['nodes'],'simple_undirected_edges':p_meta['summary']['undirected_pairs'],
            'algorithms':['degree','triangleCount','wcc'],'global_clustering_mean_scope':'degree >= 2',
            'figures_formats':['SVG','PNG','PDF'],'distance_metrics_computed':False}
        print('[ESTRUTURA]',json.dumps(summary,ensure_ascii=False));return summary
    spec={'schema':'structural-network-analysis-1','version':VERSION,
        'network_snapshot_sha256':n_meta['snapshot_sha256'],'projection_snapshot_sha256':p_meta['snapshot_sha256'],
        'code_sha256':sha(Path(__file__)),'concurrency':4,'clustering_mean_scope':'degree >= 2',
        'independent_topology_verification':True}
    signature=json_sha(spec);base=root/'resultados/estrutural';base.mkdir(parents=True,exist_ok=True)
    target=base/signature[:20];lock=base/'analise.lock';driver=None;temp=None
    try:lock.mkdir()
    except FileExistsError:raise RuntimeError('Outra análise estrutural pode estar ativa. Confira o bloqueio.') from None
    try:
        if target.exists():
            meta=validate_manifest(target)
            if meta['snapshot_sha256']!=signature:raise ValueError('Colisão de versão da análise.')
        else:
            try:
                import matplotlib
            except ImportError:
                raise RuntimeError('Instale matplotlib no ambiente Jupyter antes de executar esta etapa.') from None
            nodes=_read(n_folder/'nos.csv.gz');simple=_read(p_folder/'simples_nao_dirigida.csv.gz')
            pairs=_read(p_folder/'ponderada_nao_dirigida.csv.gz');edges=_read(n_folder/'arestas.csv.gz')
            node_ids=set(nodes.entity_group_id.astype(int))
            uri,user,password,database=_configuration(root)
            if driver_factory is None:
                from neo4j import GraphDatabase
                driver_factory=GraphDatabase.driver
            driver=driver_factory(uri,auth=(user,password),connection_timeout=15,max_transaction_retry_time=10)
            driver.verify_connectivity()
            with driver.session(database=database) as session:
                verificar_projecao(session,graph_name,database,'newsai_'+n_meta['snapshot_sha256'][:20],
                    node_ids,valores_esperados('structural',edges,pairs))
                raw,estimates,timings=executar_algoritmos(session,graph_name)
            f,components,degree,sizes,cluster_dist,summary=resumir_metricas(raw,len(simple))
            if set(f.entity_group_id)!=node_ids:raise ValueError('Universo de nós diferente da rede selecionada.')
            reference=calcular_referencia(node_ids,zip(simple.source_id,simple.target_id)).set_index('entity_group_id').sort_index()
            observed=f.set_index('entity_group_id').sort_index()
            for key in ['degree','triangle_count','component_id']:
                if not observed[key].equals(reference[key]):raise ValueError('Divergência na verificação independente: '+key)
            if sum(components.nodes)!=len(f):raise ValueError('Componentes não particionam os nós.')
            summary['independent_topology_verified']=True
            nodes['entity_group_id']=nodes.entity_group_id.astype('int64')
            f=f.merge(nodes[['entity_group_id','entity_group_name','ent_label']],on='entity_group_id',validate='one_to_one')
            temp=Path(tempfile.mkdtemp(prefix='.calculando_',dir=base))
            write_csv(temp,'metricas_nos.csv.gz',f.sort_values('entity_group_id'))
            for name,frame in [('componentes.csv',components),('distribuicao_graus.csv',degree),
                ('distribuicao_tamanhos_componentes.csv',sizes),('distribuicao_clusterizacao.csv',cluster_dist),
                ('resumo_metricas.csv',pd.DataFrame([{'metric':k,'value':v} for k,v in summary.items()]))]:write_csv(temp,name,frame)
            figures=gerar_figuras(temp,f,degree,sizes,cluster_dist,summary);write_csv(temp,'catalogo_figuras.csv',figures)
            atomic_json(temp/'execucao_gds.json',{'estimates':estimates,'algorithm_times_s':timings})
            text=(f'# Caracterização estrutural\n\nA projeção simples não dirigida contém {summary["nodes"]:,} nós e '
                f'{summary["simple_undirected_edges"]:,} arestas. O grau médio é {summary["mean_degree"]:.6f} '
                f'e a densidade é {summary["density"]:.9f}.\n\n'
                f'Foram identificadas {summary["connected_components"]:,} componentes; a maior reúne '
                f'{summary["largest_component_nodes"]:,} nós ({summary["largest_component_share"]:.2%}).\n\n'
                f'A média dos coeficientes locais para grau ≥ 2 é {summary["mean_local_clustering_degree_ge_two"]}; '
                f'a transitividade é {summary["transitivity"]}. São medidas distintas, com denominadores diferentes.\n\n'
                'A distribuição de graus é descritiva e não comprova lei de potência ou vantagem cumulativa. '
                'Os resultados dependem da cobertura das extrações e dos filtros da rede. '
                'Distâncias, diâmetro, centralidades adicionais e comunidades não são calculados nesta etapa.\n')
            (temp/'interpretacao_inicial.md').write_text(text,encoding='utf-8')
            meta={**spec,'snapshot_sha256':signature,'summary':summary,
                'created_at_utc':datetime.now(timezone.utc).isoformat(),
                'outputs_sha256':{p.name:sha(p) for p in sorted(temp.iterdir())}}
            atomic_json(temp/'manifesto.json',meta);validate_manifest(temp)
            if carregar_projecoes(root)[1]['snapshot_sha256']!=p_meta['snapshot_sha256']:
                raise ValueError('As projeções ativas mudaram durante a análise.')
            os.rename(temp,target);temp=None
        atomic_json(base/'atual.json',{'folder':target.name,'snapshot_sha256':signature})
        package=base/f'Resumo_Estrutural_{signature[:12]}_{uuid.uuid4().hex[:6]}.zip'
        with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
            for path in sorted(target.iterdir()):z.write(path,path.name)
        print('[ESTRUTURA]',json.dumps(meta['summary'],ensure_ascii=False));print('[ESTRUTURA] Pacote:',package)
        return {**meta['summary'],'output_directory':target,'package':package,'snapshot_sha256':signature}
    except (ValueError,RuntimeError):raise
    except Exception as exc:
        raise RuntimeError('Análise interrompida. Confira o GDS e as dependências. Diagnóstico: '+json.dumps(_failure(exc))) from None
    finally:
        if driver is not None:driver.close()
        if temp is not None:shutil.rmtree(temp,ignore_errors=True)
        lock.rmdir()
