"""Testes de agregação, proveniência e versionamento com evidências sintéticas."""
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import redirect_stdout
from unittest.mock import patch
import io
import json
import unittest
import pandas as pd
import redes_construcao as r


def fixture():
    news = pd.DataFrame([dict(news_id=f'n{i}', news_version_id=f'v{i}', title=f'Notícia {i}',
        link=f'https://example.org/{i}', author='Autoria sintética', source='Fonte A' if i==1 else 'Fonte B',
        publication_date=f'202{i}-01-01', publication_date_precision='second', publication_year=f'202{i}',
        category_raw='Editorial', category_grouped='Tecnologia' if i==1 else 'Economia',
        category_mapping_status='MAPPED') for i in range(1,4)])
    registry = pd.DataFrame([dict(entity_group_id=i, entity_group_name=name, ent_label=label)
        for i,name,label in [('1','Ana','PESSOA'),('2','Empresa','ORGANIZACAO'),('3','G1','ORGANIZACAO')]])
    mentions = pd.DataFrame([dict(mention_id=f'm{i}-{group}-{j}', news_id=f'n{i}', news_version_id=f'v{i}',
        entity_group_id=group, entity_group_name='Ana' if group=='1' else ('Empresa' if group=='2' else 'G1'),
        ent_label='PESSOA' if group=='1' else 'ORGANIZACAO', ent_text='Ana' if group=='1' else 'Empresa',
        entity_review_required='1' if i==3 and group=='1' else '0',
        entity_resolution_status='EXISTING_ASSOCIATION', entity_quality_status='ACCEPTED')
        for i in range(1,4) for group in ['1','2','3'] for j in range(1,3)])
    rows = [('n1','1','2','vinculo_inst'),('n1','1','2','vinculo_inst'),
            ('n2','1','2','vinculo_inst'),('n2','2','1','vinculo_inst'),
            ('n2','1','2','inclui'),('n1','3','3','ident'),
            ('n1','1','1','vinculo_inst'),('n1','1','3','vinculo_inst')]
    relations = pd.DataFrame([dict(relation_id=f'r{j}',news_id=news_id,news_version_id='v'+news_id[1:],
        head_id=f'm{news_id[1:]}-{a}-{2 if j==1 else 1}',tail_id=f'm{news_id[1:]}-{b}-1',
        head_entity_id=a,tail_entity_id=b,label=label,technical_provisional='False',semantic_status='ACCEPTED',
        semantic_flags='',resolution_flags='',entity_review_required='False')
        for j,(news_id,a,b,label) in enumerate(rows)])
    coverage = news[['news_id','news_version_id']].copy()
    coverage['ner_availability']='AVAILABLE';coverage['re_state']=['SUCCESS','SUCCESS','PENDING']
    coverage['origin']='synthetic';coverage['technical_provisional']='False'
    return news,mentions,registry,relations,coverage


class TablesTests(unittest.TestCase):
    def test_weight_news_support_and_direction(self):
        frames,summary=r.agregar_tabelas(*fixture())
        edges=frames['arestas.csv.gz']
        edge=edges.loc[edges.source_id.eq('1') & edges.target_id.eq('2') & edges.label.eq('vinculo_inst')].iloc[0]
        self.assertEqual(edge.weight,3);self.assertEqual(edge.distinct_news_count,2)
        self.assertEqual(summary['edges'],3);self.assertEqual(summary['weight_sum'],5)
        self.assertEqual(summary['exclusive_exclusion_reasons'],{'IDENTITY':1,'SELF_LOOP':1,'CORPUS_SOURCE':1})
        exclusions=frames['relacoes_excluidas.csv.gz']
        overlap=exclusions.loc[exclusions.label.eq('ident')].iloc[0]
        self.assertTrue(overlap.excluded_self_loop and overlap.excluded_corpus_source)
        self.assertFalse(edges.label.eq('ident').any());self.assertFalse(edges.source_id.eq(edges.target_id).any())
    def test_ner_and_re_counts_are_distinct(self):
        f,_=r.agregar_tabelas(*fixture())
        n=f['nos.csv.gz'].set_index('entity_group_id').loc['1']
        self.assertEqual(n.distinct_news_count,3);self.assertEqual(n.relation_news_count,2)
        self.assertEqual(n.mention_count,6);self.assertTrue(n.entity_review_required)
        self.assertEqual(n.first_observed_date,'2021-01-01');self.assertEqual(n.last_observed_date,'2023-01-01')
        self.assertEqual(set(f['nos_noticias.csv.gz'].news_id),{'n1','n2','n3'})
        self.assertNotIn('3',set(f['nos.csv.gz'].entity_group_id))
    def test_distributions_reconcile(self):
        f,_=r.agregar_tabelas(*fixture())
        for name,total in [('distribuicoes_arestas.csv.gz',5),('distribuicoes_nos.csv.gz',12)]:
            for _,part in f[name].groupby('dimension'):self.assertEqual(part['count'].sum(),total)
        self.assertEqual(len(f['arestas_noticias.csv.gz']),4)
    def test_duplicate_missing_or_wrong_version_blocked(self):
        for mode in ['duplicate','missing_group','version','label']:
            data=list(fixture())
            if mode=='duplicate':data[3]=pd.concat([data[3],data[3].head(1)])
            if mode=='missing_group':data[2]=data[2].iloc[:1]
            if mode=='version':data[3].loc[0,'news_version_id']='different'
            if mode=='label':data[3].loc[0,'label']='unknown'
            with self.subTest(mode=mode), self.assertRaises(ValueError):r.agregar_tabelas(*data)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.source=self.root/'input_entities';self.source.mkdir()
        self.re_source=self.root/'input_re';self.re_source.mkdir()
        news,m,registry,relations,coverage=fixture()
        prepared=self.root/'dados/processados';prepared.mkdir(parents=True)
        news.rename(columns={'source':'source_normalized','publication_date':'publication_date_normalized'}).to_csv(
            prepared/'noticias_preparadas.csv',index=False)
        for name,frame in [('mencoes_resolvidas.csv.gz',m),('entidades.csv.gz',registry),('relacoes_resolvidas.csv.gz',relations)]:
            r.write_csv(self.source,name,frame)
        r.write_csv(self.re_source,'cobertura_documental.csv',coverage)
        self.parent={'snapshot_sha256':'a'*64}
        self.addCleanup(patch.stopall)
        patch.object(r,'carregar_entidades_integradas',side_effect=lambda _: (self.source,self.parent.copy())).start()
        patch.object(r,'carregar_consolidado_re',return_value=(self.re_source,{'snapshot_sha256':'b'*64})).start()
        self.quiet=redirect_stdout(io.StringIO());self.quiet.__enter__();self.addCleanup(self.quiet.__exit__,None,None,None)
    def test_idempotent_and_complete_news_lookup(self):
        one=r.construir_rede(self.root);two=r.construir_rede(self.root)
        self.assertEqual(one['snapshot_sha256'],two['snapshot_sha256'])
        links=r.consultar_noticias(self.root,entity_id='1')
        self.assertEqual(len(links),3);self.assertTrue(links.link.str.startswith('https://').all())
        self.assertEqual(len(r.consultar_noticias(self.root,entity_id='1',somente_relacoes=True)),2)
        edges=r._read(one['output_directory']/'arestas.csv.gz')
        row=edges.loc[edges.source_id.eq('1') & edges.label.eq('vinculo_inst')].iloc[0]
        self.assertEqual(len(r.consultar_noticias(self.root,edge_id=row.edge_id)),2)
    def test_new_inputs_preserve_old_and_block_stale(self):
        one=r.construir_rede(self.root);old=r.sha(one['output_directory']/'arestas.csv.gz')
        self.parent['snapshot_sha256']='c'*64
        with self.assertRaises(ValueError):r.carregar_rede(self.root)
        two=r.construir_rede(self.root)
        self.assertNotEqual(one['snapshot_sha256'],two['snapshot_sha256'])
        self.assertEqual(r.sha(one['output_directory']/'arestas.csv.gz'),old)
    def test_scope_recomputes_counts_and_ids_remain_stable(self):
        one=r.construir_rede(self.root)
        old=r._read(one['output_directory']/'arestas.csv.gz')
        two=r.construir_rede(self.root,anos=[2021])
        now=r._read(two['output_directory']/'arestas.csv.gz')
        self.assertEqual(len(now),1);self.assertEqual(now.iloc[0].weight,'2')
        self.assertIn(now.iloc[0].edge_id,set(old.edge_id))
        self.assertEqual(len(r.consultar_noticias(self.root,entity_id='1')),1)
    def test_pin_and_tampering_blocked(self):
        with self.assertRaises(ValueError):r.construir_rede(self.root,assinatura_entidades_esperada='wrong')
        one=r.construir_rede(self.root)
        with (one['output_directory']/'arestas.csv.gz').open('ab') as f:f.write(b'corruption')
        with self.assertRaises(ValueError):r.carregar_rede(self.root)


if __name__=='__main__':unittest.main()
