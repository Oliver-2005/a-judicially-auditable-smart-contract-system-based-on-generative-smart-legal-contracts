import json
import os
from pathlib import Path
import tempfile
import unittest
from slcml_core.adapters import request_spec, invoke, InvocationError
from slcml_core.config import RunSettings
from slcml_core.pipeline import generate_segment
from slcml_core.preprocessing import digest, segment_contract, merge_ir
from slcml_core.validation import validate

class RecordingResponse:
    def __init__(self, status, result=None, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self.result = result or {}
    def json(self):
        return self.result
    def close(self):
        pass

class RecordingSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
    def post(self, endpoint, **kwargs):
        self.calls.append({'endpoint': endpoint, **kwargs})
        return next(self.responses)

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.old = {k: os.environ.get(k) for k in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GEMINI_API_KEY')}
        for key in self.old:
            os.environ[key] = 'unit-test-credential'
    def tearDown(self):
        for key, value in self.old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_provider_specific_parameters(self):
        messages = [{'role': 'system', 'content': 'S'}, {'role': 'user', 'content': 'U'}]
        _, _, _, gpt = request_spec('gpt', messages, 8200)
        self.assertNotIn('temperature', gpt)
        self.assertNotIn('top_p', gpt)
        self.assertEqual(gpt['reasoning_effort'], 'medium')
        _, _, _, claude = request_spec('claude', messages, 16384)
        self.assertEqual(claude['temperature'], .1)
        self.assertEqual(claude['thinking']['type'], 'disabled')
        _, _, _, gemini = request_spec('gemini', messages, 4196)
        self.assertEqual(gemini['generationConfig']['temperature'], .9)
        self.assertEqual(gemini['generationConfig']['thinkingConfig']['thinkingLevel'], 'high')

    def test_authentication_is_not_retried(self):
        session = RecordingSession([RecordingResponse(401)])
        with self.assertRaises(InvocationError):
            invoke('gpt', [{'role': 'user', 'content': 'U'}], 10, RunSettings(stream=False), session)
        self.assertEqual(len(session.calls), 1)

    def test_retry_budget_and_payload_identity(self):
        final = {'model': 'gpt-5', 'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}]}
        session = RecordingSession([RecordingResponse(503), RecordingResponse(429), RecordingResponse(200, final)])
        settings = RunSettings(stream=False, retry_backoff_seconds=(0, 0))
        result = invoke('gpt', [{'role': 'user', 'content': 'U'}], 10, settings, session)
        self.assertEqual(len(result['attempts']), 3)
        self.assertTrue(all(c['json'] == session.calls[0]['json'] for c in session.calls))

    def test_clause_is_not_truncated(self):
        text = 'Clause 1.1 — ' + 'a' * 100 + '\nClause 1.2 — refer to Clause 1.1\n'
        segments = segment_contract(text, 50)
        self.assertEqual(len(segments), 2)
        self.assertIn('a' * 100, segments[0]['target'])
        self.assertIn('Clause 1.1', segments[1]['context_only'])
        self.assertNotIn('a' * 100, segments[1]['target'])

    def test_single_revision_budget(self):
        calls = []
        def caller(*args):
            calls.append(args)
            return {'text': 'not-json', 'metadata': {}, 'attempts': []}
        text = 'Clause 1.1 — A term.'
        segment = {'segment_id': 'SEG_001', 'target': text, 'input_sha256': digest(text), 'clause_ids': ['1.1']}
        with tempfile.TemporaryDirectory(dir=os.getenv('SLCML_TEST_TMP')) as directory:
            record = generate_segment(segment, 'gpt', 'full', Path(directory), RunSettings(), caller)
            self.assertEqual(record['status'], 'validation_failed')
            self.assertEqual(len(calls), 2)
            self.assertTrue((Path(directory) / 'revision_0/response.txt').exists())
            self.assertTrue((Path(directory) / 'revision_1/response.txt').exists())

    def test_baseline_has_no_semantic_revision(self):
        calls = []
        def caller(*args):
            calls.append(args)
            return {'text': 'not-json', 'metadata': {}, 'attempts': []}
        text = 'A term.'
        segment = {'segment_id': 'SEG_001', 'target': text, 'input_sha256': digest(text)}
        with tempfile.TemporaryDirectory(dir=os.getenv('SLCML_TEST_TMP')) as directory:
            generate_segment(segment, 'gpt', 'baseline', Path(directory), RunSettings(), caller)
        self.assertEqual(len(calls), 1)

    def test_disabled_checker_emits_no_feedback(self):
        ir = {'Subject': [], 'Object': [], 'Condition': [], 'Rule': [], 'Audit': {}}
        record = validate(ir, {'schema_validation'})
        self.assertEqual([x['module'] for x in record], ['schema_validation'])

    def test_source_clause_reference_is_checked(self):
        ir = {'Subject': [{'subject_id': 's', 'source_clause_index': 'Clause_9'}],
              'Object': [], 'Condition': [], 'Rule': [], 'Audit': {}}
        record = validate(ir, {'schema_validation'}, ['1'])
        self.assertEqual(record[0]['status'], 'failed')

    def test_formal_check_reads_numeric_constraints(self):
        ir = {'Subject': [], 'Object': [], 'Rule': [], 'Audit': {}, 'Condition': [
            {'condition_id': 'c1', 'constraint_group': 'g', 'predicate_components': {'left_operand': 'x', 'operator': '>', 'right_operand': 10, 'operand_type': 'number'}},
            {'condition_id': 'c2', 'constraint_group': 'g', 'predicate_components': {'left_operand': 'x', 'operator': '<', 'right_operand': 5, 'operand_type': 'number'}}]}
        records = validate(ir, {'formal_checking'})
        self.assertEqual(records[0]['status'], 'failed')
        ir['Condition'][1]['predicate_components']['right_operand'] = 20
        self.assertEqual(validate(ir, {'formal_checking'})[0]['status'], 'passed')

    def test_cross_segment_identifier_collisions_are_resolved(self):
        first = {'Subject': [{'subject_id': 's', 'text': 'First party'}], 'Object': [], 'Condition': [],
                 'Rule': [{'rule_id': 'r', 'target_subject': 's', 'text': 'First rule'}], 'Audit': {}}
        second = {'Subject': [{'subject_id': 's', 'text': 'Second party'}], 'Object': [], 'Condition': [],
                  'Rule': [{'rule_id': 'r', 'target_subject': 's', 'text': 'Second rule'}], 'Audit': {}}
        merged = merge_ir([first, second])
        self.assertEqual(len({x['subject_id'] for x in merged['Subject']}), 2)
        self.assertEqual(merged['Rule'][1]['target_subject'], merged['Subject'][1]['subject_id'])
        self.assertEqual(first['Subject'][0]['subject_id'], 's')

    def test_cross_segment_repeated_elements_share_identifiers(self):
        item = {'Subject': [{'subject_id': 's', 'text': 'Same party'}], 'Object': [], 'Condition': [],
                'Rule': [{'rule_id': 'r', 'target_subject': 's', 'text': 'Same rule'}], 'Audit': {}}
        merged = merge_ir([item, item])
        self.assertEqual(len(merged['Subject']), 1)
        self.assertEqual(len(merged['Rule']), 1)

    def test_conflicting_metadata_is_not_silently_selected(self):
        first = {'metadata': {'case_parameters': {'power': 285}}}
        second = {'metadata': {'case_parameters': {'power': 315}}}
        with self.assertRaises(ValueError):
            merge_ir([first, second])

    def test_same_rule_text_for_different_roles_is_not_deduplicated(self):
        first = {'Subject': [{'subject_id': 's', 'text': 'First party'}], 'Object': [], 'Condition': [],
                 'Rule': [{'rule_id': 'r', 'target_subject': 's', 'text': 'Must deliver'}], 'Audit': {}}
        second = {'Subject': [{'subject_id': 's', 'text': 'Second party'}], 'Object': [], 'Condition': [],
                  'Rule': [{'rule_id': 'r', 'target_subject': 's', 'text': 'Must deliver'}], 'Audit': {}}
        self.assertEqual(len(merge_ir([first, second])['Rule']), 2)

if __name__ == '__main__':
    unittest.main()

