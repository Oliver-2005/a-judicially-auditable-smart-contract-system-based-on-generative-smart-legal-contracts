import unittest
from evaluator.metrics_calc import dimension_prf, logic_consistency, procedural_completeness, audit_coverage, evaluate_dataset

HASH = '0x' + '1' * 64

def event(stage, position=0, path='p'):
    return {'path_id': path, 'stage': stage, 'triggered': True, 'transaction_success': True,
            'transaction_hash': HASH, 'block_number': 1, 'transaction_index': 0, 'log_index': position}

class MetricTests(unittest.TestCase):
    def test_duplicate_predictions_match_once(self):
        result = dimension_prf(['same clause', 'same clause'], ['same clause'], 0.8)
        self.assertEqual(result['tp'], 1)
        self.assertAlmostEqual(result['f1'], 2 / 3)

    def test_lc_does_not_shrink_denominator(self):
        result = logic_consistency(['a', 'b'], [{'check_id': 'a', 'passed': True}])
        self.assertEqual(result['value'], 0.5)

    def test_lc_rejects_duplicate_observations(self):
        with self.assertRaises(ValueError):
            logic_consistency(['a'], [{'check_id': 'a', 'passed': True}] * 2)

    def test_pc_requires_triggered_order(self):
        paths = [{'path_id': 'p', 'stages': ['freeze', 'challenge', 'decision']}]
        correct = [event('freeze', 0), event('challenge', 1), event('decision', 2)]
        self.assertEqual(procedural_completeness(paths, correct)['value'], 1)
        wrong = [event('freeze', 1), event('challenge', 0), event('decision', 2)]
        self.assertEqual(procedural_completeness(paths, wrong)['value'], 1 / 3)
        correct[1]['triggered'] = False
        self.assertEqual(procedural_completeness(paths, correct)['value'], 1 / 3)

    def test_pc_rejects_nontransaction_keywords(self):
        paths = [{'path_id': 'p', 'stages': ['freeze', 'challenge', 'decision']}]
        self.assertEqual(procedural_completeness(paths, [{'path_id': 'p', 'stage': 'freeze'}])['value'], 0)

    def test_ac_requires_matching_clause_and_evidence(self):
        nodes = [{'node_id': 'freeze', 'event': 'AuditEvidence', 'clause_indices': ['3.2']}]
        record = {**event('freeze'), 'node_id': 'freeze', 'event': 'AuditEvidence',
                  'clause_index': 'Clause_3.2', 'evidence_hash': HASH}
        self.assertEqual(audit_coverage(nodes, [record], {'3.2'})['value'], 1)
        self.assertEqual(audit_coverage(nodes, [record], set())['value'], 0)
        record['evidence_hash'] = '0x' + '0' * 64
        self.assertEqual(audit_coverage(nodes, [record], {'3.2'})['value'], 0)

    def test_contract_macro_not_pooled_check_rate(self):
        contracts = {}
        runs = []
        for name, checks in [('a', ['1', '2']), ('b', ['1', '2', '3', '4'])]:
            contracts[name] = {'tier': 'Tier1', 'elements': {d: ['same'] for d in ('S', 'O', 'C', 'R')},
                'logic_check_ids': checks, 'procedure_paths': [],
                'audit_nodes': [{'node_id': 'n', 'event': 'AuditEvidence', 'clause_indices': ['1']}]}
            runs.append({'contract_id': name, 'model': 'm', 'configuration': 'full',
                         'elements': {d: ['same'] for d in ('S', 'O', 'C', 'R')},
                         'logic_checks': [{'check_id': '1', 'passed': True}]})
        summary = evaluate_dataset({'contracts': contracts}, runs, .8)['summary'][0]
        self.assertAlmostEqual(summary['LC'], (1 / 2 + 1 / 4) / 2)
        self.assertNotAlmostEqual(summary['LC'], 2 / 6)

    def test_missing_contract_is_retained(self):
        gold = {'tier': 'Tier1', 'elements': {d: ['same'] for d in ('S', 'O', 'C', 'R')},
                'logic_check_ids': ['x'], 'procedure_paths': [],
                'audit_nodes': [{'node_id': 'n', 'event': 'AuditEvidence', 'clause_indices': ['1']}]}
        runs = [{'contract_id': 'a', 'model': 'm', 'configuration': 'full'}]
        result = evaluate_dataset({'contracts': {'a': gold, 'b': gold}}, runs, .8)
        self.assertEqual(len(result['contracts']), 2)
        self.assertEqual(result['contracts'][1]['failures'], ['missing_run'])

if __name__ == '__main__':
    unittest.main()

