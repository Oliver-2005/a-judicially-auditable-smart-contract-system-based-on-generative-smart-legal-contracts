def complete_ir():
    subjects = [
        {'subject_id': identifier, 'role': role, 'natural_language_description': description,
         'address_placeholder': '_' + identifier, 'source_clause_index': 'Clause_1.1'}
        for identifier, role, description in [
            ('s_provider', 'DataProvider', 'Record provider'),
            ('s_analyst', 'DataAnalyst', 'Record analyst'),
            ('s_reviewer', 'DesignatedReviewer', 'Designated reviewer')]
    ]
    condition = {'condition_id': 'c_oxygen', 'condition_category': 'Quantitative',
                 'natural_language_expression': 'Declared oxygen is below 1000 ppm',
                 'formal_predicate': 'oxygen_ppm < 1000',
                 'predicate_components': {'left_operand': 'oxygen_ppm', 'operator': '<',
                                          'right_operand': 1000, 'operand_type': 'number', 'unit': 'ppm'},
                 'evaluation_timing': 'BeforeExecution', 'source_clause_index': 'Clause_1.1'}
    common = {'target_subject': 's_analyst', 'target_object': 'o_record',
              'trigger_condition_ids': ['c_oxygen'], 'source_clause_index': 'Clause_1.1'}
    normal = {**common, 'rule_id': 'r_accept', 'rule_type': 'Permission',
              'natural_language_description': 'Accept a compliant declaration', 'trigger_condition_logic': 'ALL'}
    dispute = {**common, 'rule_id': 'r_dispute', 'rule_type': 'Penalty',
               'natural_language_description': 'Preserve, challenge and review a discrepant declaration',
               'trigger_condition_logic': 'ON_FAILURE', 'dispute_unit_template_id': 'dut_oxygen',
               'state_machine_transition': {'from_state': 'Active', 'intermediate_states': ['Frozen', 'Challenge'],
                                            'possible_end_states': ['Breach', 'Restored']},
               'procedural_justice': {
                   'freeze_phase': {'freeze_action_description': 'Hold release pending review',
                                    'freeze_timestamp_field': 'challengeStart', 'evidence_preservation': ['evidenceHash']},
                   'challenge_phase': {'challenge_window_seconds': 86400, 'deadline_inclusive': True,
                                       'eligible_challengers': ['s_analyst'],
                                       'challenge_submission': {'function_signature': 'submitChallenge(bytes32)',
                                                                'required_evidence_types': ['correction_record'],
                                                                'nonzero_evidence_required': True}},
                   'adjudication_phase': {'adjudication_authority': {'authority_type': 'DesignatedReviewer',
                                                                    'authority_subject_id': 's_reviewer'},
                                          'adjudication_outcomes': [{'outcome_type': 'BreachConfirmed', 'next_state': 'Breach'},
                                                                    {'outcome_type': 'BreachDismissed', 'next_state': 'Restored'}],
                                          'default_outcome_on_timeout': 'BreachConfirmed',
                                          'timeout_requires_no_submission': True}}}
    phases = [('accept', 'NormalAcceptance', 'r_accept', 'FactStatement'),
              ('freeze', 'Frozen', 'r_dispute', 'BreachIdentification'),
              ('challenge', 'Challenge', 'r_dispute', 'ProceduralRecord'),
              ('decision', 'Adjudication', 'r_dispute', 'JudicialSummary')]
    nodes, templates = [], []
    for identifier, phase, rule, layer in phases:
        nodes.append({'node_id': 'node_' + identifier, 'event': 'AuditEvidence', 'phase': phase,
                      'clause_index': 'Clause_1.1', 'rule_ids': [rule]})
        templates.append({'template_id': 'evid_' + identifier, 'node_id': 'node_' + identifier,
                          'associated_rule_id': rule, 'template_layer': layer,
                          'template_content': 'Clause {clauseId}, evidence {evidenceHash}, state {state}, time {timestamp}.',
                          'placeholder_mappings': [{'placeholder': '{' + field + '}', 'data_source': field, 'data_type': 'record'}
                                                   for field in ('clauseId', 'evidenceHash', 'state', 'timestamp')]})
    return {'schema_version': '2.1.0', 'contract_id': 'unit_contract', 'Subject': subjects,
            'Object': [{'object_id': 'o_record', 'object_type': 'SourceRecord',
                        'natural_language_description': 'Controlled source record', 'owner_subject_id': 's_provider',
                        'source_clause_index': 'Clause_1.1'}],
            'Condition': [condition], 'Rule': [normal, dispute],
            'dispute_unit_templates': [{'template_id': 'dut_oxygen', 'rule_ids': ['r_dispute'],
                                       'source_clause_index': 'Clause_1.1', 'issue_type': 'parameter_discrepancy',
                                       'subject_ids': ['s_analyst'], 'object_ids': ['o_record'],
                                       'merge_criteria_description': 'Same record, clause and review episode',
                                       'parameter_basis': 'ConfiguredDefault',
                                       'finality_defaults': {'N_max': 1, 'K_max': 3, 'theta_safe': 0.6},
                                       'restricted_recovery_defaults': {'manual_review_required': True,
                                                                       'high_sensitive_access_blocked': True,
                                                                       'privacy_cost_multiplier': 1.5}}],
            'Audit': {'evidence_templates': templates, 'key_execution_nodes': nodes,
                      'clause_index_registry': [{'clause_index': 'Clause_1.1', 'clause_title': 'Declaration and review'}],
                      'judicial_log_schema': {'log_event_name': 'AuditEvidence',
                                              'required_fields': ['clauseId', 'evidenceHash', 'state', 'timestamp'],
                                              'field_roles': {'clause_index': 'clauseId', 'evidence_hash': 'evidenceHash',
                                                              'state': 'state', 'timestamp': 'timestamp'}},
                      'audit_trail_requirements': {'hash_algorithm': 'keccak256', 'nonzero_evidence_required': True}}}
