import json
from .validation import load_schema

BASELINE = ('Extract the subjects S, objects O, conditions C and rules R from the target contract. '
            'Return a JSON object with S, O, C and R arrays of extracted text. '
            'Preserve exceptions and source clause references. Context is read-only and is not an extraction target.')

def build_prompt(segment, enabled, task='ir', ir=None):
    if not enabled:
        instructions = BASELINE
    else:
        instructions = 'Analyze the target contractual clauses. Do not invent parties, facts, evidence or legal effects. '
        if 'intermediate_representation' in enabled:
            instructions += ('Return one JSON object with Subject, Object, Condition and Rule arrays and an Audit object. '
                             'Use subject_id, object_id, condition_id and rule_id as unique identifiers. '
                             'Retain source_clause_index on each element. Conditions carry predicate_components '
                             '(left_operand, operator, right_operand, operand_type). Rules carry trigger_condition_ids, '
                             'trigger_condition_logic (ALL, ANY, ON_FAILURE or UNCONDITIONAL), target_subject and target_object. '
                             'Use the canonical schema_version 2.1.0. All references must use declared identifiers. '
                             'Use constraint_group only for predicates that must hold jointly in the same context. ')
        else:
            instructions += 'Return S, O, C and R arrays of extracted text without a quintuple intermediate representation. '
        if 'structured_reasoning' in enabled:
            instructions += ('Resolve roles and objects, then decompose conditions and exceptions, then map obligations '
                             'and responsibility dependencies. Return concise structured decisions, not hidden reasoning. ')
        if 'schema_validation' in enabled:
            instructions += 'Check field types, identifier uniqueness and all references against the source clauses. '
        if 'formal_checking' in enabled:
            instructions += 'Express numeric predicates and rule dependencies explicitly for external consistency checking. '
        if 'state_machine' in enabled:
            instructions += ('Represent breach paths with state_machine_transition containing from_state, intermediate_states '
                             'and possible_end_states. Preserve Frozen before Challenge before final disposition. '
                             'Represent challenge_window_seconds inside procedural_justice.challenge_phase. '
                             'For applicable breach paths include freeze_phase, challenge_phase and adjudication_phase, '
                             'eligible_challengers, deadline_inclusive, a designated authority and both decision outcomes. '
                             'Timeout closure must require no challenge submission. Link each breach rule to a '
                             'dispute_unit_template_id and declare finality and restricted-recovery parameters with their basis. '
                             'Do not invent deadlines or claim configured defaults came from the contract; '
                             'use null and review flags for unresolved values. ')
        if 'audit_template' in enabled:
            instructions += ('Link Audit.evidence_templates to rules using associated_rule_id and to key_execution_nodes '
                             'using node_id. Include all four template layers, clause_index_registry, judicial_log_schema '
                             'with explicit field_roles, and audit_trail_requirements. Each key execution node must '
                             'support an event, the source clause index and a nonzero evidence hash. '
                             'A template declaration does not establish that its event has executed. ')
    if task == 'solidity':
        instructions = ('Generate Solidity using the verified IR as the normative source and the original text as '
                        'read-only context. Preserve conditions, permissions, state paths and audit fields. '
                        'If the text and IR conflict, return a JSON object with semantic_conflicts instead of '
                        'silently resolving the conflict. Otherwise return Solidity code only.')
    if task == 'runtime':
        instructions = ('Analyze the supplied execution events using read-only IR. Return structured dispute-unit '
                        'recommendations with event references, reasons and review flags. Do not modify the IR '
                        'or invoke on-chain actions. Do not infer legal validity from traceability.')
    payload = {'segment_id': segment['segment_id'], 'context_only': segment.get('context_only', ''),
               'target_clauses': segment['target'], 'source_clause_ids': segment.get('clause_ids', [])}
    if ir is not None:
        payload['verified_ir'] = ir
    if task == 'ir' and 'intermediate_representation' in enabled:
        payload['output_schema'] = load_schema()
        payload['enabled_checks'] = sorted(enabled)
        instructions += (' The schema defines the canonical field vocabulary. For disabled state-machine or audit-template '
                         'modules, do not add their procedural structures or templates merely to imitate a complete workflow; '
                         'their optional fields may be omitted and Audit may be empty when audit templates are disabled. '
                         'Use predicate_components=null with a review reason if a condition is not representable; '
                         'never replace it with an invented numeric predicate. Return no surrounding Markdown. ')
    return [{'role': 'system', 'content': instructions},
            {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]

