"""Testes offline de consolidação, proveniência e integridade NER."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from ner_dados import COLUNAS, consolidar, carregar_consolidado, gravar_csv, sha_arquivo


class TesteDadosNER(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.base = self.root / 'base.csv'
        fields = 'news_id news_version_id title full_text source_normalized link publication_date_normalized publication_year'.split()
        self.news = [dict(zip(fields, [str(i), 'v1', 'Ana', '', 'Fonte', 'https://example.test/'+str(i), '2025-01-01', '2025'])) for i in (1, 2, 3)]
        gravar_csv(self.base, fields, self.news)
        self.hash = hashlib.sha256(b'Ana').hexdigest()
        self.documents = [dict(news_id=str(i), news_version_id='v1', ner_input_sha256=self.hash,
                               availability=state, execution_state='SUCCESS' if i == 1 else 'PARTIAL',
                               completion_basis='executor_validation') for i, state in [(1, 'AVAILABLE'), (2, 'PARTIAL')]]
        self.mentions = []
        for i in (1, 2):
            row = dict.fromkeys(COLUNAS, '')
            row.update(news_id=str(i), news_version_id='v1', ner_input_sha256=self.hash, source='Fonte',
                       link='https://example.test/'+str(i), publication_date='2025-01-01', start=0, end=3,
                       ent_text='Ana', ent_label='PESSOA', origin='inference' if i == 1 else 'inference_partial',
                       source_file='resposta.json', original_start='99', original_end='102')
            row['mention_id'] = hashlib.sha256(json.dumps([str(i), 'PESSOA', 0, 3, 'Ana'], ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
            self.mentions.append(row)
        self.source = dict(id='test', documentos=str(self.root/'docs.csv'), mencoes=[str(self.root/'mentions.csv.gz')], provenance={'kind':'test_fixture'})
        self.write()

    def write(self):
        gravar_csv(self.source['documentos'], list(self.documents[0]), self.documents)
        gravar_csv(self.source['mencoes'][0], COLUNAS, self.mentions)

    def run_consolidation(self, name='output'):
        return consolidar(self.base, [self.source], self.root/name)

    def test_partial_and_missing_and_provenance(self):
        meta = self.run_consolidation()
        docs, checked = carregar_consolidado(self.root/'output', self.base)
        self.assertEqual(meta['availability'], {'AVAILABLE':1, 'PARTIAL':1, 'NOT_PROCESSED':1})
        self.assertEqual(meta['mentions_all'], 2)
        self.assertEqual(meta['mentions_pol'], 2)
        self.assertEqual(docs[1]['execution_state'], 'PARTIAL')
        self.assertEqual(checked['sources'][0]['provenance']['kind'], 'test_fixture')
        from ner_dados import linhas
        self.assertEqual(next(linhas(self.root/'output/mencoes_todas.csv.gz'))['original_start'], '99')

    def test_reject_duplicate_mention(self):
        self.mentions.append(self.mentions[0]); self.write()
        with self.assertRaisesRegex(ValueError, 'repetido'):
            self.run_consolidation()
        self.assertFalse((self.root/'output').exists())

    def test_reject_conflicting_sources(self):
        other = deepcopy(self.source); other['id'] = 'other'
        with self.assertRaisesRegex(ValueError, 'sobrepostas'):
            consolidar(self.base, [self.source, other], self.root/'output')

    def test_reject_text_or_version_change(self):
        self.documents[0]['news_version_id'] = 'v2'; self.write()
        with self.assertRaisesRegex(ValueError, 'incompatível'):
            self.run_consolidation()

    def test_reject_wrong_slice(self):
        self.mentions[0]['ent_text'] = 'Eva'; self.write()
        with self.assertRaisesRegex(ValueError, 'Superfície'):
            self.run_consolidation()

    def test_reject_unknown_label(self):
        self.mentions[0]['ent_label'] = 'PERSON'; self.write()
        with self.assertRaisesRegex(ValueError, 'Rótulo'):
            self.run_consolidation()

    def test_same_content_different_csv_serialization(self):
        self.run_consolidation()
        text = self.base.read_text(encoding='utf-8-sig').replace('\r\n','\n')
        self.base.write_bytes(text.encode('utf-8'))
        carregar_consolidado(self.root/'output', self.base)
        changed = text.replace('Ana', 'Eva', 1)
        self.base.write_text(changed, encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'base lógica'):
            carregar_consolidado(self.root/'output', self.base)

    def test_detect_changed_output(self):
        self.run_consolidation()
        with (self.root/'output/documentos_ner.csv').open('a') as f:f.write('changed')
        with self.assertRaisesRegex(ValueError, 'alterado'):
            carregar_consolidado(self.root/'output', self.base)

    def test_preserve_existing_snapshot(self):
        self.run_consolidation()
        before = sha_arquivo(self.root/'output/manifesto.json')
        with self.assertRaises(FileExistsError):self.run_consolidation()
        self.assertEqual(before, sha_arquivo(self.root/'output/manifesto.json'))

    def test_reproducible_outputs(self):
        first = self.run_consolidation('one')
        second = self.run_consolidation('two')
        self.assertEqual(first, second)
        self.assertEqual(sha_arquivo(self.root/'one/manifesto.json'), sha_arquivo(self.root/'two/manifesto.json'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
