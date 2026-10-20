import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
from statistics import mean
import unicodedata

DIMENSIONS = ('S', 'O', 'C', 'R')
HEX = re.compile(r'^0x[0-9a-fA-F]{64}$')

def normalized(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(value))).strip().casefold()

def element_text(value):
    if isinstance(value, str):
        return value
    for field in ('text', 'natural_language_description', 'natural_language_expression', 'description', 'label'):
        if isinstance(value.get(field), str) and value[field].strip():
            return value[field]
    return json.dumps({k: v for k, v in value.items() if not k.endswith('_id') and k not in {'source_clause_index', 'segment_id'}},
                      sort_keys=True, ensure_ascii=False)

def rouge_l_f1(a, b):
    first, second = normalized(a).split(), normalized(b).split()
    if not first or not second:
        return 0.0
    previous = [0] * (len(second) + 1)
    for token in first:
        current = [0]
        for j, other in enumerate(second, 1):
            current.append(previous[j - 1] + 1 if token == other else max(previous[j], current[-1]))
        previous = current
    return 2 * previous[-1] / (len(first) + len(second))

def dimension_prf(predictions, references, threshold):
    if not 0 < threshold <= 1:
        raise ValueError('A fixed matching threshold in (0, 1] is required')
    edges = []
    for p in predictions:
        scores = [(j, rouge_l_f1(element_text(p), element_text(r))) for j, r in enumerate(references)]
        edges.append([j for j, score in sorted(scores, key=lambda pair: (-pair[1], pair[0])) if score >= threshold])
    assigned = {}
    def augment(i, visited):
        for j in edges[i]:
            if j in visited:
                continue
            visited.add(j)
            if j not in assigned or augment(assigned[j], visited):
                assigned[j] = i
                return True
        return False
    for i in range(len(predictions)):
        augment(i, set())
    tp = len(assigned)
    precision = tp / len(predictions) if predictions else 0.0
    recall = tp / len(references) if references else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {'precision': precision, 'recall': recall, 'f1': f1, 'tp': tp,
            'fp': len(predictions) - tp, 'fn': len(references) - tp,
            'matches': [{'prediction_index': i, 'reference_index': j} for j, i in sorted(assigned.items())]}

def valid_hash(value):
    return isinstance(value, str) and bool(HEX.fullmatch(value)) and int(value[2:], 16) != 0

def unique_records(rows, field):
    output = {}
    for row in rows:
        key = row[field]
        if key in output:
            raise ValueError('Duplicate ' + field)
        output[key] = row
    return output

def logic_consistency(required_ids, checks):
    if not required_ids or len(set(required_ids)) != len(required_ids):
        raise ValueError('A nonempty fixed logical-check list is required')
    actual = unique_records(checks, 'check_id')
    passed = sum(actual.get(key, {}).get('passed') is True for key in required_ids)
    return {'passed': passed, 'total': len(required_ids), 'value': passed / len(required_ids)}

def execution_position(event):
    keys = ('block_number', 'transaction_index', 'log_index')
    if not all(isinstance(event.get(k), int) and not isinstance(event.get(k), bool) and event[k] >= 0 for k in keys):
        return None
    return tuple(event[k] for k in keys)

def procedural_completeness(paths, events):
    unique_records(paths, 'path_id')
    passed = total = 0
    detail = []
    for path in paths:
        stages = path['stages']
        if not stages or len(set(stages)) != len(stages):
            raise ValueError('Invalid fixed procedural-stage list')
        selected = [e for e in events if e.get('path_id') == path['path_id']]
        previous = None
        prefix_valid = True
        for stage in stages:
            eligible = [e for e in selected if e.get('stage') == stage and e.get('triggered') is True
                        and e.get('transaction_success') is True and valid_hash(e.get('transaction_hash'))
                        and execution_position(e) is not None]
            positions = sorted(execution_position(e) for e in eligible)
            later = [position for position in positions if previous is None or position > previous]
            valid = prefix_valid and bool(later)
            if valid:
                previous = later[0]
                passed += 1
            else:
                prefix_valid = False
            total += 1
            detail.append({'path_id': path['path_id'], 'stage': stage, 'passed': valid})
    return {'passed': passed, 'total': total, 'value': passed / total if total else None, 'stages': detail}

def clause_id(value):
    return re.sub(r'^(?:Clause_|Clause\s+|Article\s+)', '', str(value), flags=re.I).strip()

def rule_clauses(elements):
    output = set()
    for item in elements.get('R', []):
        if isinstance(item, dict):
            value = item.get('source_clause_index', item.get('IndexClause'))
            if value:
                output.add(clause_id(value))
        else:
            output.update(m[1] for m in re.finditer(r'(?:Clause[_\s]+|Article\s+)(\d+(?:\.\d+)*)', item, re.I))
    return output

def audit_coverage(nodes, events, extracted_rule_clauses):
    if not nodes:
        raise ValueError('A nonempty fixed audit-node list is required')
    unique_records(nodes, 'node_id')
    passed = []
    for node in nodes:
        expected = {clause_id(x) for x in node['clause_indices']}
        covered = any(e.get('node_id') == node['node_id'] and e.get('event') == node['event']
                      and clause_id(e.get('clause_index', '')) in expected & extracted_rule_clauses
                      and valid_hash(e.get('evidence_hash')) and valid_hash(e.get('transaction_hash'))
                      and e.get('transaction_success') is True and execution_position(e) is not None
                      for e in events)
        passed.append({'node_id': node['node_id'], 'covered': covered})
    count = sum(item['covered'] for item in passed)
    return {'covered': count, 'total': len(nodes), 'value': count / len(nodes), 'nodes': passed}

def evaluate_contract(gold, observed, threshold):
    elements = observed.get('elements', {})
    dimensions = {d: dimension_prf(elements.get(d, []), gold['elements'][d], threshold) for d in DIMENSIONS}
    lc = logic_consistency(gold['logic_check_ids'], observed.get('logic_checks', []))
    pc = procedural_completeness(gold.get('procedure_paths', []), observed.get('procedure_events', []))
    ac = audit_coverage(gold['audit_nodes'], observed.get('audit_events', []), rule_clauses(elements))
    return {'Macro-F1': mean(dimensions[d]['f1'] for d in DIMENSIONS),
            'LC': lc['value'], 'PC': pc['value'], 'AC': ac['value'],
            'dimensions': dimensions, 'logic': lc, 'procedure': pc, 'audit': ac,
            'failures': observed.get('failures', []), 'human_review': observed.get('human_review')}

def evaluate_dataset(reference, runs, threshold):
    contracts = reference['contracts']
    if not contracts:
        raise ValueError('No fixed contract registry')
    groups = defaultdict(dict)
    for run in runs:
        if run['contract_id'] not in contracts:
            raise ValueError('Unknown contract_id')
        key = (run['model'], run['configuration'])
        if run['contract_id'] in groups[key]:
            raise ValueError('Duplicate model/configuration/contract record')
        groups[key][run['contract_id']] = run
    rows = []
    for (model, configuration), actual in sorted(groups.items()):
        for contract_id, gold in contracts.items():
            observed = actual.get(contract_id, {'failures': ['missing_run']})
            rows.append({'model': model, 'configuration': configuration, 'contract_id': contract_id,
                         'tier': gold['tier'], **evaluate_contract(gold, observed, threshold)})
    summary = []
    for key in groups:
        selected = [r for r in rows if (r['model'], r['configuration']) == key]
        for tier in ['Overall', *sorted({r['tier'] for r in selected})]:
            subset = selected if tier == 'Overall' else [r for r in selected if r['tier'] == tier]
            entry = {'model': key[0], 'configuration': key[1], 'tier': tier, 'contracts': len(subset),
                     'failed_contracts': sum(bool(r['failures']) for r in subset)}
            for metric in ('Macro-F1', 'LC', 'PC', 'AC'):
                values = [r[metric] for r in subset if r[metric] is not None]
                entry[metric] = mean(values) if values else None
                entry[metric + '_applicable_contracts'] = len(values)
            summary.append(entry)
    return {'matching_rule': 'one_to_one_maximum_cardinality_rouge_l_f1', 'threshold': threshold,
            'contracts': rows, 'summary': summary}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--runs', type=Path, required=True)
    parser.add_argument('--threshold', type=float, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text(encoding='utf-8-sig'))
    runs = json.loads(args.runs.read_text(encoding='utf-8-sig'))
    result = evaluate_dataset(reference, runs, args.threshold)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')

if __name__ == '__main__':
    main()

