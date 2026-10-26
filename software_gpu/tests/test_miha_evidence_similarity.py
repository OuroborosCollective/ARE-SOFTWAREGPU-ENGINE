"""Synthetic contract regressions; never production evidence."""
import unittest
from scripts.miha_evidence_similarity import analyze

class MihaSimilarityTest(unittest.TestCase):
    def setUp(self):
        self.data = {'schema': 'miha.source-multisets.v1', 'dataset_revision': 'a'*40,
                     'records': [{'id': 'one', 'source_ids': ['x','x','y']},
                                 {'id': 'two', 'source_ids': ['x','y','y']},
                                 {'id': 'missing', 'source_ids': []}]}

    def test_exact_multiset_dice_is_candidate_not_proof(self):
        value = analyze(self.data, 'b'*64)
        self.assertEqual(value['pairs'][0]['dice_dissimilarity'], '1/3')
        self.assertEqual(value['pairs'][0]['shared_counts'], {'x': 1, 'y': 1})
        self.assertEqual(value['insufficient_evidence_pairs'], 2)
        self.assertEqual(value['status'], 'CANDIDATE_ONLY_NOT_PROOF')

    def test_deterministic_order(self):
        a = analyze(self.data, 'b'*64)
        b = analyze({**self.data, 'records': list(reversed(self.data['records']))}, 'b'*64)
        self.assertEqual(a['pairs'], b['pairs'])

    def test_fail_closed(self):
        for change in ({'dataset_revision': 'main'},
                       {'records': self.data['records'][:1]},
                       {'records': self.data['records'][:2]*2},
                       {'records': [{'id':'x','source_ids':['bad\nid']}, self.data['records'][0]]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                analyze({**self.data, **change}, 'b'*64)

if __name__ == '__main__':
    unittest.main()
