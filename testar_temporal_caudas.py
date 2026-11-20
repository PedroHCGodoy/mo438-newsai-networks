"""Verificações matemáticas e de reprodução do diagnóstico de caudas."""
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch
import numpy as np
import temporal_caudas as r


class CaudasTests(unittest.TestCase):
    def test_gini_matches_pairwise_definition(self):
        x=np.array([1,1,4]);expected=np.abs(x[:,None]-x).sum()/(2*len(x)*x.sum())
        self.assertAlmostEqual(r.concentracao(x)['gini_degree'],expected)
        self.assertAlmostEqual(r.concentracao([2,2,2])['gini_degree'],0)

    def test_top_groups_are_nested_and_use_ceil(self):
        d=r.concentracao(np.arange(1,102))
        self.assertEqual(d['top_1pct_nodes'],2)
        self.assertLessEqual(d['top_1pct_degree_share'],d['top_5pct_degree_share'])
        self.assertLessEqual(d['top_5pct_degree_share'],d['top_10pct_degree_share'])

    def test_invalid_degree_arrays_rejected(self):
        for data in [[],[0,1],[1,2.5],[np.nan],[-1,2]]:
            with self.assertRaises(ValueError):r.validar_graus(data)

    def test_discrete_mle_is_local_likelihood_maximum(self):
        from scipy.special import zeta
        x=np.random.default_rng(18).zipf(2.5,600)
        fit,s,_=r.ajustar(x);tail=x[x>=s['xmin']]
        def ll(alpha):return -alpha*np.log(tail).sum()-len(tail)*np.log(zeta(alpha,s['xmin']))
        self.assertGreaterEqual(ll(s['alpha']),ll(s['alpha']-.01))
        self.assertGreaterEqual(ll(s['alpha']),ll(s['alpha']+.01))
        self.assertEqual(fit.estimate_discrete,False)

    def test_bootstrap_checkpoint_and_external_random_state(self):
        x=np.random.default_rng(11).zipf(2.5,300);fit,_,_=r.ajustar(x)
        before=np.random.get_state()
        with TemporaryDirectory() as td:
            first,a=r.bootstrap(x,fit,repeticoes=3,seed=42,folder=td)
            second,b=r.bootstrap(x,fit,repeticoes=3,seed=42,folder=td)
            self.assertEqual(a,b)
            self.assertTrue(first.ks_distance.equals(second.ks_distance))
        after=np.random.get_state()
        self.assertTrue(np.array_equal(before[1],after[1]));self.assertEqual(before[2:],after[2:])

    def test_dry_run_does_not_write_files(self):
        with TemporaryDirectory() as td,patch.object(r,'carregar_trajetorias',return_value=(Path(td),{})):
            result=r.analisar_caudas_temporais(td)
            self.assertEqual(result['files_written'],0)
            self.assertEqual(list(Path(td).iterdir()),[])

    def test_nested_method_message_is_not_a_numerical_failure(self):
        from types import SimpleNamespace
        def compare(*args,**kwargs):
            print('Assuming nested distributions')
            return -1.,.5
        dist=SimpleNamespace(mu=0.,sigma=1.,noise_flag=False)
        fit=SimpleNamespace(power_law=SimpleNamespace(xmin=2.),lognormal=dist,
            exponential=dist,truncated_power_law=dist,distribution_compare=compare)
        rows=r.comparar(fit)
        self.assertTrue(all(row['status']=='COMPLETED' for row in rows))
        self.assertTrue(rows[-1]['nested'])
        self.assertIn('Assuming nested distributions',rows[-1]['library_messages'])


if __name__=='__main__':unittest.main(verbosity=2)
