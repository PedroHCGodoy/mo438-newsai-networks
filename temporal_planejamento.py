"""Cobertura e planejamento de redes acumuladas da Folha de S.Paulo."""
from pathlib import Path
from datetime import datetime,timezone
import json
import shutil
import tempfile
import uuid
import zipfile
import pandas as pd
from redes_construcao import carregar_rede
from re_consolidacao import sha,json_sha,write_csv,validate_manifest
from re_execucao import atomic_json

VERSION='1.1.0'
MARCOS_ANUAIS=tuple(range(1994,2026))
MARCOS_REFERENCIA=(1994,1995,1996,1997,1998,1999,2000,2001,2002,2003,2004,2005,2007,2010,2013,2016,2019,2022,2025)
FONTE='Folha de S.Paulo'


def calcular_cobertura(noticias,arestas,evidencias,*,marcos=MARCOS_ANUAIS):
    marcos=list(marcos)
    if not marcos or marcos!=sorted(set(marcos)) or any(isinstance(a,bool) or not isinstance(a,int) or a<1994 or a>2025 for a in marcos):
        raise ValueError('Marcos devem ser anos inteiros distintos e crescentes entre 1994 e 2025.')
    if noticias.news_id.duplicated().any() or arestas.edge_id.duplicated().any():
        raise ValueError('Identidade documental ou de aresta duplicada.')
    n=noticias.loc[noticias.source.eq(FONTE)].copy()
    anos=pd.to_numeric(n.publication_year,errors='raise')
    if anos.isna().any() or not anos.mod(1).eq(0).all():raise ValueError('Ano ausente ou não inteiro.')
    n['publication_year']=anos.astype(int)
    n=n.loc[n.publication_year.between(1994,2025)]
    if n.empty:raise ValueError('Corpus da Folha ausente no período.')
    keys=['news_id','news_version_id']
    if evidencias.duplicated(['edge_id']+keys).any():raise ValueError('Suporte aresta-notícia duplicado.')
    v=evidencias[keys].drop_duplicates().merge(noticias[keys],on=keys,how='left',indicator=True)
    if not v['_merge'].eq('both').all():raise ValueError('Evidência com versão documental desconhecida.')
    e=evidencias.merge(n[keys+['publication_year']],on=keys,how='inner',suffixes=('_e',''),validate='many_to_one')
    if not e.source.eq(FONTE).all() or not pd.to_numeric(e.publication_year_e).eq(e.publication_year).all():
        raise ValueError('Fonte ou ano divergente na evidência.')
    values=pd.to_numeric(e.occurrence_count,errors='raise')
    if not values.ge(1).all() or not values.mod(1).eq(0).all():raise ValueError('Contagens de ocorrências inválidas.')
    e['occurrence_count']=values.astype(int)
    e=e.merge(arestas[['edge_id','source_id','target_id']],on='edge_id',how='left',validate='many_to_one')
    if e.source_id.isna().any() or e.source_id.eq(e.target_id).any():raise ValueError('Aresta desconhecida ou autolaço.')
    all_nodes=set();all_edges=set();all_pairs=set();annual=[]
    for year in range(1994,2026):
        g=n.loc[n.publication_year.eq(year)];relations=e.loc[e.publication_year.eq(year)]
        nodes=set(relations.source_id)|set(relations.target_id);edges=set(relations.edge_id)
        pairs={tuple(sorted((int(a),int(b)))) for a,b in zip(relations.source_id,relations.target_id)}
        complete=int(g.re_state.isin(['SUCCESS','SUCCESS_ZERO']).sum());partial=int(g.re_state.eq('PARTIAL').sum())
        annual.append({'publication_year':year,'corpus_news':len(g),'re_completed_strict':complete,'re_partial':partial,
            'too_few_mentions':int(g.re_state.eq('TOO_FEW_MENTIONS').sum()),
            'support_news':int(relations.news_id.nunique()),'retained_occurrences':int(relations.occurrence_count.sum()),
            'strict_completion_share':complete/len(g) if len(g) else None,
            'news_without_completed_or_partial_re':int((~g.re_state.isin(['SUCCESS','SUCCESS_ZERO','PARTIAL'])).sum()),
            'nodes_in_year':len(nodes),'typed_edges_in_year':len(edges),'undirected_pairs_in_year':len(pairs),
            'first_seen_nodes':len(nodes-all_nodes),'first_seen_typed_edges':len(edges-all_edges),
            'cumulative_nodes':len(all_nodes|nodes),'cumulative_typed_edges':len(all_edges|edges),
            'cumulative_undirected_pairs':len(all_pairs|pairs),
            'no_completed_re_in_year':complete==0,'no_retained_relations_in_year':relations.empty})
        all_nodes.update(nodes);all_edges.update(edges);all_pairs.update(pairs)
    annual=pd.DataFrame(annual)
    for key in ['corpus_news','re_completed_strict','re_partial','support_news','retained_occurrences']:
        annual['cumulative_'+key]=annual[key].cumsum()
    for key in ['cumulative_nodes','cumulative_typed_edges','cumulative_undirected_pairs']:
        if annual[key].diff().dropna().lt(0).any():raise ValueError('Acumulação não monotônica.')
    estados=n.groupby(['publication_year','re_state'],as_index=False).size().rename(columns={'size':'news_count'})
    precisao=n.groupby(['publication_year','publication_date_precision'],as_index=False).size().rename(columns={'size':'news_count'})
    def planejar(cortes):
        rows=[];previous=1993
        for i,year in enumerate(cortes,1):
            upto=annual.loc[annual.publication_year.eq(year)].iloc[0]
            interval=annual.loc[annual.publication_year.between(previous+1,year)]
            row={'snapshot_order':i,'cutoff_year':year,'cumulative_start_year':1994,
                'interval_start_year':previous+1,'interval_end_year':year,'interval_calendar_years':year-previous}
            for key in ['corpus_news','re_completed_strict','re_partial','support_news','retained_occurrences']:
                row['cumulative_'+key]=int(upto['cumulative_'+key]);row['interval_'+key]=int(interval[key].sum())
            for key in ['cumulative_nodes','cumulative_typed_edges','cumulative_undirected_pairs']:row[key]=int(upto[key])
            row['cumulative_strict_completion_share']=row['cumulative_re_completed_strict']/row['cumulative_corpus_news'] if row['cumulative_corpus_news'] else None
            row['interval_strict_completion_share']=row['interval_re_completed_strict']/row['interval_corpus_news'] if row['interval_corpus_news'] else None
            row['interval_support_news_per_calendar_year']=row['interval_support_news']/row['interval_calendar_years']
            rows.append(row);previous=year
        return pd.DataFrame(rows)
    return {'cobertura_anual.csv':annual,'estados_re_ano.csv':estados,'precisao_datas_ano.csv':precisao,
        'marcos_planejados.csv':planejar(marcos),'alternativa_anual.csv':planejar(range(1994,2026)),
        'marcos_referencia.csv':planejar(MARCOS_REFERENCIA)}


def figuras(folder,annual):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    plt.rcParams.update({'font.size':10,'svg.fonttype':'none','pdf.fonttype':42})
    fig,axes=plt.subplots(2,1,figsize=(12,7),sharex=True)
    axes[0].plot(annual.publication_year,annual.corpus_news,color='#606060',label='Notícias no corpus')
    axes[0].plot(annual.publication_year,annual.re_completed_strict,color='tab:orange',label='RE concluída estritamente')
    axes[0].plot(annual.publication_year,annual.support_news,color='tab:green',label='Notícias com relações retidas')
    axes[0].set_ylabel('Notícias');axes[0].legend(frameon=False);axes[0].grid(alpha=.2)
    axes[1].bar(annual.publication_year,annual.strict_completion_share,color='tab:orange')
    axes[1].set_ylim(0,1.05);axes[1].yaxis.set_major_formatter(PercentFormatter(1))
    axes[1].set_ylabel('Cobertura da RE concluída');axes[1].set_xlabel('Ano de publicação')
    axes[1].set_xticks(list(range(1994,2026,2)));axes[1].tick_params(axis='x',rotation=45);axes[1].grid(axis='y',alpha=.2)
    fig.tight_layout();catalog=[]
    for ext in ['svg','png','pdf']:
        name='cobertura_temporal_folha.'+ext;fig.savefig(folder/name,dpi=220,bbox_inches='tight')
        catalog.append({'file':name,'objective':'Distinguir volume documental, processamento e suporte da rede ao longo do tempo.',
            'caption':'Folha de S.Paulo, 1994–2025. Conclusão estrita inclui SUCCESS e SUCCESS_ZERO; PARTIAL é informada separadamente nas tabelas. As proporções usam as notícias do corpus em cada ano. Ausência de RE não demonstra ausência de relações no noticiário.'})
    plt.close(fig);return pd.DataFrame(catalog)


def planejar_evolucao_temporal(projeto,*,executar=False,marcos=MARCOS_ANUAIS,assinatura_rede_esperada=None):
    root=Path(projeto).resolve()
    if root.name=='PROJECT_EXTRACAO':raise ValueError('Use o projeto de análise.')
    source,meta=carregar_rede(root)
    if assinatura_rede_esperada and meta['snapshot_sha256']!=assinatura_rede_esperada:raise ValueError('Rede ativa diferente da edição esperada.')
    marcos=list(marcos)
    if marcos!=sorted(set(marcos)) or not marcos or any(isinstance(a,bool) or not isinstance(a,int) or not 1994<=a<=2025 for a in marcos):
        raise ValueError('Marcos inválidos.')
    if not executar:
        return {'mode':'DRY_RUN','source':FONTE,'cutoff_years':marcos,'snapshot_count':len(marcos),
            'include_intervening_years':True,'annual_alternative_count':32,'api_calls':0,'neo4j_connections':0,'files_written':0}
    names=['noticias.csv.gz','arestas.csv.gz','arestas_noticias.csv.gz']
    inputs=[pd.read_csv(source/name,dtype=str,keep_default_na=False) for name in names]
    tables=calcular_cobertura(*inputs,marcos=marcos);annual=tables['cobertura_anual.csv']
    spec={'schema':'temporal-coverage-plan-1','version':VERSION,'code_sha256':sha(Path(__file__)),
        'network_snapshot_sha256':meta['snapshot_sha256'],'source':FONTE,'cutoff_years':marcos,
        'include_intervening_years':True,'inputs_sha256':{name:sha(source/name) for name in names}}
    assinatura=json_sha(spec);base=root/'resultados/temporal/planejamento';base.mkdir(parents=True,exist_ok=True);destino=base/assinatura[:20]
    resumo={'source':FONTE,'corpus_news_1994_2025':int(annual.corpus_news.sum()),'support_news':int(annual.support_news.sum()),
        'retained_occurrences':int(annual.retained_occurrences.sum()),'snapshot_count':len(marcos),'cutoff_years':marcos,
        'annual_alternative_count':32,'years_without_completed_re':annual.loc[annual.no_completed_re_in_year,'publication_year'].tolist(),
        'api_calls':0,'neo4j_connections':0,'networks_constructed':False,'global_network_modified':False}
    if destino.exists():
        salvo=validate_manifest(destino)
        if salvo['snapshot_sha256']!=assinatura:raise ValueError('Assinatura da saída incompatível.')
    else:
        temp=Path(tempfile.mkdtemp(prefix='.planejamento_',dir=base))
        try:
            for name,table in tables.items():write_csv(temp,name,table)
            write_csv(temp,'catalogo_figuras.csv',figuras(temp,annual))
            (temp/'LEIA_ME.md').write_text('# Evolução acumulada — cobertura e planejamento\n\n'
                'Cada corte inclui todas as notícias e relações retidas da fonte desde 1994 até o ano limite, '
                'incluindo os anos intermediários. O corte é anual: precisão inferior a dia é documentada, '
                'sem atribuir artificialmente data exata a uma notícia com apenas ano conhecido.\n\n'
                'A série principal utiliza 32 cortes anuais. Os 19 marcos de referência são preservados '
                'como seleção da série. Os intervalos entre marcos configurados podem possuir durações '
                'diferentes; volume e cobertura são informados separadamente em cada intervalo e no acumulado.\n\n'
                'As contagens acumuladas de nós e arestas são obtidas dos IDs nas evidências retidas; não são '
                'uma nova construção ou execução de métricas estruturais. Ausência de relações novas pode decorrer '
                'de falta de extração. Crescimento acumulado não demonstra vantagem cumulativa ou evolução real '
                'do noticiário sem considerar cobertura e seleção. A resolução de entidades compartilhada entre '
                'anos é retrospectiva, usando a edição completa; não é uma avaliação prospectiva sem informação futura.\n',encoding='utf-8')
            atomic_json(temp/'manifesto.json',{**spec,'snapshot_sha256':assinatura,'summary':resumo,
                'created_at_utc':datetime.now(timezone.utc).isoformat(),
                'outputs_sha256':{p.name:sha(p) for p in sorted(temp.iterdir())}})
            validate_manifest(temp);temp.rename(destino)
        finally:
            if temp.exists():shutil.rmtree(temp)
    atomic_json(base/'atual.json',{'folder':destino.name,'snapshot_sha256':assinatura})
    pacote=base/('Resumo_Planejamento_Temporal_'+assinatura[:12]+'_'+uuid.uuid4().hex[:6]+'.zip')
    with zipfile.ZipFile(pacote,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(destino.iterdir()):z.write(p,p.name)
    print('[TEMPORAL]',json.dumps(resumo,ensure_ascii=False));print('[TEMPORAL] Pacote:',pacote)
    return {**resumo,'output_directory':destino,'package':pacote,'snapshot_sha256':assinatura}
