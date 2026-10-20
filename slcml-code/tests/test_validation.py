import copy
import json
from pathlib import Path
import tempfile
import unittest

from compiler.compile_ir import compile_ir
from slcml_core.config import CONFIGURATIONS
from slcml_core.pipeline import parse_json
from slcml_core.preprocessing import merge_ir
from slcml_core.prompt_builder import build_prompt
from slcml_core.validation import ACCEPTED, full_structure_errors, load_schema, validate
from prompts.slcml_phase_a import PhaseAValidator
from prompts.slcml_scot_framework import SLCMLPromptFramework
from prompts.slcml_phase_c import Tier1RuleFilter
from tests.fixtures import complete_ir

ALL = {'schema_validation', 'formal_checking', 'state_machine', 'audit_template'}


class ValidationTests(unittest.TestCase):
    def check(self, ir, module='schema_validation'):
        return validate(ir, {module}, ['1.1'])[0]

    def test_schema_is_a_valid_draft_2020_12_schema(self):
        self.assertEqual(load_schema()['properties']['schema_version']['const'], '2.1.0')

    def test_complete_ir_passes_all_enabled_checks(self):
        results = validate(complete_ir(), ALL, ['1.1'])
        self.assertTrue(all(x['status'] == 'passed' for x in results), results)

    def test_full_structural_profile_rejects_empty_audit(self):
        ir = complete_ir()
        self.assertFalse(full_structure_errors(ir))
        ir['Audit'] = {}
        self.assertTrue(full_structure_errors(ir))

    def test_full_structural_profile_requires_applicable_procedure(self):
        ir = complete_ir()
        del ir['Rule'][1]['procedural_justice']
        self.assertTrue(full_structure_errors(ir))

    def test_missing_required_core_fields_are_rejected(self):
        for collection, field in [('Subject', 'role'), ('Object', 'natural_language_description'),
                                  ('Condition', 'formal_predicate'), ('Rule', 'target_subject')]:
            with self.subTest(field=field):
                ir = complete_ir()
                del ir[collection][0][field]
                self.assertEqual(self.check(ir)['status'], 'failed')

    def test_unversioned_and_unknown_fields_are_rejected(self):
        ir = complete_ir()
        del ir['schema_version']
        self.assertEqual(self.check(ir)['status'], 'failed')
        ir = complete_ir()
        ir['Subject'][0]['rol'] = 'DataProvider'
        self.assertEqual(self.check(ir)['status'], 'failed')

    def test_minimal_identifier_only_ir_is_rejected(self):
        ir = {'schema_version': '2.1.0', 'Subject': [{'subject_id': 's'}],
              'Object': [{'object_id': 'o'}], 'Condition': [], 'Rule': [{'rule_id': 'r'}], 'Audit': {}}
        self.assertEqual(self.check(ir)['status'], 'failed')

    def test_so_cr_text_arrays_never_pass_ir_validation(self):
        results = validate({d: [] for d in ('S', 'O', 'C', 'R')}, ALL)
        self.assertTrue(all(x['status'] == 'not_evaluable' for x in results))

    def test_wrong_input_types_are_reported_not_raised(self):
        for value in (None, [], 'text', 42):
            with self.subTest(value=value):
                results = validate(value, ALL)
                self.assertTrue(all(x['status'] == 'failed' for x in results))

    def test_invalid_enums_whitespace_and_ranges(self):
        mutations = [('role', 'UnknownRole'), ('natural_language_description', '  '),
                     ('initial_reputation_score', 101), ('initial_reputation_score', True)]
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                ir = complete_ir()
                ir['Subject'][0][field] = value
                self.assertEqual(self.check(ir)['status'], 'failed')

    def test_repeated_identifiers_are_rejected(self):
        ir = complete_ir()
        ir['Subject'].append(copy.deepcopy(ir['Subject'][0]))
        self.assertIn('duplicate_identifier', {x['code'] for x in self.check(ir)['errors']})

    def test_unknown_subject_condition_and_rule_references(self):
        for field, value in [('target_subject', 'missing'), ('target_object', 'missing'),
                             ('trigger_condition_ids', ['missing']), ('depends_on_rule_ids', ['missing'])]:
            with self.subTest(field=field):
                ir = complete_ir()
                ir['Rule'][0][field] = value
                self.assertIn('unknown_reference', {x['code'] for x in self.check(ir)['errors']})

    def test_unknown_source_clause_is_rejected(self):
        ir = complete_ir()
        ir['Subject'][0]['source_clause_index'] = 'Clause_99.1'
        self.assertIn('unknown_clause', {x['code'] for x in self.check(ir)['errors']})

    def test_numeric_strings_boolean_numbers_and_nonfinite_are_rejected(self):
        for value in ('1000', True, float('nan'), float('inf')):
            with self.subTest(value=value):
                ir = complete_ir()
                ir['Condition'][0]['predicate_components']['right_operand'] = value
                self.assertEqual(self.check(ir)['status'], 'failed')

    def test_unconditional_rule_can_have_no_conditions(self):
        ir = complete_ir()
        ir['Condition'] = []
        ir['Rule'] = [ir['Rule'][0]]
        ir['Rule'][0].update(trigger_condition_ids=[], trigger_condition_logic='UNCONDITIONAL')
        ir['dispute_unit_templates'] = []
        ir['Audit'] = {}
        results = validate(ir, {'schema_validation', 'formal_checking', 'state_machine'}, ['1.1'])
        self.assertTrue(all(x['status'] in ACCEPTED for x in results), results)

    def test_schema_allows_empty_audit_only_when_its_module_is_not_required(self):
        ir = complete_ir()
        ir['Audit'] = {}
        self.assertEqual(self.check(ir)['status'], 'passed')
        self.assertEqual(self.check(ir, 'audit_template')['status'], 'failed')

    def test_schema_does_not_reintroduce_removed_state_module(self):
        ir = complete_ir()
        del ir['Rule'][1]['state_machine_transition']
        del ir['Rule'][1]['procedural_justice']
        del ir['Rule'][1]['dispute_unit_template_id']
        ir['dispute_unit_templates'] = []
        self.assertEqual(self.check(ir)['status'], 'passed')
        self.assertEqual(self.check(ir, 'state_machine')['status'], 'failed')

    def test_unsupported_predicate_is_not_treated_as_verified(self):
        ir = complete_ir()
        ir['Condition'][0]['predicate_components'] = None
        ir['Condition'][0]['review'] = {'requires_human_review': True, 'reasons': ['Unresolved expression'], 'confidence': None}
        self.assertEqual(self.check(ir)['status'], 'passed')
        self.assertEqual(self.check(ir, 'formal_checking')['status'], 'not_evaluable')

    def test_unsatisfiable_shared_constraint_group_is_rejected(self):
        ir = complete_ir()
        first = ir['Condition'][0]
        first['constraint_group'] = 'same_context'
        second = copy.deepcopy(first)
        second['condition_id'] = 'c_other'
        second['predicate_components'].update(operator='>', right_operand=2000)
        ir['Condition'].append(second)
        self.assertIn('unsatisfiable_constraints', {x['code'] for x in self.check(ir, 'formal_checking')['errors']})

    def test_unrelated_alternative_conditions_are_not_conjoined(self):
        ir = complete_ir()
        second = copy.deepcopy(ir['Condition'][0])
        second['condition_id'] = 'c_alternative'
        second['predicate_components'].update(operator='>', right_operand=2000)
        ir['Condition'].append(second)
        self.assertEqual(self.check(ir, 'formal_checking')['status'], 'passed')

    def test_any_trigger_is_not_misinterpreted_as_all(self):
        ir = complete_ir()
        second = copy.deepcopy(ir['Condition'][0])
        second['condition_id'] = 'c_alternative'
        second['predicate_components'].update(operator='>', right_operand=2000)
        ir['Condition'].append(second)
        ir['Rule'][0].update(trigger_condition_ids=['c_oxygen', 'c_alternative'], trigger_condition_logic='ANY')
        self.assertEqual(self.check(ir, 'formal_checking')['status'], 'passed')
        ir['Rule'][0]['trigger_condition_logic'] = 'ALL'
        self.assertEqual(self.check(ir, 'formal_checking')['status'], 'failed')

    def test_dependencies_must_be_acyclic(self):
        ir = complete_ir()
        ir['Condition'][0]['depends_on'] = ['c_oxygen']
        self.assertIn('dependency_cycle', {x['code'] for x in self.check(ir, 'formal_checking')['errors']})
        ir = complete_ir()
        ir['Rule'][0]['depends_on_rule_ids'] = ['r_accept']
        self.assertIn('dependency_cycle', {x['code'] for x in self.check(ir, 'formal_checking')['errors']})

    def test_budget_interval_is_checked(self):
        ir = complete_ir()
        ir['Object'][0]['quantifiable_attributes'] = {'privacy_budget_total': 10, 'privacy_budget_remaining': 11}
        self.assertIn('budget_interval', {x['code'] for x in self.check(ir, 'formal_checking')['errors']})

    def test_state_order_and_direct_breach_are_rejected(self):
        for stages in ([], ['Challenge', 'Frozen'], ['Breach', 'Frozen', 'Challenge']):
            with self.subTest(stages=stages):
                ir = complete_ir()
                ir['Rule'][1]['state_machine_transition']['intermediate_states'] = stages
                self.assertEqual(self.check(ir, 'state_machine')['status'], 'failed')

    def test_window_must_be_positive_and_not_boolean(self):
        for window in (0, -1, True):
            with self.subTest(window=window):
                ir = complete_ir()
                ir['Rule'][1]['procedural_justice']['challenge_phase']['challenge_window_seconds'] = window
                self.assertEqual(self.check(ir, 'state_machine')['status'], 'failed')

    def test_unresolved_window_is_not_verified(self):
        ir = complete_ir()
        ir['Rule'][1]['procedural_justice']['challenge_phase']['challenge_window_seconds'] = None
        self.assertEqual(self.check(ir, 'state_machine')['status'], 'not_evaluable')

    def test_timeout_cannot_override_a_submitted_challenge(self):
        ir = complete_ir()
        ir['Rule'][1]['procedural_justice']['adjudication_phase']['timeout_requires_no_submission'] = False
        self.assertEqual(self.check(ir, 'state_machine')['status'], 'failed')

    def test_decision_outcomes_must_match_target_states(self):
        ir = complete_ir()
        ir['Rule'][1]['procedural_justice']['adjudication_phase']['adjudication_outcomes'][0]['next_state'] = 'Terminated'
        self.assertIn('outcome_state_mismatch', {x['code'] for x in self.check(ir, 'state_machine')['errors']})

    def test_procedural_subjects_are_checked_without_schema_module(self):
        ir = complete_ir()
        ir['Rule'][1]['procedural_justice']['challenge_phase']['eligible_challengers'] = ['missing']
        self.assertIn('unknown_procedural_subject', {x['code'] for x in self.check(ir, 'state_machine')['errors']})

    def test_dispute_parameters_and_restricted_recovery_are_checked(self):
        ir = complete_ir()
        ir['dispute_unit_templates'][0]['finality_defaults']['theta_safe'] = 1
        self.assertEqual(self.check(ir, 'state_machine')['status'], 'failed')
        ir = complete_ir()
        ir['dispute_unit_templates'][0]['restricted_recovery_defaults']['privacy_cost_multiplier'] = 1
        self.assertEqual(self.check(ir, 'state_machine')['status'], 'failed')

    def test_unresolved_defaults_are_preserved_without_inventing_values(self):
        ir = complete_ir()
        ir['dispute_unit_templates'][0].update(parameter_basis='Unresolved', finality_defaults=None,
                                             restricted_recovery_defaults=None)
        self.assertEqual(self.check(ir)['status'], 'passed')
        self.assertEqual(self.check(ir, 'state_machine')['status'], 'not_evaluable')
        ir['dispute_unit_templates'][0]['parameter_basis'] = 'SourceClause'
        self.assertEqual(self.check(ir)['status'], 'failed')

    def test_audit_requires_all_declared_layers(self):
        ir = complete_ir()
        ir['Audit']['evidence_templates'][0]['template_layer'] = 'ProceduralRecord'
        self.assertIn('incomplete_audit_layers', {x['code'] for x in self.check(ir, 'audit_template')['errors']})

    def test_missing_template_mapping_and_unknown_event_field_are_rejected(self):
        ir = complete_ir()
        ir['Audit']['evidence_templates'][0]['placeholder_mappings'].pop()
        self.assertIn('placeholder_mapping_mismatch', {x['code'] for x in self.check(ir, 'audit_template')['errors']})
        ir = complete_ir()
        ir['Audit']['evidence_templates'][0]['placeholder_mappings'][0]['data_source'] = 'missing'
        self.assertIn('unknown_event_field', {x['code'] for x in self.check(ir, 'audit_template')['errors']})

    def test_audit_requires_distinct_clause_and_hash_fields(self):
        ir = complete_ir()
        ir['Audit']['judicial_log_schema']['field_roles']['evidence_hash'] = 'clauseId'
        self.assertIn('invalid_log_field_roles', {x['code'] for x in self.check(ir, 'audit_template')['errors']})

    def test_audit_requires_node_rule_templates_and_registered_clauses(self):
        ir = complete_ir()
        ir['Audit']['evidence_templates'].pop()
        self.assertIn('missing_node_rule_template', {x['code'] for x in self.check(ir, 'audit_template')['errors']})
        ir = complete_ir()
        ir['Audit']['key_execution_nodes'][0]['clause_index'] = 'Clause_99'
        self.assertIn('invalid_audit_node_anchor', {x['code'] for x in self.check(ir, 'audit_template')['errors']})

    def test_unknown_or_missing_audit_rule_reference_is_rejected(self):
        ir = complete_ir()
        ir['Audit']['evidence_templates'][0]['associated_rule_id'] = 'missing'
        self.assertEqual(self.check(ir, 'audit_template')['status'], 'failed')

    def test_disabled_module_produces_no_diagnostics(self):
        ir = complete_ir()
        ir['Audit'] = {}
        results = validate(ir, ALL - {'audit_template'}, ['1.1'])
        self.assertNotIn('audit_template', {x['module'] for x in results})
        self.assertTrue(all(x['status'] in ACCEPTED for x in results), results)

    def test_json_parser_rejects_duplicate_keys_nonfinite_and_trailing_text(self):
        for text in ('{"S": [], "S": []}', '{"x": NaN}', '{"x": Infinity}', '{} text'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_json(text)

    def test_merge_preserves_audit_definitions_and_rewrites_nested_references(self):
        merged = merge_ir([complete_ir(), complete_ir()])
        results = validate(merged, ALL, ['1.1'])
        self.assertTrue(all(x['status'] in ACCEPTED for x in results), results)
        self.assertIn('judicial_log_schema', merged['Audit'])
        self.assertIn('schema_version', merged)

    def test_conflicting_audit_definitions_are_not_silently_selected(self):
        first, second = complete_ir(), complete_ir()
        second['Audit']['judicial_log_schema']['log_event_name'] = 'DifferentEvent'
        with self.assertRaises(ValueError):
            merge_ir([first, second])

    def test_compiler_rejects_invalid_ir_before_creating_output(self):
        ir = complete_ir()
        ir['Audit'] = {}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'should_not_exist.sol'
            with self.assertRaises(ValueError):
                compile_ir(ir, 'unused.sol.j2', output)
            self.assertFalse(output.exists())

    def test_prompt_contains_schema_and_correct_template_reference(self):
        segment = {'segment_id': 's', 'target': 'Clause 1.1 — Declaration.', 'clause_ids': ['1.1']}
        messages = build_prompt(segment, CONFIGURATIONS['full'])
        self.assertEqual(json.loads(messages[1]['content'])['output_schema']['properties']['schema_version']['const'], '2.1.0')
        self.assertIn('associated_rule_id', messages[0]['content'])
        baseline = build_prompt(segment, CONFIGURATIONS['baseline'])
        self.assertNotIn('output_schema', json.loads(baseline[1]['content']))

    def test_public_prompt_entries_use_one_canonical_schema(self):
        self.assertTrue(PhaseAValidator.validate(complete_ir(), ['1.1'])[0])
        self.assertTrue(SLCMLPromptFramework.validate_output_structure(complete_ir())['valid'])
        messages = SLCMLPromptFramework.assemble_prompt('Clause 1.1 — Declaration.')
        self.assertEqual(json.loads(messages[1]['content'])['output_schema']['$id'], 'urn:slcml:ir:2.1.0')

    def test_runtime_filter_reads_canonical_subject_object_and_template_fields(self):
        event = {'event_id': 'e1', 'matched_clause_id': 'Clause_1.1', 'issue_type': 'parameter_discrepancy',
                 'subject_id': 's_analyst', 'object_id': 'o_record'}
        records = Tier1RuleFilter(complete_ir()).filter_events([event])
        self.assertEqual(records[0]['matched_template_id'], 'dut_oxygen')
        event['subject_id'] = 'unknown'
        self.assertEqual(Tier1RuleFilter(complete_ir()).filter_events([event]), [])

    def test_template_expressions_are_not_evaluated_as_python_attributes(self):
        ir = complete_ir()
        ir['Audit']['evidence_templates'][0]['template_content'] += ' {state.__class__}'
        self.assertIn('unsupported_template_expression', {x['code'] for x in self.check(ir, 'audit_template')['errors']})

    def test_string_boolean_and_set_predicates_are_supported(self):
        for components in [
            {'left_operand': 'region', 'operator': '==', 'right_operand': 'IE', 'operand_type': 'string'},
            {'left_operand': 'consent', 'operator': '==', 'right_operand': True, 'operand_type': 'boolean'},
            {'left_operand': 'region', 'operator': 'in', 'right_operand': ['IE', 'US'], 'operand_type': 'set'}
        ]:
            with self.subTest(components=components):
                ir = complete_ir()
                ir['Condition'][0]['predicate_components'] = components
                self.assertEqual(self.check(ir, 'formal_checking')['status'], 'passed')

    def test_operand_units_are_not_silently_converted(self):
        ir = complete_ir()
        second = copy.deepcopy(ir['Condition'][0])
        second['condition_id'] = 'c_other'
        second['predicate_components']['unit'] = 'percent'
        ir['Condition'].append(second)
        self.assertIn('inconsistent_operand_type_or_unit', {x['code'] for x in self.check(ir, 'formal_checking')['errors']})

    def test_failure_triggers_preserve_prerequisite_guards(self):
        ir = complete_ir()
        guard = copy.deepcopy(ir['Condition'][0])
        guard['condition_id'] = 'c_guard'
        guard['predicate_components']['right_operand'] = 0
        ir['Condition'].append(guard)
        ir['Condition'][0]['depends_on'] = ['c_guard']
        self.assertIn('unsatisfiable_constraints', {x['code'] for x in self.check(ir, 'formal_checking')['errors']})

    def test_total_budget_is_checked_even_without_remaining_budget(self):
        ir = complete_ir()
        ir['Object'][0]['quantifiable_attributes'] = {'privacy_budget_total': -1}
        self.assertIn('invalid_total_budget', {x['code'] for x in self.check(ir, 'formal_checking')['errors']})

    def test_valid_ir_reaches_template_rendering(self):
        template = Path(__file__).resolve().parents[1] / 'compiler/templates/AMB2022SourceAudit.sol.j2'
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'contract.sol'
            checks = compile_ir(complete_ir(), template, output,
                                {'nominal_power': 285, 'nominal_speed': 960,
                                 'oxygen_upper_bound': 1000, 'challenge_window': 86400})
            self.assertTrue(all(x['status'] in ACCEPTED for x in checks))
            self.assertIn('pragma solidity', output.read_text(encoding='utf-8'))

    def test_identifier_namespaces_cannot_collide_during_merge(self):
        ir = complete_ir()
        ir['Object'][0]['object_id'] = 's_provider'
        self.assertIn('identifier_namespace_collision', {x['code'] for x in self.check(ir)['errors']})


if __name__ == '__main__':
    unittest.main()
