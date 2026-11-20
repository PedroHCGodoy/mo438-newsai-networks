"""Testes de integridade do pós-processamento, sem rede e sem credenciais."""
import copy
import json
import unittest
from unittest.mock import patch
import re_execucao
from re_posprocessamento import _text_sha, _json_sha, _revalidar_documento


def fixture(raw, entities, finish='STOP'):
    text='Ana e Empresa.'
    identity={'news_id':'doc','news_version_id':'v1','ner_input_sha256':_text_sha(text),
              'contract':{'provider':'google','prompt_sha256':_text_sha('Instruções.\n')}}
    prompt=('Instruções.\n\nDOCUMENTO\nDOCID: doc\n\nTEXTO:\n'+text+
            '\n\nLISTA DE ENTIDADES\n'+json.dumps(entities,ensure_ascii=False,indent=2))
    identity['prompt_sha256']=_text_sha(prompt)
    rid=_json_sha(identity)
    state, edges, audit=re_execucao.validar_resposta(raw,{x['em_id'] for x in entities},finish)
    original={'request_id':rid,'attempt_id':'abc','identity':identity,
              'news':{'news_id':'doc','news_version_id':'v1','mentions_pol':str(len(entities))},
              'state':state,'relations':edges}
    env={'request_id':rid,'attempt_id':'abc','identity':copy.deepcopy(identity),'http_status':200,
         'body':json.dumps({'candidates':[{'content':{'parts':[{'text':raw}]},'finishReason':finish}]})}
    return original,env,prompt


class PosProcessamentoTests(unittest.TestCase):
    def setUp(self):
        self.entities=[{'em_id':'a'*64,'mention_text':'Ana','categoria':'PESSOA'},
                       {'em_id':'c'*64,'mention_text':'Empresa','categoria':'ORGANIZACAO'}]
        self.edge={'head_id':'a'*63,'tail_id':'c'*64,'label':'vinculo_inst'}

    def test_candidate_never_changes_an_unapproved_id(self):
        o,e,p=fixture(json.dumps([self.edge]),self.entities)
        before=copy.deepcopy((o,e))
        d=_revalidar_documento(o,e,p,{})
        self.assertEqual(d['state'],'PARTIAL')
        self.assertEqual(d['relations'],[])
        self.assertEqual(d['candidates'][0]['candidate_count'],1)
        self.assertEqual((o,e),before)

    def test_ambiguous_candidate_remains_unapplied(self):
        entities=self.entities+[{'em_id':'a'*63+'b','mention_text':'Outra Ana','categoria':'PESSOA'}]
        o,e,p=fixture(json.dumps([self.edge]),entities)
        d=_revalidar_documento(o,e,p,{})
        self.assertEqual(d['state'],'PARTIAL')
        self.assertEqual(len(d['candidates']),2)
        self.assertTrue(all(x['candidate_count']==2 for x in d['candidates']))

    def decision(self,original):
        return {(original['request_id'],'a'*63):{'news_id':'doc',
                'prompt_sha256':original['identity']['prompt_sha256'],
                'new_id':'a'*64,'surface':'Ana','review_basis':'Correspondência documental revisada'}}

    def test_approved_repair_revalidates_and_deduplicates(self):
        valid=dict(self.edge,head_id='a'*64)
        o,e,p=fixture(json.dumps([self.edge,valid]),self.entities)
        d=_revalidar_documento(o,e,p,self.decision(o))
        self.assertEqual(d['state'],'SUCCESS')
        self.assertEqual(d['relations'],[valid])
        self.assertEqual(len(d['repairs']),1)
        self.assertEqual(d['audit']['items_duplicate'],1)

    def test_stale_prompt_decision_is_blocked(self):
        o,e,p=fixture(json.dumps([self.edge]),self.entities)
        decision=self.decision(o)
        next(iter(decision.values()))['prompt_sha256']='outro'
        with self.assertRaises(ValueError):_revalidar_documento(o,e,p,decision)

    def test_truncated_response_stays_partial_after_repair(self):
        o,e,p=fixture(json.dumps([self.edge])[:-1]+', {',self.entities)
        d=_revalidar_documento(o,e,p,self.decision(o))
        self.assertEqual(d['state'],'PARTIAL')
        self.assertEqual(len(d['relations']),1)

    def test_changed_prompt_is_blocked(self):
        o,e,p=fixture(json.dumps([self.edge]),self.entities)
        with self.assertRaises(ValueError):_revalidar_documento(o,e,p+' ',{})

    def test_technical_success_does_not_remove_semantic_alert(self):
        from re_posprocessamento import _alertas
        entities={'x':{'categoria':'LOCAL'},'y':{'categoria':'PESSOA'}}
        flags=_alertas({'head_id':'x','tail_id':'y','label':'ocorre_em'},entities)
        self.assertEqual(flags,['OCORRE_DESTINATION_NOT_LOCAL'])


if __name__=='__main__':
    with patch.object(re_execucao,'transporte_http',side_effect=AssertionError('Rede proibida')), \
         patch.object(re_execucao,'credenciais',side_effect=AssertionError('Credenciais proibidas')):
        suite=unittest.defaultTestLoader.loadTestsFromTestCase(PosProcessamentoTests)
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful():raise RuntimeError('Falha na verificação local.')
