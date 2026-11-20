"""Verificações de partições, universo comum e retomada por checkpoint."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pandas as pd
import fontes_comunidades as r


class ComunidadesFontesTests(unittest.TestCase):
    def test_cross_source_uses_only_shared_nodes(self):
        a=pd.DataFrame({'entity_group_id':[1,2,3],'community_id':[10,10,20]})
        b=pd.DataFrame({'entity_group_id':[2,3,4],'community_id':[50,60,60]})
        cross,matches=r.comparar_fontes({'cnn':{'louvain':a},'g1':{'louvain':b}},['louvain'])
        self.assertEqual(cross.iloc[0].common_nodes,2)
        self.assertAlmostEqual(cross.iloc[0].ari,1)
        self.assertTrue(matches.jaccard.eq(.5).all())

    def test_no_shared_nodes_is_not_perfect_agreement(self):
        a=pd.DataFrame({'entity_group_id':[1],'community_id':[1]})
        b=pd.DataFrame({'entity_group_id':[2],'community_id':[2]})
        cross,matches=r.comparar_fontes({'cnn':{'louvain':a},'g1':{'louvain':b}},['louvain'])
        self.assertIsNone(cross.iloc[0].ari)
        self.assertTrue(matches.empty)

    def test_checkpoint_and_configuration_guard(self):
        raw=pd.DataFrame({'entity_group_id':[1,2,3],'community_id':[5,5,6]})
        p=r.canonizar_particao(raw,[1,2,3]);definition=r.configuracoes([42])['louvain']
        with TemporaryDirectory() as temp:
            folder=Path(temp)/'louvain'
            r.salvar_checkpoint(folder,'a'*64,definition,p,{'gds_version':'test'})
            actual,execution=r.carregar_checkpoint(folder,'a'*64,definition,[1,2,3])
            pd.testing.assert_frame_equal(actual,p)
            with self.assertRaises(ValueError):r.carregar_checkpoint(folder,'b'*64,definition,[1,2,3])

    def test_partition_missing_node_rejected(self):
        with self.assertRaises(ValueError):
            r.canonizar_particao(pd.DataFrame({'entity_group_id':[1],'community_id':[1]}),[1,2])

    def test_disconnected_community_flag_preserves_assignment(self):
        nodes=pd.DataFrame({'entity_group_id':[1,2,3,4],'ent_label':['PESSOA']*4,
            'component_id':[1,1,3,3],'pagerank':[1.,1.,1.,1.]})
        pairs=pd.DataFrame({'source_id':[1,3],'target_id':[2,4],'weight':[1,1]})
        p=r.canonizar_particao(pd.DataFrame({'entity_group_id':[1,2,3,4],'community_id':[9]*4}),nodes.entity_group_id)
        f,s,t,summary=r.avaliar_particao(nodes,pairs,p,gcc_component_id=1)
        self.assertEqual(summary['disconnected_communities'],1)
        self.assertEqual(summary['communities_spanning_original_components'],1)
        self.assertEqual(f.community_id.nunique(),1)

    def test_dry_run_no_files_or_connection(self):
        with TemporaryDirectory() as temp,patch.object(r,'carregar_fontes',return_value=(Path(temp),{})),patch.object(r,'carregar_estrutura_fontes',return_value=(Path(temp),{})),patch.object(r,'carregar_protagonismo',return_value=(Path(temp),{})):
            out=r.detectar_comunidades_fontes(temp)
            self.assertEqual(len(out['runs']),4)
            self.assertEqual(out['maximum_owned_projections'],1)
            self.assertEqual(list(Path(temp).iterdir()),[])


if __name__=='__main__':unittest.main(verbosity=2)
