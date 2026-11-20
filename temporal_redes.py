"""Redes acumuladas anuais com identidades e suporte documental preservados."""
from pathlib import Path
from datetime import datetime, timezone
from time import perf_counter
import json
import os
import shutil
import tempfile
import uuid
import zipfile
import pandas as pd
from redes_construcao import carregar_rede
from redes_fontes import construir_fonte
from redes_projecoes import preparar_tabelas
from temporal_planejamento import calcular_cobertura, FONTE, MARCOS_REFERENCIA
from re_consolidacao import sha, json_sha, write_csv, validate_manifest
from re_execucao import atomic_json

VERSION = '1.0.0'
ANOS = tuple(range(1994, 2026))
ENTRADAS = ('noticias.csv.gz', 'nos.csv.gz', 'arestas.csv.gz',
            'nos_noticias.csv.gz', 'arestas_noticias.csv.gz')


def validar_transicao(anterior, atual, ano):
    """Confere identidades, atributos canônicos e monotonicidade por aresta."""
    v = atual['nos.csv.gz'].set_index('entity_group_id')
    a = atual['arestas.csv.gz'].set_index('edge_id')
    antigos_v = set() if anterior is None else set(anterior['nos.csv.gz'].entity_group_id)
    antigos_a = set() if anterior is None else set(anterior['arestas.csv.gz'].edge_id)
    if not antigos_v.issubset(v.index) or not antigos_a.issubset(a.index):
        raise ValueError('Identidades desapareceram na acumulação em ' + str(ano))
    if anterior is not None:
        ov = anterior['nos.csv.gz'].set_index('entity_group_id')
        oa = anterior['arestas.csv.gz'].set_index('edge_id')
        for col in ['entity_group_name', 'ent_label']:
            if not ov[col].astype(str).equals(v.loc[ov.index, col].astype(str)):
                raise ValueError('Atributo canônico alterado: ' + col)
        for col in ['source_id', 'target_id', 'label', 'relation_macro']:
            if not oa[col].astype(str).equals(a.loc[oa.index, col].astype(str)):
                raise ValueError('Identidade semântica alterada: ' + col)
        for col in ['weight', 'distinct_news_count']:
            if (pd.to_numeric(a.loc[oa.index, col]).to_numpy() < pd.to_numeric(oa[col]).to_numpy()).any():
                raise ValueError('Contagem diminuiu na acumulação: ' + col)
    return {'cutoff_year': ano, 'previous_cutoff_year': ano-1 if anterior is not None else '',
            'new_nodes': len(v)-len(antigos_v), 'new_typed_edges': len(a)-len(antigos_a),
            'previous_nodes_preserved': True, 'previous_edges_preserved': True,
            'canonical_attributes_preserved': True, 'edge_weights_nondecreasing': True,
            'edge_news_counts_nondecreasing': True}


def conferir_corte(tabelas, resumo, esperado, ano):
    """Compara o grafo materializado com contagens independentes da cobertura."""
    correspondencias = {'selected_news': 'cumulative_corpus_news',
        're_completed_strict': 'cumulative_re_completed_strict', 're_partial': 'cumulative_re_partial',
        'support_news': 'cumulative_support_news', 'weight_sum': 'cumulative_retained_occurrences',
        'nodes': 'cumulative_nodes', 'typed_directed_edges': 'cumulative_typed_edges',
        'undirected_pairs': 'cumulative_undirected_pairs'}
    for key, ref in correspondencias.items():
        if int(resumo[key]) != int(esperado[ref]):
            raise ValueError(f'Corte {ano}: {key} difere da cobertura independente.')
    for nome in ['noticias.csv.gz', 'nos_noticias.csv.gz', 'arestas_noticias.csv.gz']:
        f = tabelas[nome]
        if not f.source.eq(FONTE).all() or not pd.to_numeric(f.publication_year).between(1994, ano).all():
            raise ValueError('Documento fora da fonte ou do período: ' + nome)
    a = tabelas['arestas.csv.gz']
    if set(tabelas['nos.csv.gz'].entity_group_id) != set(a.source_id) | set(a.target_id):
        raise ValueError('Extremidades não recompõem os nós.')


def _ler(folder, nomes=ENTRADAS):
    return {nome: pd.read_csv(folder/nome, dtype=str, keep_default_na=False) for nome in nomes}


def carregar_redes_temporais(projeto, assinatura_rede_esperada=None):
    """Abre apenas uma série completa e confere os arquivos dos 32 cortes."""
    base = Path(projeto).resolve()/'dados/processados/redes/temporais'
    atual = json.loads((base/'atual.json').read_text(encoding='utf-8'))
    nome = atual['folder']
    if Path(nome).name != nome:
        raise ValueError('Pasta temporal inválida.')
    folder = base/nome
    meta = validate_manifest(folder)
    if meta['snapshot_sha256'] != atual['snapshot_sha256']:
        raise ValueError('Índice temporal incompatível.')
    if assinatura_rede_esperada and meta['network_snapshot_sha256'] != assinatura_rede_esperada:
        raise ValueError('Série temporal pertence a outra edição da rede.')
    if meta['cutoff_years'] != list(ANOS):
        raise ValueError('Série anual incompleta.')
    for ano in ANOS:
        sub = folder/str(ano)
        if sha(sub/'manifesto.json') != meta['cutoff_manifests_sha256'][str(ano)]:
            raise ValueError('Manifesto temporal modificado: ' + str(ano))
        child = validate_manifest(sub)
        if child['series_sha256'] != meta['snapshot_sha256'] or child['cutoff_year'] != ano:
            raise ValueError('Corte incompatível com a série.')
    return folder, meta


def construir_redes_temporais(projeto, *, executar=False, assinatura_rede_esperada=None):
    root = Path(projeto).resolve()
    if root.name == 'PROJECT_EXTRACAO':
        raise ValueError('Use o projeto de análise.')
    origem, rede = carregar_rede(root)
    if assinatura_rede_esperada and rede['snapshot_sha256'] != assinatura_rede_esperada:
        raise ValueError('A rede ativa difere da edição esperada.')
    if not executar:
        resumo = {'mode': 'DRY_RUN', 'source': FONTE, 'snapshot_count': 32,
            'cutoff_years': list(ANOS), 'reference_cutoff_years': list(MARCOS_REFERENCIA),
            'recompute_weights_from_evidence': True, 'api_calls': 0,
            'neo4j_connections': 0, 'database_writes': 0, 'files_written': 0}
        print('[REDES TEMPORAIS]', json.dumps(resumo, ensure_ascii=False))
        return resumo
    inicio = perf_counter()
    inputs = _ler(origem)
    spec = {'schema': 'annual-cumulative-networks-1', 'version': VERSION,
        'code_sha256': sha(Path(__file__)),
        'builder_code_sha256': sha(Path(construir_fonte.__code__.co_filename)),
        'projection_code_sha256': sha(Path(preparar_tabelas.__code__.co_filename)),
        'coverage_code_sha256': sha(Path(calcular_cobertura.__code__.co_filename)),
        'network_snapshot_sha256': rede['snapshot_sha256'], 'source': FONTE,
        'start_year': 1994, 'cutoff_years': list(ANOS),
        'reference_cutoff_years': list(MARCOS_REFERENCIA),
        'policies': {'node_universe': 'endpoints of retained relations',
            'weights': 'sum of retained occurrences inside source and cumulative period',
            'entity_resolution': 'shared retrospective canonical IDs; no additional merges',
            'missing_relations': 'no imputation', 'self_loops': False, 'identity_edges': False},
        'inputs_sha256': {nome: sha(origem/nome) for nome in ENTRADAS}}
    assinatura = json_sha(spec)
    base = root/'dados/processados/redes/temporais'
    base.mkdir(parents=True, exist_ok=True)
    destino = base/assinatura[:20]
    destino.mkdir(exist_ok=True)
    lock = destino/'construcao.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError('Construção bloqueada. Verifique se há execução ativa antes de arquivar construcao.lock.') from None
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump({'pid': os.getpid(), 'started_at_utc': datetime.now(timezone.utc).isoformat()}, stream)
    criados = reutilizados = 0
    try:
        cobertura = calcular_cobertura(inputs['noticias.csv.gz'], inputs['arestas.csv.gz'],
                                      inputs['arestas_noticias.csv.gz'], marcos=ANOS)
        referencia = cobertura['marcos_planejados.csv'].set_index('cutoff_year')
        anterior = None
        rows, audits = [], []
        for ano in ANOS:
            sub = destino/str(ano)
            if sub.exists():
                meta = validate_manifest(sub)
                if meta['series_sha256'] != assinatura or meta['cutoff_year'] != ano:
                    raise ValueError('Corte salvo incompatível: ' + str(ano))
                tabelas = _ler(sub, tuple(meta['outputs_sha256']))
                resumo = meta['summary']
                reutilizados += 1
            else:
                tabelas, resumo = construir_fonte(*(inputs[nome] for nome in ENTRADAS),
                    fonte=FONTE, inicio=pd.Timestamp('1994-01-01'), fim=pd.Timestamp(f'{ano}-12-31'))
                conferir_corte(tabelas, resumo, referencia.loc[ano], ano)
                validar_transicao(anterior, tabelas, ano)
                temp = Path(tempfile.mkdtemp(prefix=f'.{ano}_', dir=destino))
                try:
                    for nome, tabela in tabelas.items():
                        write_csv(temp, nome, tabela)
                    atomic_json(temp/'manifesto.json', {'schema': 'annual-cumulative-cutoff-1',
                        'snapshot_sha256': json_sha([assinatura, ano]), 'series_sha256': assinatura,
                        'cutoff_year': ano, 'summary': resumo,
                        'outputs_sha256': {p.name: sha(p) for p in sorted(temp.iterdir())}})
                    validate_manifest(temp)
                    temp.rename(sub)
                finally:
                    if temp.exists():
                        shutil.rmtree(temp)
                criados += 1
            conferir_corte(tabelas, resumo, referencia.loc[ano], ano)
            audits.append(validar_transicao(anterior, tabelas, ano))
            rows.append({'cutoff_year': ano, 'cumulative_start_year': 1994,
                         'is_reference_cutoff': ano in MARCOS_REFERENCIA, **resumo})
            print(f'[REDES TEMPORAIS] {ano}: {resumo["nodes"]:,} nós; '
                  f'{resumo["typed_directed_edges"]:,} arestas tipadas; '
                  f'{resumo["weight_sum"]:,} ocorrências; corte salvo e conferido.', flush=True)
            anterior = {k: tabelas[k] for k in ['nos.csv.gz', 'arestas.csv.gz']}
        if carregar_rede(root)[1]['snapshot_sha256'] != rede['snapshot_sha256']:
            raise ValueError('A edição da rede mudou durante a construção.')
        if any(sha(origem/nome) != spec['inputs_sha256'][nome] for nome in ENTRADAS):
            raise ValueError('Entradas modificadas durante a construção.')
        resumo = {'source': FONTE, 'snapshot_count': 32, 'reference_snapshot_count': 19,
            'cutoff_years': list(ANOS), 'last_snapshot': rows[-1], 'all_transitions_verified': True,
            'all_cutoffs_match_independent_coverage': True, 'api_calls': 0, 'neo4j_connections': 0,
            'database_writes': 0, 'global_network_modified': False,
            'scientific_algorithms_computed': False}
        resumo_frame = pd.DataFrame(rows)
        write_csv(destino, 'resumo_redes_anuais.csv', resumo_frame)
        write_csv(destino, 'resumo_marcos_referencia.csv', resumo_frame.loc[resumo_frame.is_reference_cutoff])
        write_csv(destino, 'auditoria_transicoes.csv', pd.DataFrame(audits))
        for nome in ['cobertura_anual.csv', 'estados_re_ano.csv', 'precisao_datas_ano.csv']:
            write_csv(destino, nome, cobertura[nome])
        (destino/'LEIA_ME.md').write_text(NOTAS, encoding='utf-8')
        atomic_json(destino/'manifesto.json', {**spec, 'snapshot_sha256': assinatura,
            'summary': resumo, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'outputs_sha256': {p.name: sha(p) for p in sorted(destino.iterdir())
                              if p.is_file() and p.name not in ['manifesto.json', 'construcao.lock']},
            'cutoff_manifests_sha256': {str(ano): sha(destino/str(ano)/'manifesto.json') for ano in ANOS}})
        validate_manifest(destino)
        atomic_json(base/'atual.json', {'folder': destino.name, 'snapshot_sha256': assinatura})
    finally:
        lock.unlink(missing_ok=True)
    # O pacote de conferência contém resumos e manifestos; tabelas completas ficam nos cortes.
    saidas = root/'resultados/temporal/redes'
    saidas.mkdir(parents=True, exist_ok=True)
    pacote = saidas/f'Resumo_Redes_Temporais_{assinatura[:12]}_{uuid.uuid4().hex[:6]}.zip'
    with zipfile.ZipFile(pacote, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(destino.iterdir()):
            if p.is_file():
                z.write(p, p.name)
        for ano in ANOS:
            z.write(destino/str(ano)/'manifesto.json', f'{ano}/manifesto.json')
    resultado = {**resumo, 'new_snapshots_this_run': criados, 'reused_snapshots_this_run': reutilizados,
                 'elapsed_seconds_this_run': perf_counter()-inicio,
                 'output_directory': destino, 'package': pacote, 'snapshot_sha256': assinatura}
    print('[REDES TEMPORAIS]', json.dumps({k: v for k, v in resultado.items()
                                        if k not in ['output_directory', 'package']}, ensure_ascii=False))
    print('[REDES TEMPORAIS] Pacote:', pacote)
    return resultado


NOTAS = '''# Redes acumuladas anuais

Os 32 cortes, de 1994 a 2025, integram a mesma série de análise. Os 19 marcos
de referência são uma seleção da série, sem segunda construção ou exclusão
dos anos intermediários. Cada pasta anual contém nós, arestas semânticas
dirigidas e tipadas, documentos, vínculos nó-notícia e aresta-notícia,
projeções simples e ponderadas não dirigidas e vínculos de projeção.

Os pesos e atributos são recalculados para a fonte e o período. Os nós são
extremidades de relações retidas; mention_count e distinct_news_count podem
incluir documentos com NER sem RE concluída. relation_news_count registra
suporte relacional. IDs, títulos, links e categorias preservam rastreabilidade.
Não se somam notícias distintas de arestas diferentes para estimar suporte
de uma projeção: utiliza-se a união dos identificadores documentais.

As categorias podem ser analisadas pelos vínculos documentais. Não se atribui
uma categoria editorial única a uma entidade com aparições em várias categorias.
As mesmas exclusões da rede de origem continuam aplicadas. Não há identidades,
autolaços, fusões adicionais de entidades ou imputação de relações faltantes.

Nomes e tipos canônicos utilizam a resolução compartilhada, retrospectiva.
Sua presença em um corte depende de evidência até aquele ano. A quantidade
de relações é uma contagem de registros retidos, não confiança semântica.

A cobertura é informada em todos os anos. Ausência de relações novas pode
decorrer de falta de extração; um patamar da série não demonstra estabilidade
do noticiário. Crescimento acumulado é consequência parcial da construção e
não comprova vantagem cumulativa. Mudanças de densidade e de protagonismo
serão examinadas posteriormente, considerando volume e cobertura.

As tabelas de projeção são persistentes. Nenhum grafo GDS é criado nesta
etapa. Não são calculados PageRank, comunidades, caminhos ou métricas
estruturais. A distância topológica posterior utiliza arestas unitárias;
distance=1/weight na projeção ponderada não é número de saltos.

Cada corte é instalado após gravação e validação, com hashes próprios.
Ao repetir a execução, os cortes compatíveis são conferidos e reutilizados.
Uma série só é publicada em atual.json depois da conclusão de todos os cortes.
O ZIP de conferência contém resumos e manifestos; não substitui as tabelas
completas preservadas nas 32 pastas anuais.
'''
