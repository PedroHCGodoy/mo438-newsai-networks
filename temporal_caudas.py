"""Cauda dos graus, comparação de distribuições e concentração complementar."""
from pathlib import Path
from datetime import datetime, timezone
from importlib.metadata import version
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
import warnings
import shutil
import tempfile
import uuid
import zipfile
import numpy as np
import pandas as pd
from temporal_redes import ANOS
from re_consolidacao import sha, json_sha, write_csv, validate_manifest
from re_execucao import atomic_json

VERSION='1.0.0'


def carregar_trajetorias(root, assinatura_esperada=None):
    base=Path(root)/'resultados/temporal/protagonismo'
    ptr=json.loads((base/'atual.json').read_text(encoding='utf-8'))
    if Path(ptr['folder']).name!=ptr['folder']:raise ValueError('Índice de protagonismo inválido.')
    folder=base/ptr['folder'];meta=validate_manifest(folder)
    if ptr['snapshot_sha256']!=meta['snapshot_sha256']:raise ValueError('Índice de protagonismo incompatível.')
    if assinatura_esperada and meta['snapshot_sha256']!=assinatura_esperada:raise ValueError('Edição de protagonismo inesperada.')
    return folder,meta


def validar_graus(values):
    x=np.asarray(values,dtype=float)
    if x.ndim!=1 or not len(x) or not np.isfinite(x).all() or (x<1).any() or not np.equal(x,np.floor(x)).all():
        raise ValueError('Graus devem ser inteiros positivos, sem valores ausentes.')
    return x.astype('int64')


def concentracao(values):
    x=np.sort(validar_graus(values));n=len(x);s=int(x.sum())
    out={'nodes':n,'degree_sum':s,'mean_degree':float(x.mean()),'median_degree':float(np.median(x)),
        'max_degree':int(x[-1]),'degree_one_share':float(np.mean(x==1)),
        'gini_degree':float(2*np.dot(np.arange(1,n+1,dtype=float),x)/(n*s)-(n+1)/n)}
    for fraction in [.01,.05,.10]:
        k=max(1,int(np.ceil(n*fraction)));key=str(int(100*fraction))
        out['top_'+key+'pct_nodes']=k;out['top_'+key+'pct_degree_share']=float(x[-k:].sum()/s)
    return out


def ajustar(values):
    """Estimador discreto por máxima verossimilhança; xmin selecionado por KS."""
    import powerlaw
    x=validar_graus(values);buf=StringIO()
    with warnings.catch_warnings(record=True) as caught,redirect_stdout(buf),redirect_stderr(buf):
        warnings.simplefilter('always')
        fit=powerlaw.Fit(x,discrete=True,estimate_discrete=False,verbose=False)
        p=fit.power_law
        stats={'xmin':float(p.xmin),'alpha':float(p.alpha),'sigma_iid':float(p.sigma),
            'ks_distance':float(p.D),'tail_nodes':int(np.sum(x>=p.xmin)),
            'tail_share':float(np.mean(x>=p.xmin)),'power_law_noise_flag':bool(getattr(p,'noise_flag',False))}
    if not np.isfinite([stats['xmin'],stats['alpha'],stats['ks_distance']]).all() or stats['alpha']<=1:
        raise ValueError('Ajuste discreto sem parâmetros válidos.')
    diagnostics=[str(w.message) for w in caught]
    if buf.getvalue().strip():diagnostics.append(buf.getvalue().strip()[-2500:])
    return fit,stats,diagnostics


def comparar(fit):
    rows=[]
    for other in ['lognormal','exponential','truncated_power_law']:
        row={'alternative':other,'nested':other=='truncated_power_law','xmin':float(fit.power_law.xmin)}
        buf=StringIO()
        try:
            with warnings.catch_warnings(record=True) as caught,redirect_stdout(buf),redirect_stderr(buf):
                warnings.simplefilter('always')
                dist=getattr(fit,other)
                ratio,p=fit.distribution_compare('power_law',other,nested=row['nested'],normalized_ratio=False)
                parameters={name:float(getattr(dist,name)) for name in ['alpha','Lambda','mu','sigma'] if hasattr(dist,name)}
                noisy=bool(getattr(dist,'noise_flag',False))
            messages=[str(w.message) for w in caught]
            library_message=buf.getvalue().strip()[-2500:]
            # O aviso de comparação aninhada informa o método; não é falha numérica.
            numerical_output='\n'.join(line for line in library_message.splitlines()
                if line.strip()!='Assuming nested distributions').strip()
            row.update(log_likelihood_ratio=float(ratio),p_iid_diagnostic=float(p),
                parameters=json.dumps(parameters),noise_flag=noisy,
                status='REVIEW_NUMERICS' if messages or noisy or numerical_output else 'COMPLETED',
                warnings=' | '.join(messages),library_messages=library_message)
            if not np.isfinite([ratio,p]).all():row['status']='INVALID_NUMERIC_RESULT'
        except Exception as exc:
            row.update(status='FAILED',error_type=type(exc).__name__)
        rows.append(row)
    return rows


def bootstrap(values,fit,*,repeticoes,seed,folder):
    """Semiparamétrico iid: corpo empírico, cauda ajustada, novo xmin por réplica."""
    x=validar_graus(values);folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    xmin=fit.power_law.xmin;body=x[x<xmin];tail_share=float(np.mean(x>=xmin))
    records=[]
    for i in range(repeticoes):
        path=folder/f'{i:05d}.json'
        if path.exists():
            row=json.loads(path.read_text(encoding='utf-8'))
            if row['replicate']!=i or row['seed']!=seed:raise ValueError('Réplica de bootstrap incompatível.')
        else:
            rng=np.random.default_rng(np.random.SeedSequence([seed,i]))
            ntail=len(x) if not len(body) else int(rng.binomial(len(x),tail_share))
            state=np.random.get_state();buf=StringIO()
            try:
                # A biblioteca usa o gerador legado; seu estado externo é restaurado.
                np.random.seed(int(rng.integers(0,2**32-1)))
                with redirect_stdout(buf),redirect_stderr(buf),warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter('always')
                    tail=fit.power_law.generate_random(ntail,estimate_discrete=False) if ntail else np.array([],dtype=int)
                sample=np.concatenate([rng.choice(body,len(x)-ntail,replace=True) if len(body) else np.array([],dtype=int),tail])
                _,stats,diagnostics=ajustar(sample)
                row={'replicate':i,'seed':seed,'status':'VALID',**stats,
                    'generation_warnings':[str(w.message) for w in caught],'fit_diagnostics':diagnostics,
                    'max_generated_degree':int(np.max(sample))}
            except Exception as exc:
                row={'replicate':i,'seed':seed,'status':'FAILED','error_type':type(exc).__name__}
            finally:np.random.set_state(state)
            atomic_json(path,row)
        records.append(row)
        if (i+1)%10==0 or i+1==repeticoes:
            print(f'[CAUDAS] Bootstrap 2025: {i+1}/{repeticoes} réplicas salvas.',flush=True)
    valid=[r for r in records if r['status']=='VALID'];exceed=sum(r['ks_distance']>=fit.power_law.D for r in valid)
    complete=len(valid)==repeticoes and repeticoes>0
    p=(exceed+1)/(repeticoes+1) if complete else None
    return pd.DataFrame(records),{'repetitions_requested':repeticoes,'valid_repetitions':len(valid),
        'status':'COMPLETE' if complete else 'INCOMPLETE' if repeticoes else 'NOT_REQUESTED',
        'observed_ks':float(fit.power_law.D),'p_iid_semiparametric':p,
        'monte_carlo_standard_error':float(np.sqrt(p*(1-p)/repeticoes)) if complete else None,
        'plus_one_correction':True,'seed':seed,'network_dependence_accounted_for':False}


def gerar_figuras(folder,dist,fits,concentration,curve,boot,bootstrap_summary):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    plt.rcParams.update({'font.size':10,'svg.fonttype':'none','pdf.fonttype':42});catalog=[]
    def save(fig,name,objective,caption):
        fig.tight_layout()
        for ext in ['svg','png','pdf']:
            f=name+'.'+ext;fig.savefig(Path(folder)/f,dpi=300,bbox_inches='tight');catalog.append({'file':f,'objective':objective,'caption':caption})
        plt.close(fig)
    fig,ax=plt.subplots(figsize=(8,5))
    for year in [1997,2005,2016,2019,2022,2025]:
        d=dist.loc[dist.cutoff_year.eq(year)];ax.plot(d.degree,d.ccdf_ge_k,marker='.',markersize=3,label=str(year))
    ax.set(xscale='log',yscale='log',xlabel='Grau k',ylabel='P(K ≥ k)');ax.legend(frameon=False);ax.grid(alpha=.2,which='both')
    save(fig,'01_ccdf_comparacao','Examinar diferenças na distribuição dos graus ao longo do tempo.',
        'CCDFs empíricas da projeção simples. Os cortes selecionados seguem a comparação temporal de referência; '
        'sua cobertura varia. Aparência aproximadamente linear em log-log não demonstra lei de potência.')
    fig,ax=plt.subplots(figsize=(8,5));d=dist.loc[dist.cutoff_year.eq(2025)]
    ax.plot(d.degree,d.ccdf_ge_k,'.',label='CCDF empírica',color='tab:blue')
    ax.plot(curve.degree,curve.ccdf_power_law_scaled,label='Lei de potência ajustada na cauda',color='tab:orange')
    xmin=float(fits.loc[fits.cutoff_year.eq(2025),'xmin'].iloc[0]);ax.axvline(xmin,color='gray',linestyle='--',label=f'xmin={xmin:g}')
    ax.set(xscale='log',yscale='log',xlabel='Grau k',ylabel='P(K ≥ k)');ax.legend(frameon=False);ax.grid(alpha=.2,which='both')
    save(fig,'02_cauda_2025','Localizar o intervalo efetivamente ajustado.',
        'A curva ajustada é escalada pela fração de nós na cauda para comparação com a CCDF completa. '
        'O modelo discreto é ajustado acima de xmin; não descreve automaticamente toda a distribuição. '
        'A figura não substitui o diagnóstico de ajuste e a comparação de alternativas.')
    fig,axes=plt.subplots(3,1,figsize=(10,8),sharex=True)
    for ax,key,label,cor in zip(axes,['alpha','xmin','tail_share'],['Expoente α','Limiar xmin','Fração de nós na cauda'],['tab:blue','tab:orange','tab:blue']):
        ax.plot(fits.cutoff_year,fits[key],marker='o',markersize=3,color=cor);ax.set_ylabel(label);ax.grid(alpha=.2)
    axes[2].yaxis.set_major_formatter(PercentFormatter(1));axes[-1].set_xlabel('Ano limite')
    save(fig,'03_parametros_e_cobertura_cauda','Examinar a estabilidade do ajuste e o tamanho da região ajustada.',
        'Expoentes são condicionados a limiares selecionados separadamente em cada corte. '
        'Diferenças de α não comparam necessariamente a mesma faixa de graus. '
        'As incertezas iid e os sinais numéricos são diagnósticos, sem garantia de validade para graus dependentes de uma rede.')
    fig,axes=plt.subplots(2,1,figsize=(10,7),sharex=True)
    axes[0].plot(concentration.cutoff_year,concentration.gini_degree,color='tab:blue',marker='o',markersize=3)
    axes[0].set(ylabel='Gini dos graus — complementar',ylim=(0,1))
    for key,cor in [('1','tab:blue'),('5','tab:orange'),('10','tab:green')]:
        axes[1].plot(concentration.cutoff_year,concentration['top_'+key+'pct_degree_share'],color=cor,label=key+'% superior')
    axes[1].set(ylabel='Participação na soma dos graus',ylim=(0,1),xlabel='Ano limite');axes[1].yaxis.set_major_formatter(PercentFormatter(1));axes[1].legend(frameon=False)
    for ax in axes:ax.grid(alpha=.2)
    save(fig,'04_concentracao_complementar','Descrever desigualdade e concentração complementarmente à análise da cauda.',
        'Gini e participações dos maiores graus utilizam todos os nós. Cada grupo superior contém ceil(N × fração) '
        'entidades. Participação na soma dos graus não equivale à fração de arestas distintas. '
        'Essas medidas não identificam um mecanismo de vantagem cumulativa.')
    valid=boot.loc[boot.status.eq('VALID')] if 'status' in boot else pd.DataFrame()
    if len(valid):
        fig,ax=plt.subplots(figsize=(8,4.5));ax.hist(valid.ks_distance,bins=20,color='tab:blue',alpha=.75)
        ax.axvline(bootstrap_summary['observed_ks'],color='tab:orange',label='KS observado')
        ax.set(xlabel='KS após novo ajuste em cada réplica',ylabel='Réplicas');ax.legend(frameon=False)
        save(fig,'05_bootstrap_2025','Contextualizar o afastamento observado em uma referência semiparamétrica.',
            'Corpo empírico e cauda discreta de lei de potência; xmin e α são reestimados em cada réplica. '
            'Esta simulação iid não gera redes e não preserva dependência entre graus. '
            'Seu p-valor é diagnóstico; não representa a probabilidade de o modelo ser verdadeiro.')
    return pd.DataFrame(catalog)


def analisar_caudas_temporais(projeto,*,executar=False,repeticoes_bootstrap=199,seed=42,
                              assinatura_protagonismo_esperada=None):
    root=Path(projeto).resolve()
    if root.name=='PROJECT_EXTRACAO':raise ValueError('Use o projeto de análise.')
    if isinstance(repeticoes_bootstrap,bool) or not isinstance(repeticoes_bootstrap,int) or repeticoes_bootstrap<0:raise ValueError('Réplicas devem ser inteiras não negativas.')
    if isinstance(seed,bool) or not isinstance(seed,int) or seed<0:raise ValueError('Semente deve ser inteira não negativa.')
    origem,meta=carregar_trajetorias(root,assinatura_protagonismo_esperada)
    if not executar:
        out={'mode':'DRY_RUN','snapshot_count':32,'discrete_mle':True,'estimate_discrete':False,
            'bootstrap_year':2025,'bootstrap_repetitions':repeticoes_bootstrap,'seed':seed,
            'alternatives':['lognormal','exponential','truncated_power_law'],
            'gini_role':'complementary','api_calls':0,'neo4j_connections':0,'files_written':0}
        print('[CAUDAS]',json.dumps(out));return out
    try:pv=version('powerlaw')
    except Exception:raise ImportError('Instale powerlaw==1.5 no ambiente do notebook antes da execução.') from None
    if pv!='1.5':raise ValueError('Esta implementação foi verificada com powerlaw==1.5. Instale a versão indicada no ambiente do notebook.')
    import scipy
    from scipy.special import zeta
    spec={'schema':'temporal-degree-tails-1','version':VERSION,'code_sha256':sha(Path(__file__)),
        'protagonism_snapshot_sha256':meta['snapshot_sha256'],'powerlaw_version':pv,'scipy_version':scipy.__version__,
        'numpy_version':np.__version__,'bootstrap_repetitions':repeticoes_bootstrap,'seed':seed,
        'discrete':True,'estimate_discrete':False,'bootstrap_year':2025,'iid_reference_only':True}
    signature=json_sha(spec);base=root/'resultados/temporal/caudas';base.mkdir(parents=True,exist_ok=True)
    target=base/signature[:20];lock=base/'analise.lock';temp=None
    try:lock.mkdir()
    except FileExistsError:raise RuntimeError('Análise pode estar ativa. Confira o bloqueio antes de retomar.') from None
    try:
        if target.exists():
            saved=validate_manifest(target)
            if saved['snapshot_sha256']!=signature:raise ValueError('Resultado incompatível.')
            summary=saved['summary']
        else:
            temp=Path(tempfile.mkdtemp(prefix='.caudas_',dir=base))
            data=pd.read_csv(origem/'trajetorias_entidades.csv.gz',usecols=['entity_group_id','cutoff_year','degree'])
            if sorted(data.cutoff_year.unique())!=list(ANOS) or data.duplicated(['entity_group_id','cutoff_year']).any():raise ValueError('Trajetórias incompletas ou duplicadas.')
            fits=[];comparisons=[];cs=[];distributions=[];diagnostics=[]
            for year,g in data.groupby('cutoff_year',sort=True):
                x=validar_graus(g.degree);fit,stats,logs=ajustar(x)
                fits.append({'cutoff_year':int(year),**stats,'small_tail_diagnostic':stats['tail_nodes']<50})
                comparisons.extend({'cutoff_year':int(year),**row} for row in comparar(fit))
                cs.append({'cutoff_year':int(year),**concentracao(x)})
                counts=pd.Series(x).value_counts().sort_index();d=pd.DataFrame({'degree':counts.index,'nodes':counts.to_numpy()})
                d['cutoff_year']=year;d['probability']=d.nodes/len(x);d['ccdf_ge_k']=d.nodes.iloc[::-1].cumsum().iloc[::-1]/len(x)
                distributions.append(d);diagnostics.append({'cutoff_year':int(year),'messages':logs})
                if year==2025:last_fit=fit;last_x=x
                print(f'[CAUDAS] {year}: xmin={stats["xmin"]:g}; α={stats["alpha"]:.3f}; '
                      f'{stats["tail_nodes"]:,} nós na cauda; ajuste salvo em preparação.',flush=True)
            boot_spec={k:v for k,v in spec.items() if k!='bootstrap_repetitions'}
            boot_signature=json_sha(boot_spec);boot_folder=base/'bootstrap'/boot_signature[:20]
            boot_folder.mkdir(parents=True,exist_ok=True)
            if (boot_folder/'contrato.json').exists():
                if json.loads((boot_folder/'contrato.json').read_text())!=boot_spec:raise ValueError('Contrato de bootstrap incompatível.')
            else:atomic_json(boot_folder/'contrato.json',boot_spec)
            if repeticoes_bootstrap and fits[-1]['tail_nodes']<50:
                boot=pd.DataFrame();bs={'status':'NOT_RUN_SMALL_TAIL','tail_nodes':fits[-1]['tail_nodes']}
            else:boot,bs=bootstrap(last_x,last_fit,repeticoes=repeticoes_bootstrap,seed=seed,folder=boot_folder/'replicas')
            xmin=last_fit.power_law.xmin;alpha=last_fit.power_law.alpha
            grid=np.unique(np.rint(np.geomspace(xmin,last_x.max(),200))).astype(int)
            curve=pd.DataFrame({'degree':grid,'ccdf_power_law_scaled':np.mean(last_x>=xmin)*zeta(alpha,grid)/zeta(alpha,xmin)})
            ft=pd.DataFrame(fits);ct=pd.DataFrame(cs);dist=pd.concat(distributions,ignore_index=True);cp=pd.DataFrame(comparisons)
            for name,table in [('ajustes_cauda.csv',ft),('comparacao_modelos.csv',cp),('concentracao_complementar.csv',ct),
                ('distribuicoes_graus.csv',dist),('curva_ajustada_2025.csv',curve),('bootstrap_replicas.csv',boot)]:write_csv(temp,name,table)
            atomic_json(temp/'bootstrap_resumo.json',bs);atomic_json(temp/'diagnosticos_ajuste.json',diagnostics)
            catalog=gerar_figuras(temp,dist,ft,ct,curve,boot,bs);write_csv(temp,'catalogo_figuras.csv',catalog)
            summary={'snapshot_count':32,'comparisons':len(cp),'comparisons_requiring_review':int(cp.status.ne('COMPLETED').sum()),
                'bootstrap_2025':bs,'figure_files':len(catalog),'gini_role':'complementary',
                'scale_free_network_concluded':False,'cumulative_advantage_tested':False,
                'api_calls':0,'neo4j_connections':0,'network_modified':False}
            (temp/'LEIA_ME.md').write_text(NOTAS,encoding='utf-8')
            if carregar_trajetorias(root,assinatura_protagonismo_esperada)[1]['snapshot_sha256']!=meta['snapshot_sha256']:raise ValueError('Entradas alteradas durante a análise.')
            atomic_json(temp/'manifesto.json',{**spec,'snapshot_sha256':signature,'summary':summary,
                'created_at_utc':datetime.now(timezone.utc).isoformat(),'outputs_sha256':{p.name:sha(p) for p in sorted(temp.iterdir())}})
            validate_manifest(temp);temp.rename(target);temp=None
        atomic_json(base/'atual.json',{'folder':target.name,'snapshot_sha256':signature})
    finally:
        if temp is not None and temp.exists():shutil.rmtree(temp)
        lock.rmdir()
    package=base/f'Resumo_Caudas_Temporais_{signature[:12]}_{uuid.uuid4().hex[:6]}.zip'
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(target.iterdir()):z.write(p,p.name)
    print('[CAUDAS]',json.dumps(summary,ensure_ascii=False));print('[CAUDAS] Pacote:',package)
    return {**summary,'output_directory':target,'package':package,'snapshot_sha256':signature}


NOTAS='''# Cauda e concentração dos graus

O estimador principal é o modelo discreto de lei de potência por máxima
verossimilhança, sem a aproximação estimate_discrete. O limiar xmin é
selecionado pela distância KS. A fração
da rede efetivamente ajustada e os sinais numéricos são registrados.
Caudas com menos de 50 nós são sinalizadas operacionalmente; 50 não é
um limiar de validade científica. Nenhum ajuste usa regressão em log-log.

Lognormal, exponencial e lei de potência com corte exponencial são
comparadas na mesma amostra acima do xmin da lei de potência. As outras
distribuições seguem as implementações e discretizações de powerlaw 1.5;
estimate_discrete=False não torna exatas todas as distribuições alternativas.
A razão de log-verossimilhança é não normalizada: positiva favorece a
lei de potência; negativa favorece a alternativa. Para o corte exponencial,
o teste é aninhado e sua calibração requer cautela, inclusive na fronteira
do parâmetro de corte. Avisos e flags numéricos impedem leitura automática
de preferência confiável. Não se escolhe vencedor apenas pelo sinal de R.

O bootstrap de 2025 mistura o corpo empírico com a cauda de lei de potência
e refaz a seleção de xmin e o ajuste em cada réplica. Os resultados ficam
salvos para retomada, com semente por réplica e restauração do estado
aleatório externo. O p-valor usa correção de uma unidade; sua precisão
Monte Carlo é informada. Falhas não são descartadas silenciosamente:
se qualquer réplica falhar, o resumo fica incompleto e não informa p.

Trata-se de referência univariada iid, não de simulação de redes. Graus
de uma rede não são observações independentes; a simulação não preserva
dependência ou restrição k≤N−1 e pode gerar valores maiores. Os p-valores
do bootstrap e das razões, assim como sigma, são diagnósticos sob essa
aproximação. Não fornecem garantia inferencial para a rede observada.
Não rejeitar o modelo não prova que ele seja verdadeiro; preferi-lo a uma
alternativa não comprova adequação absoluta. Uma cauda ajustada não basta
para chamar toda a rede de livre de escala ou demonstrar Efeito Mateus.

Gini e participações superiores são complementares, sobre todos os nós.
Essas medidas descrevem concentração; a lei de potência trata da forma
da distribuição na cauda. Elas não respondem à mesma pergunta e não
substituem o teste posterior de associação entre grau anterior e ganhos.

Referências metodológicas: Clauset, Shalizi e Newman (2009), DOI
10.1137/070710111; Alstott, Bullmore e Plenz (2014), DOI
10.1371/journal.pone.0085777. A análise utiliza apenas graus persistidos,
sem extração remota ou consulta ao Neo4j.
'''
