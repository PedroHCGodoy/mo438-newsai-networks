"""Verificações de seleção visual, conectividade e ausência de efeitos no modo de conferência."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pandas as pd
import fontes_visualizacao as r


class VistasFontesTests(unittest.TestCase):
    def test_flagged_communities_included_without_duplicates(self):
        metrics=pd.DataFrame({'run_id':['louvain']*3,'community_id':[1,2,3],
            'nodes':[100,50,10],'connected_pieces':[1,2,2]})
        self.assertEqual(r.selecionar_comunidades(metrics,'louvain',2),[1,2,3])

    def test_induced_connectivity_ignores_external_path(self):
        assignments=pd.DataFrame({'run_id':['louvain']*3,'community_id':[1,1,3],
            'entity_group_id':[1,2,3],'entity_group_name':['A','B','C'],'ent_label':['PESSOA']*3})
        stats=pd.DataFrame({'run_id':['louvain'],'community_id':[1],'connected_pieces':[2]})
        pairs=pd.DataFrame({'source_id':[1,3],'target_id':[3,2]})
        members,summary=r.inspecionar_partes(assignments,stats,pairs)
        self.assertEqual(summary.iloc[0].connected_pieces,2)
        self.assertEqual(set(members.piece_id),{1,2})
        self.assertEqual(set(members.entity_group_id),{1,2})

    def test_wrong_connectivity_rejected(self):
        a=pd.DataFrame({'run_id':['louvain']*2,'community_id':[1,1],
            'entity_group_id':[1,2],'entity_group_name':['A','B'],'ent_label':['PESSOA']*2})
        s=pd.DataFrame({'run_id':['louvain'],'community_id':[1],'connected_pieces':[2]})
        with self.assertRaises(ValueError):r.inspecionar_partes(a,s,pd.DataFrame({'source_id':[1],'target_id':[2]}))

    def test_home_link_and_local_pagerank_heading(self):
        with patch.object(r.vis,'pagina_html',return_value='<a href="indice_comunidades.html">Painel</a><th>Destaques por PageRank global</th>'):
            out=r.pagina({},'Título','Nota','g1_indice_comunidades.html')
        self.assertIn('href="g1_indice_comunidades.html"',out)
        self.assertIn('PageRank da fonte',out)

    def test_dry_run_no_files_or_connection(self):
        with TemporaryDirectory() as temp,patch.object(r,'carregar_fontes',return_value=(Path(temp),{})),patch.object(r,'carregar_particoes',return_value=(Path(temp),{'reference_leiden':'leiden_seed_42'})):
            out=r.gerar_visualizacoes_fontes(temp)
            self.assertTrue(out['include_all_flagged_communities'])
            self.assertEqual(out['neo4j_connections'],0)
            self.assertEqual(list(Path(temp).iterdir()),[])

    def test_invalid_limits_rejected(self):
        with patch.object(r,'carregar_fontes',return_value=(Path('.'),{})),patch.object(r,'carregar_particoes',return_value=(Path('.'),{'reference_leiden':'leiden_seed_42'})):
            with self.assertRaises(ValueError):r.gerar_visualizacoes_fontes('.',max_nos=0)


if __name__=='__main__':unittest.main(verbosity=2)
