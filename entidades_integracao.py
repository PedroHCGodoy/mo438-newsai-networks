"""Integra associações documentadas de entidades às relações entre menções."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import gzip
import json
import shutil
import tempfile
import os
import time
import uuid
import zipfile
import pandas as pd
from re_consolidacao import carregar_consolidado_re, json_sha, sha, write_csv, validate_manifest
from re_execucao import atomic_json

VERSION='1.0.0'
INPUT_FILES=('associacoes_mencoes.csv.gz','registro_entidades.csv')
ASSOCIATION_COLUMNS=['mention_id','news_id','news_version_id','ner_input_sha256','ent_label','ent_text',
    'entity_group_id','entity_group_name','entity_review_required','entity_quality_status','entity_resolution_status']


def conferir_fonte(folder):
    folder=Path(folder)
    manifest=json.loads((folder/'manifesto.json').read_text(encoding='utf-8-sig'))
    if manifest.get('schema')!='er-associations-1':raise ValueError('Esquema de associações não reconhecido.')
    signature=manifest.get('input_signature','')
    if len(signature)!=64 or any(c not in '0123456789abcdef' for c in signature):raise ValueError('Assinatura de resolução inválida.')
    for name in INPUT_FILES:
        if sha(folder/name)!=manifest['outputs'].get(name):raise ValueError('Arquivo incompatível com o manifesto: '+name)
    return manifest


def registrar_associacoes(projeto, pasta_origem):
    """Importa uma versão conferida para o projeto; preserva origem e versões anteriores."""
    root=Path(projeto).resolve();source=Path(pasta_origem).resolve()
    if source.is_file():
        with tempfile.TemporaryDirectory(prefix='associacoes_') as tmp:
            staging=Path(tmp)
            with zipfile.ZipFile(source) as z:
                for name in ('manifesto.json',)+INPUT_FILES:
                    with z.open(name) as incoming,(staging/name).open('wb') as outgoing:
                        shutil.copyfileobj(incoming,outgoing,length=1024*1024)
            return registrar_associacoes(root,staging)
    meta=conferir_fonte(source)
    parent=root/'dados/processados/entidades/entradas';target=parent/meta['input_signature'][:20]
    hashes={name:sha(source/name) for name in ('manifesto.json',)+INPUT_FILES}
    parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        conferir_fonte(target)
        if any(sha(target/name)!=h for name,h in hashes.items()):raise ValueError('Mesmo identificador de resolução com arquivos diferentes.')
    else:
        temp=Path(tempfile.mkdtemp(prefix='.importando_',dir=parent))
        try:
            for name in hashes:shutil.copyfile(source/name,temp/name)
            if any(sha(temp/name)!=h or sha(source/name)!=h for name,h in hashes.items()):raise ValueError('Uma fonte mudou durante a cópia.')
            os.rename(temp,target)
        finally:
            if temp.exists():shutil.rmtree(temp)
    atomic_json(parent/'atual.json',{'folder':target.name,'resolution_signature':meta['input_signature']})
    print('[ENTIDADES] Associações registradas:',target)
    return target


def fonte_ativa(root):
    parent=Path(root)/'dados/processados/entidades/entradas'
    pointer=json.loads((parent/'atual.json').read_text(encoding='utf-8'))
    if Path(pointer['folder']).name!=pointer['folder']:raise ValueError('Apontador de associações inválido.')
    folder=parent/pointer['folder'];meta=conferir_fonte(folder)
    if meta['input_signature']!=pointer['resolution_signature']:raise ValueError('Apontador e assinatura de associações incompatíveis.')
    return folder,meta


def conferir_associacoes(root, source, meta):
    a=pd.read_csv(source/INPUT_FILES[0],dtype=str,keep_default_na=False,usecols=ASSOCIATION_COLUMNS)
    registry=pd.read_csv(source/INPUT_FILES[1],dtype=str,keep_default_na=False)
    if len(a)!=int(meta['mentions_total']) or not a.mention_id.is_unique:raise ValueError('Contagem ou unicidade de menções incompatível.')
    if not a.entity_group_id.str.fullmatch('[1-9][0-9]*').all():raise ValueError('Grupos ausentes ou IDs de grupo fora do esquema.')
    if not registry.entity_group_id.is_unique:raise ValueError('ID de grupo duplicado no registro.')
    if not registry.ent_label.isin(['PESSOA','ORGANIZACAO','LOCAL']).all():raise ValueError('Tipo de grupo fora do escopo.')
    if not a.entity_review_required.isin(['0','1']).all():raise ValueError('Marcação de inspeção desconhecida.')
    if a.entity_group_id.nunique()!=int(meta['groups_used']):raise ValueError('Número de grupos incompatível com o manifesto.')
    groups=registry.set_index('entity_group_id')
    if not a.entity_group_id.isin(groups.index).all():raise ValueError('Associação sem grupo registrado.')
    if not a.entity_group_name.eq(a.entity_group_id.map(groups.entity_group_name)).all():raise ValueError('Nome de grupo incompatível.')
    if not a.ent_label.eq(a.entity_group_id.map(groups.ent_label)).all():raise ValueError('Categoria da menção e do grupo incompatíveis.')
    byid=a.set_index('mention_id',drop=False);seen=set();total=0
    path=Path(root)/'dados/processados/ner/consolidado/mencoes_pol.csv.gz'
    fields=['mention_id','news_id','news_version_id','ner_input_sha256','ent_label','ent_text']
    for chunk in pd.read_csv(path,dtype=str,keep_default_na=False,usecols=fields,chunksize=50000):
        if chunk.mention_id.duplicated().any() or chunk.mention_id.isin(seen).any():raise ValueError('Menções NER repetidas.')
        if not chunk.mention_id.isin(byid.index).all():raise ValueError('Há menções NER sem associação; atualize a resolução antes de integrar.')
        mapped=byid.reindex(chunk.mention_id)
        for field in fields[1:]:
            if not (mapped[field].to_numpy()==chunk[field].to_numpy()).all():raise ValueError('Menção, versão ou texto incompatível com a resolução: '+field)
        seen.update(chunk.mention_id);total+=len(chunk)
    if total!=len(a):raise ValueError('A resolução contém menções ausentes do snapshot NER.')
    if int(a.entity_review_required.eq('1').sum())!=int(meta.get('review_mentions',a.entity_review_required.eq('1').sum())):
        raise ValueError('Número de marcações de inspeção incompatível.')
    return byid,groups


def anotar_relacoes(frame, byid):
    frame=frame.copy()
    for side in ['head','tail']:
        ids=frame[side+'_id']
        if not ids.isin(byid.index).all():raise ValueError('Endpoint RE sem associação de entidade.')
        mapped=byid.reindex(ids)
        for field in ['news_id','news_version_id']:
            if not (mapped[field].to_numpy()==frame[field].to_numpy()).all():raise ValueError('Endpoint e menção de outra notícia ou versão.')
        if not (mapped.ent_label.to_numpy()==frame[side+'_type'].to_numpy()).all() or not (mapped.ent_text.to_numpy()==frame[side+'_surface'].to_numpy()).all():
            raise ValueError('Superfície ou categoria de endpoint incompatível.')
        for source,dest in [('entity_group_id','entity_id'),('entity_group_name','entity_name'),
                            ('entity_review_required','entity_review_required'),('entity_resolution_status','entity_resolution_status'),
                            ('entity_quality_status','entity_quality_status')]:
            frame[side+'_'+dest]=mapped[source].to_numpy()
    same=frame.head_entity_id.eq(frame.tail_entity_id);ident=frame.label.eq('ident')
    frame['within_entity']=same
    frame['relation_role']='SEMANTIC_BETWEEN_GROUPS'
    frame.loc[~ident&same,'relation_role']='SEMANTIC_WITHIN_GROUP'
    frame.loc[ident&same,'relation_role']='IDENTITY_WITHIN_GROUP'
    frame.loc[ident&~same,'relation_role']='IDENTITY_BETWEEN_GROUPS'
    frame['entity_review_required']=frame.head_entity_review_required.eq('1')|frame.tail_entity_review_required.eq('1')
    frame['resolution_flags']=''
    frame.loc[ident&~same,'resolution_flags']='IDENTITY_BETWEEN_GROUPS'
    frame.loc[~ident&same,'resolution_flags']='SEMANTIC_WITHIN_GROUP'
    mask=frame.entity_review_required
    frame.loc[mask,'resolution_flags']=frame.loc[mask,'resolution_flags'].map(lambda s:(s+'|' if s else '')+'ENTITY_REVIEW_REQUIRED')
    return frame


def aplicar_resolucao(projeto, *, tamanho_bloco=50000):
    """Acrescenta os grupos aos endpoints sem fundir grupos, excluir triplas ou agregar pesos."""
    if not isinstance(tamanho_bloco,int) or isinstance(tamanho_bloco,bool) or tamanho_bloco<1:raise ValueError('Tamanho de bloco deve ser inteiro positivo.')
    root=Path(projeto).resolve();re_folder,re_meta=carregar_consolidado_re(root)
    source,source_meta=fonte_ativa(root)
    deps=[source/'manifesto.json',source/INPUT_FILES[0],source/INPUT_FILES[1],root/'dados/processados/ner/consolidado/mencoes_pol.csv.gz']
    hashes={str(p.relative_to(root)).replace(os.sep,'/'):sha(p) for p in deps}
    signature=json_sha({'version':VERSION,'code_sha256':sha(Path(__file__)),'inputs_sha256':hashes,
        're_snapshot_sha256':re_meta['snapshot_sha256'],'resolution_signature':source_meta['input_signature']})
    parent=root/'dados/processados/entidades/resolucao';target=parent/signature[:20]
    if target.exists():
        meta=validate_manifest(target)
        if meta.get('snapshot_sha256')!=signature:raise ValueError('Assinatura da saída incompatível.')
    else:
        started=time.monotonic();byid,groups=conferir_associacoes(root,source,source_meta)
        parent.mkdir(parents=True,exist_ok=True)
        temp=Path(tempfile.mkdtemp(prefix='.integrando_',dir=parent))
        try:
            count=0;first=True;seen=set();roles=Counter();has_re=set();has_semantic=set();flag_count=0;review_relations=0
            with (temp/'relacoes_resolvidas.csv.gz').open('wb') as raw, (temp/'diagnosticos_resolucao.csv.gz').open('wb') as araw:
                with gzip.GzipFile(fileobj=raw,mode='wb',filename='',mtime=0) as gz,gzip.GzipFile(fileobj=araw,mode='wb',filename='',mtime=0) as az:
                    for chunk in pd.read_csv(re_folder/'relacoes_mencoes.csv.gz',dtype=str,keep_default_na=False,chunksize=tamanho_bloco):
                        if chunk.relation_id.duplicated().any() or chunk.relation_id.isin(seen).any():raise ValueError('Relações repetidas na entrada.')
                        seen.update(chunk.relation_id)
                        resolved=anotar_relacoes(chunk,byid)
                        resolved.to_csv(gz,index=False,header=first,encoding='utf-8',lineterminator='\n')
                        flagged=resolved.loc[resolved.resolution_flags.ne('')]
                        flagged.to_csv(az,index=False,header=first,encoding='utf-8',lineterminator='\n')
                        first=False;count+=len(resolved);roles.update(resolved.relation_role)
                        flag_count+=len(flagged);review_relations+=int(resolved.entity_review_required.sum())
                        has_re.update(resolved.head_entity_id);has_re.update(resolved.tail_entity_id)
                        semantic=resolved.loc[resolved.label.ne('ident')]
                        has_semantic.update(semantic.head_entity_id);has_semantic.update(semantic.tail_entity_id)
            if count!=int(re_meta['summary']['relations']):raise ValueError('Perda de relações durante a integração.')
            if not count:raise ValueError('A consolidação selecionada não possui relações; nenhum snapshot foi ativado.')
            entities=groups.loc[groups.index.isin(set(byid.entity_group_id))].copy()
            entities['mention_count']=entities.index.map(byid.groupby('entity_group_id').size()).astype(int)
            entities['news_count']=entities.index.map(byid.groupby('entity_group_id').news_id.nunique()).astype(int)
            reviewed=byid.loc[byid.entity_review_required.eq('1')].groupby('entity_group_id').size()
            entities['review_mention_count']=entities.index.map(reviewed).fillna(0).astype(int)
            entities['has_re_evidence']=entities.index.isin(has_re)
            entities['has_semantic_re_evidence']=entities.index.isin(has_semantic)
            entities=entities.reset_index().sort_values('entity_group_id',key=lambda s:pd.to_numeric(s))
            write_csv(temp,'entidades.csv.gz',entities)
            # A tabela completa e suas marcas de proveniência permanecem idênticas à fonte.
            shutil.copyfile(source/INPUT_FILES[0],temp/'mencoes_resolvidas.csv.gz')
            counts=pd.DataFrame([{'relation_role':k,'relations':roles[k]} for k in sorted(roles)])
            write_csv(temp,'diagnosticos_por_tipo.csv',counts)
            write_csv(temp,'grupos_por_categoria.csv',entities.groupby('ent_label',sort=True).agg(groups=('entity_group_id','size'),mentions=('mention_count','sum'),review_mentions=('review_mention_count','sum')).reset_index())
            write_csv(temp,'metodos_associacao.csv',byid.groupby('entity_resolution_status',sort=True).size().reset_index(name='mentions'))
            summary={'mentions':len(byid),'groups':len(entities),'review_mentions':int(byid.entity_review_required.eq('1').sum()),
                'relations_preserved':count,'relation_roles':dict(roles),'groups_in_re':len(has_re),'groups_in_semantic_re':len(has_semantic),
                'relations_with_resolution_flags':flag_count,'relations_touching_review_mentions':review_relations,
                'groups_merged':0,'relations_removed':0,'weights_aggregated':False,'api_calls':0,'embeddings_generated':0}
            readme=('INTEGRAÇÃO DE ENTIDADES\n\n'+json.dumps(summary,ensure_ascii=False,indent=2)+
                '\n\nTodos os grupos e suas marcações são preservados. Cobertura de IDs não equivale a validação semântica.\n'+
                'Os registros são evidências entre menções com endpoints resolvidos; ainda não são arestas agregadas.\n'+
                'Identidades entre grupos diferentes e relações semânticas dentro de um grupo são diagnósticos, não decisões automáticas.\n')
            (temp/'LEIA_ME.txt').write_text(readme,encoding='utf-8')
            meta={'schema':'entity-integration-1','version':VERSION,'snapshot_sha256':signature,
                're_snapshot_sha256':re_meta['snapshot_sha256'],'resolution_signature':source_meta['input_signature'],
                'created_at_utc':datetime.now(timezone.utc).isoformat(),'elapsed_s':round(time.monotonic()-started,3),
                'code_sha256':sha(Path(__file__)),'inputs_sha256':hashes,'summary':summary,
                'outputs_sha256':{p.name:sha(p) for p in sorted(temp.iterdir())}}
            atomic_json(temp/'manifesto.json',meta)
            if carregar_consolidado_re(root)[1]['snapshot_sha256']!=re_meta['snapshot_sha256'] or fonte_ativa(root)[1]['input_signature']!=source_meta['input_signature']:
                raise ValueError('Uma versão ativa mudou durante a integração.')
            if any(sha(root/name)!=h for name,h in hashes.items()):raise ValueError('As entradas mudaram durante a integração.')
            os.rename(temp,target)
        finally:
            if temp.exists():shutil.rmtree(temp)
    atomic_json(parent/'atual.json',{'folder':target.name,'snapshot_sha256':signature})
    output=root/'resultados/entidades';output.mkdir(parents=True,exist_ok=True)
    package=output/f'Resumo_Integracao_Entidades_{signature[:12]}_{uuid.uuid4().hex[:6]}.zip'
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(target.iterdir()):
            if p.name not in ['relacoes_resolvidas.csv.gz','mencoes_resolvidas.csv.gz','entidades.csv.gz']:z.write(p,p.name)
    print('[ENTIDADES] '+json.dumps(meta['summary'],ensure_ascii=False))
    print('[ENTIDADES] Saídas:',target)
    print('[ENTIDADES] Pacote:',package)
    return {**meta['summary'],'output_directory':target,'package':package,'snapshot_sha256':signature}


def carregar_entidades_integradas(projeto):
    """Bloqueia o uso de associações ou relações posteriores ao snapshot selecionado."""
    root=Path(projeto).resolve();parent=root/'dados/processados/entidades/resolucao'
    pointer=json.loads((parent/'atual.json').read_text(encoding='utf-8'))
    if Path(pointer['folder']).name!=pointer['folder']:raise ValueError('Apontador de entidades inválido.')
    folder=parent/pointer['folder'];meta=validate_manifest(folder)
    if meta['snapshot_sha256']!=pointer['snapshot_sha256']:raise ValueError('Apontador e manifesto incompatíveis.')
    if carregar_consolidado_re(root)[1]['snapshot_sha256']!=meta['re_snapshot_sha256']:
        raise ValueError('Há uma nova consolidação RE. Execute a seção 27 antes de atualizar as análises.')
    if fonte_ativa(root)[1]['input_signature']!=meta['resolution_signature'] or any(sha(root/name)!=h for name,h in meta['inputs_sha256'].items()):
        raise ValueError('As associações ou o NER mudaram. Atualize a integração de entidades.')
    return folder,meta
