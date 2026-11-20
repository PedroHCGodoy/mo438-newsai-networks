"""Trajetórias de conectividade, exposição documental e persistência de rankings."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
from time import perf_counter
import json
import shutil
import tempfile
import uuid
import zipfile
import numpy as np
import pandas as pd
from temporal_redes import carregar_redes_temporais, ANOS
from temporal_conexoes import carregar_estrutura
from redes_construcao import carregar_rede
from redes_centralidades import calcular_conectividade
from re_consolidacao import sha, json_sha, write_csv, validate_manifest
from re_execucao import atomic_json

VERSION = '1.0.1'
TYPE_COLORS = {'PESSOA': '#4C78A8', 'ORGANIZACAO': '#F58518', 'LOCAL': '#54A24B'}
TYPE_NAMES = {'PESSOA': 'Pessoas', 'ORGANIZACAO': 'Organizações', 'LOCAL': 'Locais'}


def carregar_conexoes(root, temporal_sha, estrutura_sha, assinatura_esperada=None):
    base = Path(root)/'resultados/temporal/conexoes'
    ptr = json.loads((base/'atual.json').read_text(encoding='utf-8'))
    if Path(ptr['folder']).name != ptr['folder']: raise ValueError('Índice de conexões inválido.')
    folder = base/ptr['folder']; meta = validate_manifest(folder)
    if (meta['snapshot_sha256'] != ptr['snapshot_sha256'] or meta['temporal_snapshot_sha256'] != temporal_sha
            or meta['structural_snapshot_sha256'] != estrutura_sha):
        raise ValueError('Formação de conexões pertence a outra edição.')
    if assinatura_esperada and meta['snapshot_sha256'] != assinatura_esperada: raise ValueError('Edição de conexões inesperada.')
    return folder, meta


def atribuir_rankings(frame):
    f = frame.copy()
    if f.empty or f.entity_group_id.duplicated().any(): raise ValueError('Entidades vazias ou duplicadas no corte.')
    f['degree'] = pd.to_numeric(f.neighbor_degree, errors='raise').astype('int64')
    for campo in ['weighted_strength', 'distinct_news_count', 'relation_news_count', 'mention_count']:
        f[campo] = pd.to_numeric(f[campo], errors='raise').astype('int64')
    if f.degree.lt(0).any(): raise ValueError('Grau negativo.')
    f['degree_normalized'] = f.degree/(len(f)-1) if len(f)>1 else 0.
    f['degree_share'] = f.degree/f.degree.sum() if f.degree.sum() else 0.
    for campo in ['degree', 'weighted_strength', 'relation_news_count', 'distinct_news_count']:
        f[campo+'_rank'] = f[campo].rank(method='min', ascending=False).astype('int64')
    f['degree_rank_within_type'] = f.groupby('ent_label').degree.rank(method='min', ascending=False).astype('int64')
    return f


def selecionar_top(frame, k):
    exato = frame.sort_values(['cutoff_year', 'degree', 'entity_group_id'],
        ascending=[True, False, True]).groupby('cutoff_year', group_keys=False).head(k).copy()
    exato['operational_top_position'] = exato.groupby('cutoff_year').cumcount()+1
    inclusivo = frame.loc[frame.degree_rank.le(k)].copy()
    return exato, inclusivo


def persistencia(top, anos, selecao):
    rows = []
    grupos = {year: set(top.loc[top.cutoff_year.eq(year), 'entity_group_id']) for year in anos}
    for prev, year in zip(anos[:-1], anos[1:]):
        a, b = grupos[prev], grupos[year]; common = len(a & b)
        rows.append({'selection': selecao, 'previous_year': prev, 'cutoff_year': year,
            'interval_calendar_years': year-prev, 'previous_size': len(a), 'current_size': len(b),
            'retained': common, 'entrants': len(b-a), 'exits': len(a-b),
            'retention_share': common/len(a) if a else None,
            'jaccard': common/len(a | b) if a | b else None})
    return pd.DataFrame(rows)


def conferir_ganhos(frame, anterior, events, *, baseline=False):
    f = frame.copy(); ids = set(f.entity_group_id)
    old = {} if anterior is None else anterior.set_index('entity_group_id').degree.to_dict()
    if not set(old).issubset(ids): raise ValueError('Entidades desapareceram no longitudinal.')
    f['previous_degree'] = f.entity_group_id.map(old).fillna(0).astype('int64')
    f['new_neighbors'] = f.degree-f.previous_degree
    f['is_baseline_stock'] = baseline
    if f.new_neighbors.lt(0).any(): raise ValueError('Grau diminuiu em uma rede acumulada.')
    if baseline:
        f['new_neighbors_to_preexisting'] = pd.NA
        f['new_neighbors_to_new'] = pd.NA
        f['reinforcement_occurrences'] = pd.NA
        return f
    ganhos, to_old, to_new, reforco = Counter(), Counter(), Counter(), Counter()
    for e in events.itertuples():
        a,b = int(e.source_id),int(e.target_id)
        if a not in ids or b not in ids: raise ValueError('Evento com extremo fora da rede.')
        if e.event_type == 'NEW_PAIR':
            ganhos.update([a,b])
            for entity, neighbor in [(a,b),(b,a)]:
                (to_old if neighbor in old else to_new)[entity] += 1
        elif e.event_type == 'REINFORCED_PAIR':
            reforco[a] += int(e.added_occurrences); reforco[b] += int(e.added_occurrences)
        else: raise ValueError('Evento desconhecido.')
    expected = f.entity_group_id.map(ganhos).fillna(0).astype('int64')
    if not f.new_neighbors.equals(expected): raise ValueError('Ganho de grau difere dos novos pares por entidade.')
    for col, counter in [('new_neighbors_to_preexisting',to_old),('new_neighbors_to_new',to_new),('reinforcement_occurrences',reforco)]:
        f[col] = f.entity_group_id.map(counter).fillna(0).astype('int64')
    return f


def gerar_figuras(folder, trajetorias, retencao, frequencia, selecionadas, casos):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    catalogo = []
    plt.rcParams.update({'font.size':10, 'svg.fonttype':'none', 'pdf.fonttype':42})
    def salvar(fig, nome, objetivo, legenda):
        fig.tight_layout()
        for ext in ['svg','png','pdf']:
            file = nome+'.'+ext; fig.savefig(Path(folder)/file,dpi=300,bbox_inches='tight')
            catalogo.append({'file':file,'objective':objetivo,'caption':legenda})
        plt.close(fig)
    fig,ax = plt.subplots(figsize=(10,4.5))
    for selection,cor,label in [('EXACT_K','tab:blue','Exatamente K, desempate por ID'),('WITH_BOUNDARY_TIES','tab:orange','Incluindo empates na posição K')]:
        d=retencao.loc[retencao.selection.eq(selection)]
        ax.plot(d.cutoff_year,d.retention_share,color=cor,marker='o',markersize=3,label=label)
    ax.set(ylim=(0,1.05),xlabel='Ano final da transição',ylabel='Retenção do grupo anterior')
    ax.yaxis.set_major_formatter(PercentFormatter(1));ax.legend(frameon=False);ax.grid(alpha=.2)
    salvar(fig,'01_retencao_rankings','Examinar estabilidade e sensibilidade aos empates.',
        'Fração das entidades do grupo anterior que permanece no grupo seguinte. A seleção exata utiliza ID '
        'para desempatar; o ranking científico preserva empates. A seleção inclusiva pode ter mais de K entidades. '
        'Persistência em redes acumuladas não demonstra atividade documental em todos os anos.')
    fig,axes=plt.subplots(1,3,figsize=(15,5),sharey=True)
    tipos=['LOCAL','ORGANIZACAO','PESSOA']
    for ax,tipo in zip(axes,tipos):
        chosen=selecionadas.loc[selecionadas.ent_label.eq(tipo)&selecionadas.selected_by_final_type_top]
        for e in chosen.itertuples():
            d=trajetorias.loc[trajetorias.entity_group_id.eq(e.entity_group_id)].set_index('cutoff_year').reindex(ANOS)
            ax.plot(list(ANOS),d.degree_rank,marker='o',markersize=2,label=f'{e.entity_group_name} [{e.entity_group_id}]')
        ax.set_title(TYPE_NAMES[tipo]);ax.set_xlabel('Ano limite');ax.set_yscale('log');ax.grid(alpha=.2)
        ax.legend(fontsize=7,frameon=False,loc='best')
    axes[0].invert_yaxis();axes[0].set_ylabel('Posição global por grau — escala log')
    salvar(fig,'02_trajetorias_por_tipo','Examinar trajetórias das entidades mais conectadas no corte final.',
        'Seleção retrospectiva das primeiras entidades por tipo em 2025, com desempate por ID. '
        'O eixo apresenta posição no ranking global, preservando empates. Ausência anterior na rede não recebe '
        'posição ou grau imputado. A seleção privilegia destaques finais e não representa amostra imparcial das trajetórias.')
    fig,axes=plt.subplots(2,2,figsize=(12,7),sharex=True)
    campos=[('degree','Grau — vizinhos distintos'),('degree_normalized','Grau / (N−1)'),
            ('new_neighbors','Novos vizinhos no ano'),('annual_mention_news','Notícias com menção no ano')]
    for ax,(campo,label) in zip(axes.flat,campos):
        for e in selecionadas.loc[selecionadas.entity_group_id.isin(casos)].itertuples():
            d=trajetorias.loc[trajetorias.entity_group_id.eq(e.entity_group_id)].set_index('cutoff_year').reindex(ANOS)
            v=d[campo]
            if campo=='new_neighbors':v=v.where(~d.is_baseline_stock.eq(True))
            ax.plot(list(ANOS),v,marker='o',markersize=3,label=f'{e.entity_group_name} [{e.entity_group_id}; {e.ent_label}]')
        ax.set_ylabel(label);ax.grid(alpha=.2)
    axes[0,0].legend(fontsize=7,frameon=False)
    for ax in axes[-1]:ax.set_xlabel('Ano limite')
    salvar(fig,'03_casos_conectividade_e_exposicao','Distinguir acúmulo de grau, conectividade relativa, ganhos e exposição.',
        'Casos configurados por ID, sem união de grupos ou correção de seus rótulos. Notícias com menção '
        'podem não possuir RE concluída. O estoque inicial não é ganho anual. O crescimento observado e sua '
        'associação visual com exposição não demonstram vantagem cumulativa ou causalidade.')
    chosen=frequencia.loc[frequencia.cutoffs_in_exact_top_k.gt(0)].sort_values(
        ['cutoffs_in_exact_top_k','mean_rank_when_in_network','entity_group_id'],ascending=[False,True,True]).head(20).iloc[::-1]
    fig,ax=plt.subplots(figsize=(9,max(5,.30*len(chosen)+1.5)))
    ax.barh([f'{r.entity_group_name} [{r.entity_group_id}]' for r in chosen.itertuples()],chosen.cutoffs_in_exact_top_k,
            color=[TYPE_COLORS.get(x,'gray') for x in chosen.ent_label])
    ax.set(xlabel='Número de cortes anuais no grupo de exatamente K entidades',xlim=(0,32));ax.grid(axis='x',alpha=.2);ax.set_axisbelow(True)
    salvar(fig,'04_frequencia_no_top','Identificar entidades recorrentes entre as mais conectadas.',
        'Número de cortes em que a entidade integra o grupo de exatamente K, com desempate por ID. '
        'Verde identifica locais, laranja organizações e azul pessoas, conforme os tipos canônicos preservados. '
        'As frequências são condicionadas à cobertura e ao tempo desde a entrada na rede; não medem atividade anual.')
    return pd.DataFrame(catalogo)


def analisar_protagonismo_temporal(projeto, *, executar=False, top_k=20, top_por_tipo=5, casos=(),
        assinatura_rede_esperada=None, assinatura_temporal_esperada=None,
        assinatura_estrutura_esperada=None, assinatura_conexoes_esperada=None):
    root=Path(projeto).resolve()
    if root.name=='PROJECT_EXTRACAO':raise ValueError('Use o projeto de análise.')
    if any(isinstance(x,bool) or not isinstance(x,int) or x<1 for x in [top_k,top_por_tipo]):raise ValueError('Limites de seleção devem ser inteiros positivos.')
    casos=list(casos)
    if any(isinstance(x,bool) or not isinstance(x,int) or x<0 for x in casos) or len(set(casos))!=len(casos):raise ValueError('Casos devem ser IDs inteiros distintos.')
    origem,meta=carregar_redes_temporais(root,assinatura_rede_esperada)
    if assinatura_temporal_esperada and meta['snapshot_sha256']!=assinatura_temporal_esperada:raise ValueError('Série temporal inesperada.')
    if carregar_rede(root)[1]['snapshot_sha256']!=meta['network_snapshot_sha256']:raise ValueError('Rede global ativa incompatível.')
    estrutura,emeta=carregar_estrutura(root,meta['snapshot_sha256'],assinatura_estrutura_esperada)
    conexoes,cmeta=carregar_conexoes(root,meta['snapshot_sha256'],emeta['snapshot_sha256'],assinatura_conexoes_esperada)
    if not executar:
        out={'mode':'DRY_RUN','snapshot_count':32,'top_k':top_k,'top_per_type':top_por_tipo,'configured_case_ids':casos,
            'reuse_saved_degrees':True,'preserve_rank_ties':True,'api_calls':0,'neo4j_connections':0,'files_written':0}
        print('[PROTAGONISMO TEMPORAL]',json.dumps(out));return out
    start=perf_counter()
    spec={'schema':'temporal-entity-trajectories-1','version':VERSION,'code_sha256':sha(Path(__file__)),
        'connectivity_code_sha256':sha(Path(calcular_conectividade.__code__.co_filename)),
        'network_snapshot_sha256':meta['network_snapshot_sha256'],'temporal_snapshot_sha256':meta['snapshot_sha256'],
        'structural_snapshot_sha256':emeta['snapshot_sha256'],'connections_snapshot_sha256':cmeta['snapshot_sha256'],
        'top_k':top_k,'top_per_type':top_por_tipo,'configured_case_ids':casos,
        'rank_tie_method':'min','exact_top_tiebreak':'entity_group_id ascending','selection_reference_year':2025}
    signature=json_sha(spec);base=root/'resultados/temporal/protagonismo';base.mkdir(parents=True,exist_ok=True)
    target=base/signature[:20];lock=base/'analise.lock';temp=None
    try:lock.mkdir()
    except FileExistsError:raise RuntimeError('Análise pode estar ativa; confira o bloqueio antes de retomar.') from None
    try:
        if target.exists():
            saved=validate_manifest(target)
            if saved['snapshot_sha256']!=signature:raise ValueError('Assinatura de resultado incompatível.')
            summary=saved['summary']
        else:
            temp=Path(tempfile.mkdtemp(prefix='.protagonismo_',dir=base))
            events=pd.read_csv(conexoes/'eventos_pares_anuais.csv.gz')
            cobertura=pd.read_csv(origem/'cobertura_anual.csv').set_index('publication_year')
            parts=[];previous=None
            for year in ANOS:
                folder=origem/str(year)
                ler=lambda n:pd.read_csv(folder/n,dtype=str,keep_default_na=False)
                nodes,edges,simple=[ler(n) for n in ['nos.csv.gz','arestas.csv.gz','simples_nao_dirigida.csv.gz']]
                structural=pd.read_csv(estrutura/str(year)/'metricas_nos.csv.gz')
                f,totals=calcular_conectividade(nodes,edges,simple,structural)
                f=atribuir_rankings(f);f['cutoff_year']=year
                nn=ler('nos_noticias.csv.gz');nn['entity_group_id']=nn.entity_group_id.astype(int)
                annual=nn.loc[pd.to_numeric(nn.publication_year).eq(year)].copy()
                annual['mention_count']=pd.to_numeric(annual.mention_count)
                annual['relation_participation_count']=pd.to_numeric(annual.relation_participation_count)
                cols={'annual_mentions':annual.groupby('entity_group_id').mention_count.sum(),
                    'annual_mention_news':annual.groupby('entity_group_id').news_id.nunique(),
                    'annual_relation_news':annual.loc[annual.relation_participation_count.gt(0)].groupby('entity_group_id').news_id.nunique()}
                for col,s in cols.items():f[col]=f.entity_group_id.map(s).fillna(0).astype('int64')
                if int(annual.relation_participation_count.sum())!=2*int(cobertura.loc[year,'retained_occurrences']):
                    raise ValueError('Participações anuais não recompõem ocorrências da cobertura.')
                f=conferir_ganhos(f,previous,events.loc[events.cutoff_year.eq(year)],baseline=year==1994)
                if int(f.degree.sum())!=2*len(simple) or int(f.weighted_strength.sum())!=2*totals['record_weight_sum']:
                    raise ValueError('Somas de graus ou forças incompatíveis.')
                if not np.isclose(f.degree_share.sum(),1):raise ValueError('Participações no grau não somam um.')
                parts.append(f);previous=f[['entity_group_id','degree']]
                print(f'[PROTAGONISMO TEMPORAL] {year}: {len(f):,} entidades; rankings e ganhos conferidos.',flush=True)
            longitudinal=pd.concat(parts,ignore_index=True)
            exact,inclusive=selecionar_top(longitudinal,top_k)
            retention=pd.concat([persistencia(exact,list(ANOS),'EXACT_K'),persistencia(inclusive,list(ANOS),'WITH_BOUNDARY_TIES')],ignore_index=True)
            refs=meta['reference_cutoff_years']
            retention_ref=pd.concat([persistencia(exact,refs,'EXACT_K'),persistencia(inclusive,refs,'WITH_BOUNDARY_TIES')],ignore_index=True)
            frequency=longitudinal.groupby(['entity_group_id','entity_group_name','ent_label'],as_index=False).agg(
                cutoffs_in_network=('cutoff_year','nunique'),first_network_year=('cutoff_year','min'),
                best_rank=('degree_rank','min'),mean_rank_when_in_network=('degree_rank','mean'),
                cutoffs_with_relation_news=('annual_relation_news',lambda x:int(x.gt(0).sum())))
            for label,top in [('exact',exact),('inclusive',inclusive)]:
                freq=top.groupby('entity_group_id').cutoff_year.nunique()
                frequency['cutoffs_in_'+label+'_top_k']=frequency.entity_group_id.map(freq).fillna(0).astype(int)
            frequency['share_all_cutoffs_in_exact_top']=frequency.cutoffs_in_exact_top_k/len(ANOS)
            frequency['share_since_entry_in_exact_top']=frequency.cutoffs_in_exact_top_k/frequency.cutoffs_in_network
            final=longitudinal.loc[longitudinal.cutoff_year.eq(2025)]
            selected=final.sort_values(['degree','entity_group_id'],ascending=[False,True]).groupby('ent_label',group_keys=False).head(top_por_tipo)
            top_ids=set(selected.entity_group_id)
            if not set(casos).issubset(set(final.entity_group_id)):raise ValueError('Caso configurado ausente da rede final.')
            selected=final.loc[final.entity_group_id.isin(top_ids|set(casos)),['entity_group_id','entity_group_name','ent_label','degree','degree_rank']].copy()
            selected['selected_by_final_type_top']=selected.entity_group_id.isin(top_ids)
            selected['configured_case']=selected.entity_group_id.isin(casos)
            trajectories=longitudinal.loc[longitudinal.entity_group_id.isin(selected.entity_group_id)].copy()
            all_nn=ler('nos_noticias.csv.gz');all_nn['entity_group_id']=all_nn.entity_group_id.astype(int)
            news=ler('noticias.csv.gz')
            links=all_nn.loc[all_nn.entity_group_id.isin(selected.entity_group_id)].merge(news,
                on=['news_id','news_version_id'],validate='many_to_one',suffixes=('_node',''))
            case_links=links.loc[links.entity_group_id.isin(casos)].copy()
            audit=selected.loc[selected.configured_case].copy()
            audit['document_review_required']=True
            audit['canonical_type_preserved']=True
            for name,table in [('trajetorias_entidades.csv.gz',longitudinal),('top_exato.csv',exact),
                ('top_com_empates.csv',inclusive),('persistencia_anual.csv',retention),
                ('persistencia_marcos_referencia.csv',retention_ref),('frequencia_rankings.csv.gz',frequency),
                ('entidades_selecionadas.csv',selected),('trajetorias_selecionadas.csv.gz',trajectories),
                ('entidades_noticias.csv.gz',links),('casos_noticias.csv.gz',case_links),('auditoria_casos.csv',audit)]:
                write_csv(temp,name,table)
            write_csv(temp,'catalogo_figuras.csv',gerar_figuras(temp,trajectories,retention,frequency,selected,casos))
            summary={'snapshot_count':32,'top_k':top_k,'selected_entities':len(selected),
                'configured_case_ids':casos,'entity_cutoff_rows':len(longitudinal),
                'unique_entities':int(longitudinal.entity_group_id.nunique()),
                'all_degrees_match_saved_structure':True,'all_neighbor_gains_match_pair_events':True,
                'rank_ties_preserved':True,'figure_files':12,'pagerank_computed':False,
                'cumulative_advantage_tested':False,'api_calls':0,'neo4j_connections':0,'database_writes':0,
                'entity_groups_merged':0,'canonical_types_changed':0,'network_modified':False}
            (temp/'LEIA_ME.md').write_text(NOTAS,encoding='utf-8')
            if carregar_redes_temporais(root,assinatura_rede_esperada)[1]['snapshot_sha256']!=meta['snapshot_sha256']:
                raise ValueError('Série temporal alterada durante a execução.')
            carregar_estrutura(root,meta['snapshot_sha256'],emeta['snapshot_sha256'])
            carregar_conexoes(root,meta['snapshot_sha256'],emeta['snapshot_sha256'],cmeta['snapshot_sha256'])
            atomic_json(temp/'manifesto.json',{**spec,'snapshot_sha256':signature,'summary':summary,
                'created_at_utc':datetime.now(timezone.utc).isoformat(),
                'outputs_sha256':{p.name:sha(p) for p in sorted(temp.iterdir())}})
            validate_manifest(temp);temp.rename(target);temp=None
        atomic_json(base/'atual.json',{'folder':target.name,'snapshot_sha256':signature})
    finally:
        if temp is not None and temp.exists():shutil.rmtree(temp)
        lock.rmdir()
    package=base/f'Resumo_Protagonismo_Temporal_{signature[:12]}_{uuid.uuid4().hex[:6]}.zip'
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(target.iterdir()):z.write(p,p.name)
    out={**summary,'elapsed_seconds_this_run':perf_counter()-start,'snapshot_sha256':signature,
        'output_directory':target,'package':package}
    print('[PROTAGONISMO TEMPORAL]',json.dumps({k:v for k,v in out.items() if k not in ['output_directory','package']},ensure_ascii=False))
    print('[PROTAGONISMO TEMPORAL] Pacote:',package)
    return out


NOTAS='''# Protagonismo e persistência temporal

Os graus já calculados são conferidos com os pares persistidos, sem nova
execução GDS. Força soma ocorrências incidentes; grau conta vizinhos
distintos. O grau normalizado é k/(N-1); a participação no grau é k/soma(k).
Grau crescente não implica participação relativa crescente.

Rankings usam competição com empates preservados. O Top K exato desempata
por menor ID apenas para seleção operacional. Também se exporta seleção
que inclui todos os empatados no limite, com retenção e Jaccard próprios.
Frequência entre cortes acumulados não equivale a frequência nas notícias.
As proporções sobre os 32 cortes e desde a entrada são informadas separadas.

Cada novo vizinho é confrontado com os pares novos da etapa de conexões.
O estoque de 1994 é identificado e não representa ganho desde um ano
observado anterior. Reforço não acrescenta vizinhos. O grau anterior e
os ganhos ficam salvos para futura análise de vantagem cumulativa, que
não é testada aqui. Não se conclui Efeito Mateus apenas por uma trajetória.

Notícias com menção incluem documentos com NER mesmo sem RE concluída;
notícias com participação relacional exigem relação retida. As medidas
anuais contextualizam a persistência topológica imposta pela acumulação.
Ausência prévia na rede não é preenchida com uma posição de ranking zero.

A seleção das entidades mais conectadas por tipo em 2025 é retrospectiva,
privilegiando destaques finais. Os casos configurados por ID são mantidos
separados, com seus tipos canônicos originais e documentos para inspeção.
Uma eventual interpretação metonímica ou inconsistência de tipagem não
é resolvida automaticamente. Não há fusões ou correções silenciosas.

Use entity_group_id e cutoff_year para trajetórias. Os arquivos de notícias
permitem recuperar títulos, links, categorias e exposição dos casos e das
entidades selecionadas. A soma das notícias por entidade pode contar o
mesmo documento várias vezes; para corpus, conte news_id distintos.

Não há consultas Neo4j, PageRank temporal, extração remota ou alteração da
rede. Os resultados dependem das edições verificadas das etapas anteriores.
As figuras podem ser refeitas a partir das tabelas persistidas usando
gerar_figuras em outra pasta, preservando os artefatos já verificados.
'''
