import hashlib
import copy
import json
import re
import unicodedata

CLAUSE = re.compile(r'^\s*(?:(?:Article|Clause|Section)\s+|第)?(\d+(?:\.\d+)*)(?:[\s.、:：条—-]|$)', re.I)
REFERENCE = re.compile(r'\b(?:Article|Clause|Section)\s+(\d+(?:\.\d+)*)\b', re.I)

def normalize(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value)).strip()

def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()

def segment_contract(text, threshold=6000):
    if threshold <= 0 or not text.strip():
        raise ValueError('Nonempty input and a positive threshold are required')
    starts = [m.start() for m in re.finditer(r'(?m)^.*$', text)
              if CLAUSE.match(m.group())]
    starts = sorted(set([0, *starts, len(text)]))
    units = [(a, b, text[a:b]) for a, b in zip(starts, starts[1:]) if text[a:b].strip()]
    if len(starts) == 2:
        units = [(m.start(), m.end(), m.group()) for m in re.finditer(r'[^\n]+(?:\n|$)', text)]
    groups = []
    current = []
    for unit in units:
        if current and sum(len(x[2]) for x in current) + len(unit[2]) > threshold:
            groups.append(current)
            current = []
        current.append(unit)
    if current:
        groups.append(current)
    definitions = text[:starts[1]].strip() if len(starts) > 2 else ''
    registry = {}
    for _, _, body in units:
        m = CLAUSE.match(body)
        if m:
            registry[m[1]] = body
    output = []
    for index, group in enumerate(groups, 1):
        body = ''.join(x[2] for x in group)
        local_ids = [m[1] for line in body.splitlines() if (m := CLAUSE.match(line))]
        referenced = {m[1] for m in REFERENCE.finditer(body)} - set(local_ids)
        context = [definitions] if len(groups) > 1 and definitions and group[0][0] > 0 else []
        context.extend(registry[x] for x in sorted(referenced) if x in registry)
        output.append({'segment_id': f'SEG_{index:03d}', 'start': group[0][0],
                       'end': group[-1][1], 'target': body, 'clause_ids': local_ids,
                       'context_only': '\n\n'.join(context), 'input_sha256': digest(body)})
    return output

def merge_elements(outputs, names=('Subject', 'Object', 'Condition', 'Rule')):
    merged = {name: [] for name in names}
    seen = {name: set() for name in names}
    for output in outputs:
        for name in names:
            for item in output.get(name, []):
                if isinstance(item, dict):
                    clause = item.get('source_clause_index', item.get('IndexClause', ''))
                    text = item.get('natural_language_description', item.get('natural_language_expression', item.get('text', item.get('label', ''))))
                    key = (normalize(str(clause)), normalize(str(text)))
                    if not key[1]:
                        import json
                        key = (key[0], json.dumps(item, ensure_ascii=False, sort_keys=True))
                else:
                    key = ('', normalize(str(item)))
                if key not in seen[name]:
                    merged[name].append(item)
                    seen[name].add(key)
    return merged

def merge_ir(outputs):
    names = ('Subject', 'Object', 'Condition', 'Rule')
    fields = ('subject_id', 'object_id', 'condition_id', 'rule_id')
    result = {name: [] for name in names}
    result['Audit'] = {'evidence_templates': [], 'clause_index_registry': [], 'key_execution_nodes': []}
    aliases = []
    seen = {name: {} for name in names}
    references = {'target_subject', 'target_object', 'associated_rule', 'associated_rule_id',
                  'owner_subject_id', 'trigger_condition_ids', 'condition_refs',
                  'subject_id', 'object_id', 'condition_id', 'rule_id', 'depends_on',
                  'depends_on_rule_ids', 'eligible_challengers', 'authority_subject_id',
                  'rule_ids', 'subject_ids', 'object_ids', 'dispute_unit_template_id',
                  'node_id', 'template_id'}
    def key(item, field, mapping):
        def canonical(value, current=None):
            if isinstance(value, dict):
                return {k: canonical(v, k) for k, v in value.items()}
            if isinstance(value, list):
                return [canonical(v, current) for v in value]
            if isinstance(value, str):
                return mapping.get(value, value) if current in references else normalize(value)
            return value
        return json.dumps(canonical({k: v for k, v in item.items() if k not in {field, 'segment_id'}}), ensure_ascii=False, sort_keys=True)
    for index, output in enumerate(outputs):
        mapping = {}
        for group, field in [(output.get('dispute_unit_templates', []), 'template_id'),
                             (output.get('Audit', {}).get('key_execution_nodes', []), 'node_id'),
                             (output.get('Audit', {}).get('evidence_templates', []), 'template_id')]:
            for item in group:
                identifier = item[field]
                mapping[identifier] = f'SEG_{index + 1:03d}__{identifier}' if len(outputs) > 1 else identifier
        for name, field in zip(names, fields):
            for item in output.get(name, []):
                signature = key(item, field, mapping)
                if signature in seen[name]:
                    mapping[item[field]] = seen[name][signature]
                else:
                    identifier = f'SEG_{index + 1:03d}__{item[field]}' if len(outputs) > 1 else item[field]
                    seen[name][signature] = identifier
                    mapping[item[field]] = identifier
        aliases.append(mapping)
    def rewrite(value, mapping, field=None):
        if isinstance(value, dict):
            return {k: rewrite(v, mapping, k) for k, v in value.items()}
        if isinstance(value, list):
            return [rewrite(v, mapping, field) for v in value]
        return mapping.get(value, value) if field in references and isinstance(value, str) else value
    for index, output in enumerate(outputs):
        mapping = aliases[index]
        for name, field in zip(names, fields):
            current_ids = {item[field] for item in result[name]}
            for item in output.get(name, []):
                value = rewrite(copy.deepcopy(item), mapping)
                if value[field] not in current_ids:
                    result[name].append(value)
                    current_ids.add(value[field])
        for item in output.get('Audit', {}).get('evidence_templates', []):
            value = rewrite(copy.deepcopy(item), mapping)
            if value not in result['Audit']['evidence_templates']:
                result['Audit']['evidence_templates'].append(value)
        for item in output.get('Audit', {}).get('key_execution_nodes', []):
            result['Audit']['key_execution_nodes'].append(rewrite(copy.deepcopy(item), mapping))
        for item in output.get('dispute_unit_templates', []):
            result.setdefault('dispute_unit_templates', []).append(rewrite(copy.deepcopy(item), mapping))
        for item in output.get('Audit', {}).get('clause_index_registry', []):
            for existing in result['Audit']['clause_index_registry']:
                if existing.get('clause_index') == item.get('clause_index') and existing != item:
                    raise ValueError('Conflicting clause registry entry: ' + item['clause_index'])
            if item not in result['Audit']['clause_index_registry']:
                result['Audit']['clause_index_registry'].append(copy.deepcopy(item))
        for field, value in output.get('Audit', {}).items():
            if field not in {'evidence_templates', 'clause_index_registry', 'key_execution_nodes'}:
                if field in result['Audit'] and result['Audit'][field] != value:
                    raise ValueError('Conflicting audit definition: ' + field)
                result['Audit'][field] = copy.deepcopy(value)
        for field in ('schema_version', 'contract_id'):
            if field in output:
                if field in result and result[field] != output[field]:
                    raise ValueError('Conflicting IR header: ' + field)
                result[field] = output[field]
        metadata = output.get('metadata', {})
        if metadata:
            merged = result.setdefault('metadata', {})
            for field, value in metadata.items():
                if field in merged and merged[field] != value:
                    raise ValueError('Conflicting cross-segment metadata: ' + field)
                merged[field] = copy.deepcopy(value)
    return result

