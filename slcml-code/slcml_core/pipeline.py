import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from .adapters import invoke, InvocationError
from .config import CONFIGURATIONS, TOKEN_LIMITS, RunSettings
from .preprocessing import segment_contract, merge_elements, merge_ir
from .prompt_builder import build_prompt
from .validation import ACCEPTED, SCHEMA_PATH, validate

def sha256(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()

def parse_json(raw):
    text = raw.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.I)
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError('Nonfinite JSON number: ' + value)
    decoder = json.JSONDecoder(object_pairs_hook=unique_object, parse_constant=invalid_constant)
    value, end = decoder.raw_decode(text)
    if text[end:].strip() or not isinstance(value, dict):
        raise ValueError('Expected one JSON object')
    return value

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')

def generate_segment(segment, model, configuration, output, settings, caller=invoke):
    if settings.maximum_repairs not in (0, 1):
        raise ValueError('The revision budget must be zero or one')
    enabled = CONFIGURATIONS[configuration]
    messages = build_prompt(segment, enabled)
    task = 'ir' if 'intermediate_representation' in enabled else 'socr'
    record = {'segment_id': segment['segment_id'], 'model': model, 'configuration': configuration,
              'input_sha256': segment['input_sha256'], 'attempts': [], 'status': 'failed'}
    for revision in range(settings.maximum_repairs + 1):
        call_dir = output / f'revision_{revision}'
        call_dir.mkdir(parents=True, exist_ok=False)
        save(call_dir / 'messages.json', messages)
        try:
            response = caller(model, messages, TOKEN_LIMITS[task], settings)
        except InvocationError as exc:
            record.update(status='invocation_failed', failure_type=str(exc), communication_attempts=exc.attempts)
            break
        raw = response['text']
        (call_dir / 'response.txt').write_text(raw, encoding='utf-8')
        meta = {k: v for k, v in response.items() if k != 'text'}
        meta.update(prompt_sha256=sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True)), raw_sha256=sha256(raw))
        save(call_dir / 'invocation.json', meta)
        errors = []
        parsed = None
        try:
            parsed = parse_json(raw)
            save(call_dir / 'parsed.json', parsed)
            if configuration == 'baseline':
                if not all(isinstance(parsed.get(d), list) and all(isinstance(x, str) for x in parsed[d]) for d in ('S', 'O', 'C', 'R')):
                    raise ValueError('Missing SOCR arrays')
                checks = []
            else:
                checks = validate(parsed, enabled, segment.get('clause_ids', []))
            errors = [dict(e, module=c['module']) for c in checks for e in c['errors']]
            unknown = any(c['status'] == 'not_evaluable' for c in checks)
            finish = str(response.get('metadata', {}).get('finish_reason', '')).lower()
            if finish in {'length', 'max_tokens', 'max_tokens_exceeded'}:
                errors.append({'module': 'response', 'code': 'truncated', 'detail': 'output_limit_reached'})
            save(call_dir / 'checks.json', checks)
        except (ValueError, TypeError, KeyError) as exc:
            errors = [{'module': 'parser', 'code': type(exc).__name__, 'detail': 'invalid_json_or_output_shape'}]
            unknown = False
        record['attempts'].append({'revision': revision, 'errors': errors, 'not_evaluable': unknown,
                                   'raw_sha256': sha256(raw)})
        record['final_output'] = parsed
        if not errors:
            record['status'] = 'checks_incomplete' if unknown else 'completed'
            break
        if configuration == 'baseline' or revision == settings.maximum_repairs:
            record['status'] = 'validation_failed'
            break
        messages = [*messages, {'role': 'assistant', 'content': raw},
                    {'role': 'user', 'content': 'Revise the output using only these enabled-check diagnostics: ' + json.dumps(errors, ensure_ascii=False)}]
    save(output / 'workflow.json', record)
    return record

def run_contract(text, model, configuration, output, settings=None):
    settings = settings or RunSettings()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    segments = segment_contract(text, settings.chunk_threshold)
    save(output / 'inputs.json', segments)
    save(output / 'configuration.json', {'model': model, 'configuration': configuration,
        'enabled_modules': sorted(CONFIGURATIONS[configuration]), 'settings': asdict(settings),
        'schema_sha256': hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest(),
        'input_sha256': sha256(text), 'timestamp_utc': datetime.now(timezone.utc).isoformat()})
    records = [generate_segment(s, model, configuration, output / s['segment_id'], settings) for s in segments]
    successful = [r['final_output'] for r in records if r.get('final_output')]
    names = ('Subject', 'Object', 'Condition', 'Rule') if 'intermediate_representation' in CONFIGURATIONS[configuration] else ('S', 'O', 'C', 'R')
    save(output / 'merged_elements.json', merge_elements(successful, names))
    if names[0] == 'Subject' and len(successful) == len(records):
        try:
            combined = merge_ir(successful)
            save(output / 'merged_ir.json', combined)
            clauses = [clause for segment in segments for clause in segment.get('clause_ids', [])]
            combined_checks = validate(combined, CONFIGURATIONS[configuration], clauses)
            save(output / 'merged_checks.json', combined_checks)
            if any(check['status'] not in ACCEPTED for check in combined_checks):
                for record in records:
                    if record['status'] == 'completed':
                        record['status'] = 'merge_validation_failed'
        except ValueError as exc:
            save(output / 'merge_failure.json', {'error_type': type(exc).__name__, 'detail': str(exc)})
            for record in records:
                if record['status'] == 'completed':
                    record['status'] = 'merge_validation_failed'
    save(output / 'summary.json', {'segments': len(records), 'workflows': records,
        'complete': all(r['status'] == 'completed' for r in records)})
    return records

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--model', choices=('gpt', 'claude', 'gemini'), required=True)
    parser.add_argument('--configuration', choices=CONFIGURATIONS, default='full')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        parser.error('--execute is required for a model invocation')
    records = run_contract(args.input.read_text(encoding='utf-8-sig'), args.model, args.configuration, args.output)
    return 0 if all(r['status'] == 'completed' for r in records) else 1

if __name__ == '__main__':
    raise SystemExit(main())

