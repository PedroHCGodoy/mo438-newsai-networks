import unittest
import numpy as np
import pandas as pd
from scipy.stats import lognorm
from revisao_pendencias import connectivity,bfs_parts,lognormal_logpmf

class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.nodes=pd.DataFrame({'entity_group_id':[10,11,12,13,20,21],'community_id':[1,1,1,1,2,2]})
        self.pairs=pd.DataFrame({'source_id':[10,12,20],'target_id':[11,13,21],'weight':[1,2,3]})
    def test_detect_disconnected_and_recompute_q(self):
        f,s=connectivity(self.nodes,self.pairs)
        self.assertEqual(s['disconnected_communities'],1)
        self.assertEqual(f.groupby('community_id').independent_piece_id.nunique().tolist(),[2,1])
        self.assertAlmostEqual(s['weighted_modularity_independent'],.5)
    def test_bfs_reference_preserves_isolates(self):
        p=bfs_parts([10,11,12,13,99],self.pairs)
        self.assertEqual(p,{10:10,11:10,12:12,13:12,99:99})
    def test_duplicate_or_missing_nodes_rejected(self):
        with self.assertRaises(ValueError):connectivity(pd.concat([self.nodes,self.nodes.iloc[:1]]),self.pairs)
        with self.assertRaises(ValueError):connectivity(self.nodes.iloc[:-1],self.pairs)
    def test_invalid_edges_rejected(self):
        with self.assertRaises(ValueError):connectivity(self.nodes,pd.concat([self.pairs,self.pairs.iloc[:1]]))
        p=self.pairs.copy();p.loc[0,'weight']=0
        with self.assertRaises(ValueError):connectivity(self.nodes,p)
    def test_stable_lognormal_against_regular_reference(self):
        x=np.arange(3,20,dtype=float);mu=1.;sigma=2.
        ref=(lognorm.cdf(x+.5,sigma,scale=np.exp(mu))-lognorm.cdf(x-.5,sigma,scale=np.exp(mu)))/lognorm.sf(2.5,sigma,scale=np.exp(mu))
        np.testing.assert_allclose(lognormal_logpmf(x,mu,sigma,3),np.log(ref),rtol=1e-10)
    def test_extreme_saved_parameters_finite(self):
        x=np.array([3.,10.,100.,1000.]);p=lognormal_logpmf(x,-804.441490016917,21.48115390809859,3)
        self.assertTrue(np.isfinite(p).all());self.assertTrue((p<0).all())
        self.assertTrue((np.diff(p)<0).all())

if __name__=='__main__':unittest.main(verbosity=2)
