"""Verificações de proveniência, contagens, recortes e HTML autocontido."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from comunidades_visualizacao import (noticias_comunidades,caracterizar_suporte,selecionar_vista,
    json_seguro,layout_vista,preparar_grafo,pagina_html,figuras_grafo,gerar_visualizacoes,reexportar_figuras,limpar_saidas_anteriores)


def entradas():
    nodes=pd.DataFrame({'run_id':['louvain']*4,'entity_group_id':[0,1,2,3],
        'community_id':[0,0,2,2],'entity_group_name':['Mesmo nome','Mesmo nome','C','D'],
        'ent_label':['PESSOA','ORGANIZACAO','LOCAL','PESSOA'],'neighbor_degree':[2,1,2,1],
        'weighted_strength':[5,3,3,1],'pagerank':[1,1,1,1]})
    edges=pd.DataFrame({'edge_id':['a','b','c','d'],'source_id':[0,0,2,0],'target_id':[1,2,3,1],
                        'weight':[2,2,1,1],'label':['vinculo_inst','localizado_em','vinculo_inst','outra']})
    evidence=pd.DataFrame({'edge_id':['a','b','c','d'],'news_id':['n1','n1','n2','n1'],'news_version_id':['v1','v1','v2','v1']})
    news=pd.DataFrame({'news_id':['n1','n2'],'news_version_id':['v1','v2'],'title':['Notícia 1','Notícia 2'],
        'link':['https://example.org/1','https://example.org/2'],'source':['G1','CNN Brasil'],
        'publication_date':['2020-01-01','2021-01-01'],'publication_year':[2020,2021],
        'category_grouped':['ECONOMIA','CIENCIA'],'author':['Autor 1','Autor 2']})
    stats=pd.DataFrame({'run_id':['louvain']*2,'community_id':[0,2],'nodes':[2,2],'connected_pieces':[1,1]})
    return nodes,edges,evidence,news,stats


class VisualizacoesTests(unittest.TestCase):
    def test_news_union_and_overlap(self):
        nodes,edges,evidence,news,stats=entradas()
        support=noticias_comunidades(nodes,edges,evidence,news)
        metrics,profiles=caracterizar_suporte(support,stats)
        self.assertEqual(len(support),3)
        self.assertEqual(metrics.any_news.tolist(),[1,2])
        self.assertEqual(metrics.internal_news.tolist(),[1,1])
        self.assertEqual(metrics.boundary_news.tolist(),[1,1])
        self.assertEqual(len(profiles.loc[profiles.scope.eq('internal')&profiles.dimension.eq('source')]),2)

    def test_unknown_version_fails(self):
        nodes,edges,evidence,news,_=entradas();evidence.loc[0,'news_version_id']='changed'
        with self.assertRaises(ValueError):noticias_comunidades(nodes,edges,evidence,news)

    def test_pair_aggregation_preserves_ids_and_labels(self):
        nodes,edges,*_=entradas()
        selected,pairs,directed,detail=selecionar_vista(nodes,edges,community_id=0,max_nodes=10,max_edges=10)
        self.assertEqual(len(selected),2)
        self.assertEqual(selected.entity_group_name.nunique(),1)
        self.assertEqual(len(pairs),1)
        self.assertEqual(pairs.weight.iloc[0],3)
        self.assertEqual(pairs.typed_edge_ids.iloc[0],['a','d'])
        self.assertEqual(len(pairs.labels.iloc[0]),2)

    def test_limits_do_not_change_full_scope(self):
        nodes,edges,*_=entradas()
        selected,pairs,directed,detail=selecionar_vista(nodes,edges,max_nodes=2,max_edges=1)
        self.assertEqual(len(selected),2);self.assertLessEqual(len(pairs),1)
        self.assertEqual(detail['full_nodes'],4)
        self.assertEqual(detail['full_typed_edges'],4)

    def test_json_embedded_safely(self):
        value={'text':'</script><img src=x onerror="bad()"> & \u2028'}
        encoded=json_seguro(value)
        self.assertNotIn('</script>',encoded)
        self.assertNotIn('<img',encoded)
        self.assertEqual(json.loads(encoded),value)

    def test_graph_html_and_figures(self):
        nodes,edges,*_=entradas();selected,pairs,directed,_=selecionar_vista(nodes,edges)
        positions=layout_vista(selected,pairs)
        payload=preparar_grafo(selected,pairs,directed,positions=positions,node_news={},edge_news={},news_lookup={},scope_news=[],selection_note='Teste')
        self.assertTrue(all(e.get('arrows','')=='' for e in payload['graph']['edges']))
        self.assertTrue(all(e['arrows']=='to' for e in payload['semantic_edges']))
        self.assertEqual(payload['default_color_mode'],'community')
        content=pagina_html(payload,title='Teste',note='Recorte de teste',graph=True)
        self.assertIn('vis-network',content)
        self.assertIn('Lista completa de notícias',content)
        self.assertNotIn('<script src=',content)
        self.assertNotIn('<link ',content)
        with tempfile.TemporaryDirectory() as directory:
            figuras_grafo(Path(directory),'teste',selected,pairs,positions,'Teste')
            self.assertEqual(len(list(Path(directory).iterdir())),3)

    def test_dry_run_no_files_or_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('comunidades_visualizacao.carregar_comunidades',return_value=(None,{'reference_leiden':'leiden_seed_42'})), \
                 patch('comunidades_visualizacao.carregar_rede',return_value=(None,{'snapshot_sha256':'n','summary':{'nodes':4}})):
                result=gerar_visualizacoes(directory)
                self.assertEqual(result['neo4j_connections'],0)
                self.assertEqual(list(Path(directory).iterdir()),[])
                with self.assertRaises(ValueError):gerar_visualizacoes(directory,max_nos=0)

    def test_reexport_reads_saved_positions_without_scientific_loaders(self):
        import hashlib
        nodes,edges,*_=entradas();selected,pairs,directed,_=selecionar_vista(nodes,edges)
        positions=layout_vista(selected,pairs)
        selected['layout_x']=[positions[i][0] for i in selected.entity_group_id]
        selected['layout_y']=[positions[i][1] for i in selected.entity_group_id]
        selected['view_id']='vista';pairs['view_id']='vista'
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)/'resultados/visualizacoes';source=base/'original';source.mkdir(parents=True)
            selected.to_csv(source/'nos_exibidos.csv.gz',index=False);pairs.to_csv(source/'pares_exibidos.csv.gz',index=False)
            pd.DataFrame({'view_id':['vista']}).to_csv(source/'catalogo_visualizacoes.csv',index=False)
            pd.DataFrame({'run_id':[]}).to_csv(source/'caracterizacao_comunidades.csv.gz',index=False)
            pd.DataFrame({'run_id':[],'value':[]}).to_csv(source/'distribuicoes_editoriais.csv.gz',index=False)
            hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
            (source/'manifesto.json').write_text(json.dumps({'snapshot_sha256':'v','partitions':[],'outputs_sha256':hashes}))
            (base/'atual.json').write_text(json.dumps({'folder':'original','snapshot_sha256':'v'}))
            with patch('comunidades_visualizacao.carregar_rede',side_effect=AssertionError('scientific reload')), \
                 patch('comunidades_visualizacao.carregar_comunidades',side_effect=AssertionError('scientific reload')):
                result=reexportar_figuras(directory,tamanho_fonte=12,max_rotulos=2)
            self.assertEqual(result['scientific_recomputations'],0)
            self.assertEqual(len(list(result['output_directory'].glob('*.png'))),1)
            for name,expected in hashes.items():self.assertEqual(hashlib.sha256((source/name).read_bytes()).hexdigest(),expected)

    def test_reciprocal_pairs_use_projection_weights(self):
        nodes,edges,*_=entradas()
        reverse=pd.DataFrame({'edge_id':['r'],'source_id':[1],'target_id':[0],'weight':[7],'label':['proprietario_de']})
        selected,pairs,directed,detail=selecionar_vista(nodes,pd.concat([edges,reverse],ignore_index=True),community_id=0)
        self.assertEqual(len(pairs),1);self.assertEqual(pairs.weight.iloc[0],10)
        self.assertEqual(len(directed),2);self.assertEqual(sorted(directed.weight),[3,7])
        self.assertEqual(pairs.typed_edge_ids.iloc[0],['a','d','r'])
        self.assertEqual(detail['displayed_undirected_pairs'],1)
        self.assertEqual(detail['inspection_directed_pairs'],2)


def owned_folder(base,name,schema):
    import hashlib
    folder=base/name;folder.mkdir(parents=True)
    (folder/'saida.txt').write_text('output')
    meta={'schema':schema,'snapshot_sha256':name,'outputs_sha256':{'saida.txt':hashlib.sha256((folder/'saida.txt').read_bytes()).hexdigest()}}
    (folder/'manifesto.json').write_text(json.dumps(meta));return folder


def owned_zip(base,name,folder):
    import zipfile
    target=base/name
    with zipfile.ZipFile(target,'w') as z:
        for p in folder.iterdir():z.write(p,p.name)
    return target


class LimpezaTests(unittest.TestCase):
    def setup_outputs(self,directory):
        root=Path(directory);base=root/'resultados/visualizacoes';base.mkdir(parents=True)
        current=owned_folder(base,'b'*20,'community-evidence-visualization-2')
        old=owned_folder(base,'a'*20,'community-evidence-visualization-1')
        package=owned_zip(base,'Resumo_Visualizacoes_bbbbbbbbbbbb_111111.zip',current)
        return root,base,current,old,package

    def test_removes_only_recognized_previous_visualizations(self):
        with tempfile.TemporaryDirectory() as directory:
            root,base,current,old,package=self.setup_outputs(directory)
            prior=owned_zip(base,'Resumo_Visualizacoes_aaaaaaaaaaaa_222222.zip',old)
            edition=owned_folder(base/'edicoes_figuras','c'*20,'static-figure-edition-1')
            protected=root/'dados/processados';protected.mkdir(parents=True);(protected/'cientifico.csv').write_text('keep')
            result=limpar_saidas_anteriores(base,current,package)
            self.assertFalse(old.exists());self.assertFalse(prior.exists());self.assertFalse(edition.exists())
            self.assertTrue(current.exists());self.assertTrue(package.exists());self.assertTrue((protected/'cientifico.csv').exists())
            self.assertEqual(result['status'],'COMPLETE')

    def test_invalid_current_package_aborts_before_deletion(self):
        import zipfile
        with tempfile.TemporaryDirectory() as directory:
            _,base,current,old,package=self.setup_outputs(directory)
            package.write_bytes(b'corrupt')
            with self.assertRaises(zipfile.BadZipFile):limpar_saidas_anteriores(base,current,package)
            self.assertTrue(old.exists());self.assertTrue(current.exists())

    def test_preserves_unknown_files_and_modified_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            _,base,current,old,package=self.setup_outputs(directory)
            (old/'anotacao_usuario.txt').write_text('keep')
            unknown=base/'manual.html';unknown.write_text('keep')
            result=limpar_saidas_anteriores(base,current,package)
            self.assertTrue(old.exists());self.assertTrue(unknown.exists())
            self.assertEqual(result['status'],'REVIEW_REMAINING')

    def test_rejects_cleanup_outside_visualization_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root,base,current,old,package=self.setup_outputs(directory)
            with self.assertRaises(ValueError):limpar_saidas_anteriores(root,current,package)
            self.assertTrue(old.exists())


if __name__=='__main__':unittest.main(verbosity=2)
