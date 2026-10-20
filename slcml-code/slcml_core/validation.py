import argparse
from collections import Counter
from functools import lru_cache
import json
import math
from pathlib import Path
import re
from string import Formatter

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ELEMENTS = ('Subject', 'Object', 'Condition', 'Rule')
IDS = ('subject_id', 'object_id', 'condition_id', 'rule_id')
SCHEMA_PATH = Path(__file__).resolve().parents[1] / 'schemas' / 'slcml.schema.json'
ACCEPTED = {'passed', 'not_applicable'}


def clause_id(value):
    return re.sub(r'^(?:Clause_|Clause\s+|Article\s+)', '', str(value), flags=re.I).strip()


@lru_cache(maxsize=1)
def load_schema():
    schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    return schema


def diagnostic(code, detail, path='IR'):
    return {'code': code, 'detail': str(detail), 'path': path}


def outcome(errors=(), limitations=(), checked=0):
    return {'errors': list(errors), 'limitations': list(limitations), 'checked_items': checked}


def structural_errors(value, definition=None, path='IR'):
    schema = load_schema()
    if definition:
        schema = {'$ref': '#/$defs/' + definition, '$defs': schema['$defs']}
    return [diagnostic('json_schema', error.message,
                       path + ''.join(f'[{x}]' if isinstance(x, int) else '.' + x for x in error.absolute_path))
            for error in sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: str(list(e.absolute_path)))]


def full_structure_errors(value):
    schema = json.loads((SCHEMA_PATH.parent / 'slcml.full.schema.json').read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    base = load_schema()
    registry = Registry().with_resource(base['$id'], Resource.from_contents(base))
    return [diagnostic('full_profile_schema', error.message,
                       'IR' + ''.join(f'[{x}]' if isinstance(x, int) else '.' + x for x in error.absolute_path))
            for error in Draft202012Validator(schema, registry=registry).iter_errors(value)]


def duplicate_errors(items, key, path):
    counts = Counter(item.get(key) for item in items)
    return [diagnostic('duplicate_identifier', value, path + '.' + key)
            for value, count in sorted(counts.items(), key=lambda x: str(x[0])) if count > 1]


def _finite_errors(value, path='IR'):
    if isinstance(value, float) and not math.isfinite(value):
        yield diagnostic('nonfinite_number', 'NaN and infinity are not valid IR numbers', path)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _finite_errors(item, path + '.' + key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _finite_errors(item, f'{path}[{index}]')


def schema_checks(ir, source_clauses):
    errors = structural_errors(ir)
    if errors:
        return outcome(errors)
    registries = {}
    for name, key in zip(ELEMENTS, IDS):
        errors.extend(duplicate_errors(ir[name], key, 'IR.' + name))
        registries[key] = {item[key] for item in ir[name]}
    templates = ir.get('dispute_unit_templates', [])
    errors.extend(duplicate_errors(templates, 'template_id', 'IR.dispute_unit_templates'))
    registries['dispute_unit_template_id'] = {item['template_id'] for item in templates}
    identifiers = [item[key] for name, key in zip(ELEMENTS, IDS) for item in ir[name]]
    identifiers.extend(item['template_id'] for item in templates)
    identifiers.extend(item['template_id'] for item in ir['Audit'].get('evidence_templates', []))
    identifiers.extend(item['node_id'] for item in ir['Audit'].get('key_execution_nodes', []))
    for identifier, count in Counter(identifiers).items():
        if count > 1:
            errors.append(diagnostic('identifier_namespace_collision', identifier))
    reference_fields = {
        'target_subject': 'subject_id', 'owner_subject_id': 'subject_id',
        'authority_subject_id': 'subject_id', 'eligible_challengers': 'subject_id',
        'subject_ids': 'subject_id', 'target_object': 'object_id', 'object_ids': 'object_id',
        'trigger_condition_ids': 'condition_id', 'depends_on': 'condition_id',
        'associated_rule_id': 'rule_id', 'rule_ids': 'rule_id',
        'depends_on_rule_ids': 'rule_id', 'dispute_unit_template_id': 'dispute_unit_template_id'
    }
    allowed = {clause_id(x) for x in source_clauses}

    def visit(value, path):
        if isinstance(value, dict):
            for key, item in value.items():
                current = path + '.' + key
                if key in {'source_clause_index', 'clause_index'} and allowed and clause_id(item) not in allowed:
                    errors.append(diagnostic('unknown_clause', item, current))
                if key in reference_fields:
                    for identifier in item if isinstance(item, list) else [item]:
                        if identifier not in registries[reference_fields[key]]:
                            errors.append(diagnostic('unknown_reference', identifier, current))
                if key not in {'metadata', 'field_roles'}:
                    visit(item, current)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f'{path}[{index}]')
    visit(ir, 'IR')
    return outcome(errors, checked=sum(len(ir[name]) for name in ELEMENTS))


def _cycle_errors(items, id_key, dependency_key, path):
    graph = {item[id_key]: item.get(dependency_key, []) for item in items}
    errors, visiting, visited = [], set(), set()

    def visit(identifier):
        if identifier in visiting:
            errors.append(diagnostic('dependency_cycle', identifier, path))
            return
        if identifier in visited:
            return
        visiting.add(identifier)
        for dependency in graph.get(identifier, []):
            if dependency not in graph:
                errors.append(diagnostic('unknown_dependency', dependency, path))
            else:
                visit(dependency)
        visiting.remove(identifier)
        visited.add(identifier)
    for identifier in graph:
        visit(identifier)
    return errors


def formal_checks(ir):
    from z3 import And, Bool, BoolVal, Int, IntVal, Not, Or, Real, RealVal, Solver, String, StringVal, sat, unsat
    errors, limitations, checked = [], [], 0
    conditions = ir['Condition']
    errors.extend(_cycle_errors(conditions, 'condition_id', 'depends_on', 'IR.Condition'))
    errors.extend(_cycle_errors(ir['Rule'], 'rule_id', 'depends_on_rule_ids', 'IR.Rule'))
    expressions, types, groups = {}, {}, {}
    for index, condition in enumerate(conditions):
        path = f'IR.Condition[{index}]'
        components = condition.get('predicate_components')
        if components is None:
            limitations.append(diagnostic('unsupported_predicate', 'No machine-readable predicate; review required', path))
            continue
        malformed = structural_errors(components, 'predicate', path + '.predicate_components')
        if malformed:
            errors.extend(malformed)
            continue
        name, op, value, kind = (components[k] for k in ('left_operand', 'operator', 'right_operand', 'operand_type'))
        if kind == 'set':
            literal_types = {type(x) for x in value}
            if literal_types <= {int, float}:
                kind = 'number'
            elif literal_types == {str}:
                kind = 'string'
            elif literal_types == {bool}:
                kind = 'boolean'
            else:
                errors.append(diagnostic('heterogeneous_set', name, path))
                continue
        signature = (kind, components.get('unit'))
        if name in types and types[name] != signature:
            errors.append(diagnostic('inconsistent_operand_type_or_unit', name, path))
            continue
        types[name] = signature
        constructor, literal = {'number': (Real, RealVal), 'integer': (Int, IntVal),
                                'boolean': (Bool, BoolVal), 'string': (String, StringVal)}[kind]
        variable = constructor(name)

        def encode(item):
            return literal(str(item)) if kind in {'number', 'integer'} else literal(item)
        if op in {'in', 'not_in'}:
            expression = Or(*[variable == encode(x) for x in value])
            if op == 'not_in':
                expression = Not(expression)
        else:
            right = encode(value)
            if op == '<': expression = variable < right
            elif op == '<=': expression = variable <= right
            elif op == '>': expression = variable > right
            elif op == '>=': expression = variable >= right
            elif op == '==': expression = variable == right
            else: expression = variable != right
        expressions[condition['condition_id']] = expression
        if condition.get('constraint_group'):
            groups.setdefault(condition['constraint_group'], []).append(expression)
        checked += 1

    def dependencies(identifier, seen=None):
        seen = set() if seen is None else seen
        if identifier in seen:
            return []
        seen.add(identifier)
        condition = next((c for c in conditions if c['condition_id'] == identifier), None)
        return [identifier, *[x for d in condition.get('depends_on', []) for x in dependencies(d, seen)]] if condition else [identifier]

    for rule in ir['Rule']:
        ids = rule.get('trigger_condition_ids', [])
        logic = rule.get('trigger_condition_logic', 'ALL')
        if logic == 'UNCONDITIONAL':
            if ids:
                errors.append(diagnostic('unconditional_with_triggers', rule['rule_id']))
            continue
        if not ids:
            errors.append(diagnostic('missing_trigger', rule['rule_id']))
            continue
        branches = [dependencies(identifier) for identifier in ids]
        if any(identifier not in expressions for branch in branches for identifier in branch):
            limitations.append(diagnostic('incomplete_rule_predicate', rule['rule_id']))
            continue
        terms = [And(*[expressions[x] for x in branch]) for branch in branches]
        if logic == 'ALL': expression = And(*terms)
        elif logic == 'ANY': expression = Or(*terms)
        elif logic == 'ON_FAILURE':
            guards = [expressions[x] for branch in branches for x in branch[1:]]
            expression = And(*guards, Not(And(*[expressions[x] for x in ids])))
        else:
            errors.append(diagnostic('unsupported_trigger_logic', logic))
            continue
        groups['rule:' + rule['rule_id']] = [expression]
    for group, terms in groups.items():
        solver = Solver()
        solver.set(timeout=2000)
        solver.add(*terms)
        status = solver.check()
        if status == unsat:
            errors.append(diagnostic('unsatisfiable_constraints', group))
        elif status != sat:
            limitations.append(diagnostic('solver_unknown', group))
        checked += 1
    for index, obj in enumerate(ir['Object']):
        attributes = obj.get('quantifiable_attributes', {})
        total, remaining = attributes.get('privacy_budget_total'), attributes.get('privacy_budget_remaining')
        if total is not None:
            if isinstance(total, bool) or not isinstance(total, (int, float)) or total < 0:
                errors.append(diagnostic('invalid_total_budget', obj['object_id'], f'IR.Object[{index}]'))
            checked += 1
        if remaining is not None:
            if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in (remaining, total)) or not 0 <= remaining <= total:
                errors.append(diagnostic('budget_interval', obj['object_id'], f'IR.Object[{index}]'))
            checked += 1
    return outcome(errors, limitations, checked)


def _state(name):
    return name[2:] if name.startswith('S_') else name


def requires_procedure(rule):
    targets = rule.get('state_machine_transition', {}).get('possible_end_states', [])
    return (any(_state(x) == 'Breach' for x in targets) or rule.get('rule_type') == 'Penalty'
            or bool(rule.get('breach_classification')))


def state_machine_checks(ir):
    errors, limitations, checked = [], [], 0
    subjects = {item['subject_id'] for item in ir['Subject']}
    templates = {item['template_id']: item for item in ir.get('dispute_unit_templates', [])}
    for index, rule in enumerate(ir['Rule']):
        path = f'IR.Rule[{index}]'
        transition = rule.get('state_machine_transition')
        if transition is not None:
            invalid = structural_errors(transition, 'transition', path + '.state_machine_transition')
            errors.extend(invalid)
            if invalid:
                continue
        if not requires_procedure(rule):
            continue
        checked += 1
        if transition is None:
            errors.append(diagnostic('missing_state_transition', rule['rule_id'], path))
            continue
        stages = [_state(x) for x in transition['intermediate_states']]
        targets = {_state(x) for x in transition['possible_end_states']}
        route = [_state(transition['from_state']), *stages]
        if not any(x in stages for x in ('Frozen', 'Suspended')) or 'Challenge' not in stages:
            errors.append(diagnostic('missing_procedural_stage', rule['rule_id'], path))
        elif min(stages.index(x) for x in ('Frozen', 'Suspended') if x in stages) > stages.index('Challenge'):
            errors.append(diagnostic('procedural_order', rule['rule_id'], path))
        if len(set(route)) != len(route) or 'Breach' in route:
            errors.append(diagnostic('invalid_procedural_route', rule['rule_id'], path))
        if 'Breach' not in targets or not targets & {'Restored', 'Active', 'Resolved', 'Restricted'}:
            errors.append(diagnostic('missing_disposition_branch', rule['rule_id'], path))
        procedure = rule.get('procedural_justice')
        invalid = structural_errors(procedure, 'procedure', path + '.procedural_justice')
        errors.extend(invalid)
        if invalid:
            continue
        challenge, decision = procedure['challenge_phase'], procedure['adjudication_phase']
        if challenge['challenge_window_seconds'] is None:
            limitations.append(diagnostic('unresolved_challenge_window', rule['rule_id'], path))
        for identifier in challenge['eligible_challengers'] + [decision['adjudication_authority']['authority_subject_id']]:
            if identifier not in subjects:
                errors.append(diagnostic('unknown_procedural_subject', identifier, path))
        outcomes = decision['adjudication_outcomes']
        if len({x['outcome_type'] for x in outcomes}) != len(outcomes):
            errors.append(diagnostic('duplicate_outcome', rule['rule_id'], path))
        if {_state(x['next_state']) for x in outcomes} != targets:
            errors.append(diagnostic('outcome_state_mismatch', rule['rule_id'], path))
        if decision['default_outcome_on_timeout'] not in {x['outcome_type'] for x in outcomes}:
            errors.append(diagnostic('unknown_timeout_outcome', rule['rule_id'], path))
        template = templates.get(rule.get('dispute_unit_template_id'))
        invalid = structural_errors(template, 'disputeUnit', path + '.dispute_unit_template')
        errors.extend(invalid)
        if not invalid:
            if rule['rule_id'] not in template['rule_ids']:
                errors.append(diagnostic('dispute_template_rule_mismatch', rule['rule_id'], path))
            if template['parameter_basis'] == 'Unresolved':
                limitations.append(diagnostic('unresolved_finality_parameters', template['template_id'], path))
    return outcome(errors, limitations, checked)


def audit_checks(ir):
    audit = ir.get('Audit')
    errors = structural_errors(audit, 'completeAudit', 'IR.Audit')
    if errors:
        return outcome(errors)
    templates, nodes = audit['evidence_templates'], audit['key_execution_nodes']
    errors.extend(duplicate_errors(templates, 'template_id', 'IR.Audit.evidence_templates'))
    errors.extend(duplicate_errors(nodes, 'node_id', 'IR.Audit.key_execution_nodes'))
    registry = audit['clause_index_registry']
    errors.extend(duplicate_errors(registry, 'clause_index', 'IR.Audit.clause_index_registry'))
    registered = {item['clause_index'] for item in registry}
    rules = {item['rule_id']: item for item in ir['Rule']}
    by_node = {item['node_id']: item for item in nodes}
    log = audit['judicial_log_schema']
    fields = set(log['required_fields'])
    roles = list(log['field_roles'].values())
    if not set(roles) <= fields or len(set(roles)) != len(roles):
        errors.append(diagnostic('invalid_log_field_roles', 'Semantic field roles must resolve to distinct required event fields'))
    for name in ELEMENTS:
        for item in ir[name]:
            if item.get('source_clause_index') not in registered:
                errors.append(diagnostic('unregistered_clause', item.get('source_clause_index'), 'IR.' + name))
    layers = {item['template_layer'] for item in templates}
    if layers != {'FactStatement', 'BreachIdentification', 'ProceduralRecord', 'JudicialSummary'}:
        errors.append(diagnostic('incomplete_audit_layers', ','.join(sorted(layers))))
    for index, template in enumerate(templates):
        path = f'IR.Audit.evidence_templates[{index}]'
        rule, node = rules.get(template['associated_rule_id']), by_node.get(template['node_id'])
        if rule is None or node is None:
            errors.append(diagnostic('unknown_template_reference', template['template_id'], path))
        elif rule['rule_id'] not in node['rule_ids']:
            errors.append(diagnostic('template_node_rule_mismatch', template['template_id'], path))
        slots = re.findall(r'\{[A-Za-z][A-Za-z0-9_]*\}', template['template_content'])
        try:
            for _, field, spec, conversion in Formatter().parse(template['template_content']):
                if field is not None and (not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', field) or spec or conversion):
                    errors.append(diagnostic('unsupported_template_expression', field, path))
        except ValueError:
            errors.append(diagnostic('malformed_template_braces', template['template_id'], path))
        mappings = template['placeholder_mappings']
        if set(slots) != {x['placeholder'] for x in mappings}:
            errors.append(diagnostic('placeholder_mapping_mismatch', template['template_id'], path))
        errors.extend(duplicate_errors(mappings, 'placeholder', path + '.placeholder_mappings'))
        if any(x['data_source'] not in fields for x in mappings):
            errors.append(diagnostic('unknown_event_field', template['template_id'], path))
    for index, node in enumerate(nodes):
        path = f'IR.Audit.key_execution_nodes[{index}]'
        if node['event'] != log['log_event_name'] or node['clause_index'] not in registered:
            errors.append(diagnostic('invalid_audit_node_anchor', node['node_id'], path))
        for identifier in node['rule_ids']:
            if identifier not in rules:
                errors.append(diagnostic('unknown_node_rule', identifier, path))
            else:
                rule = rules[identifier]
                clause_indices = {rule.get('source_clause_index')}
                clause_indices.update(c.get('source_clause_index') for c in ir['Condition']
                                      if c['condition_id'] in rule.get('trigger_condition_ids', []))
                if node['clause_index'] not in clause_indices:
                    errors.append(diagnostic('node_rule_clause_mismatch', identifier, path))
            if not any(t['node_id'] == node['node_id'] and t['associated_rule_id'] == identifier for t in templates):
                errors.append(diagnostic('missing_node_rule_template', identifier, path))
    for rule in ir['Rule']:
        covered = {node['phase'] for node in nodes if rule['rule_id'] in node['rule_ids']}
        if not covered:
            errors.append(diagnostic('missing_rule_audit_node', rule['rule_id']))
        if requires_procedure(rule) and not {'Frozen', 'Challenge', 'Adjudication'} <= covered:
            errors.append(diagnostic('incomplete_procedural_audit_nodes', rule['rule_id']))
    return outcome(errors, checked=len(nodes) + len(templates))


CHECKERS = {'schema_validation': schema_checks, 'formal_checking': formal_checks,
            'state_machine': state_machine_checks, 'audit_template': audit_checks}


def validate(ir, enabled, source_clauses=()):
    records = []
    for name, checker in CHECKERS.items():
        if name not in enabled:
            continue
        if not isinstance(ir, dict):
            result = outcome([diagnostic('invalid_ir_type', 'Expected a JSON object')])
        elif any(k in ir for k in ('S', 'O', 'C', 'R')) and not all(k in ir for k in ELEMENTS):
            records.append({'module': name, 'status': 'not_evaluable', **outcome(limitations=[diagnostic('extraction_only', 'SOCR text arrays are not a compilable IR')])})
            continue
        elif name != 'schema_validation' and not all(isinstance(ir.get(k), list) and all(isinstance(x, dict) and isinstance(x.get(key), str) for x in ir[k]) for k, key in zip(ELEMENTS, IDS)):
            records.append({'module': name, 'status': 'not_evaluable', **outcome(limitations=[diagnostic('invalid_ir_shape', 'Required IR collections or identifiers are unavailable')])})
            continue
        else:
            try:
                nonfinite = list(_finite_errors(ir))
                result = outcome(nonfinite) if nonfinite else checker(ir, source_clauses) if name == 'schema_validation' else checker(ir)
            except Exception as exc:
                result = outcome([diagnostic('check_execution_failed', type(exc).__name__)])
        status = ('failed' if result['errors'] else 'not_evaluable' if result['limitations']
                  else 'passed' if result['checked_items'] else 'not_applicable')
        records.append({'module': name, 'status': status, **result})
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ir', type=Path, required=True)
    parser.add_argument('--source-clauses', type=Path)
    parser.add_argument('--modules', nargs='+', choices=CHECKERS, default=list(CHECKERS))
    args = parser.parse_args()
    clauses = json.loads(args.source_clauses.read_text(encoding='utf-8')) if args.source_clauses else []
    records = validate(json.loads(args.ir.read_text(encoding='utf-8')), set(args.modules), clauses)
    print(json.dumps(records, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if records and all(x['status'] in ACCEPTED for x in records) else 1


if __name__ == '__main__':
    raise SystemExit(main())
