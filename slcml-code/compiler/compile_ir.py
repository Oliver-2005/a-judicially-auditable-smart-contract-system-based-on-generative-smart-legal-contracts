import argparse
import json
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from slcml_core.validation import ACCEPTED, full_structure_errors, validate

def compile_ir(ir, template, output, context=None):
    structural = full_structure_errors(ir)
    if structural:
        raise ValueError(json.dumps(structural, ensure_ascii=False))
    checks = validate(ir, {'schema_validation', 'formal_checking', 'state_machine', 'audit_template'})
    if any(c['status'] not in ACCEPTED for c in checks):
        raise ValueError(json.dumps(checks, ensure_ascii=False))
    context = dict(context or {})
    params = ir.get('metadata', {}).get('case_parameters', {})
    for source, target in [('nominal_laser_power_w', 'nominal_power'),
                           ('nominal_scan_speed_mm_s', 'nominal_speed'),
                           ('oxygen_upper_bound_ppm_exclusive', 'oxygen_upper_bound'),
                           ('challenge_window_seconds', 'challenge_window')]:
        if source in params:
            context[target] = params[source]
    template = Path(template)
    env = Environment(loader=FileSystemLoader(str(template.parent)), undefined=StrictUndefined,
                      autoescape=False, keep_trailing_newline=True)
    source = env.get_template(template.name).render(ir=ir, **context)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(source, encoding='utf-8')
    return checks

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ir', type=Path, required=True)
    parser.add_argument('--template', type=Path, required=True)
    parser.add_argument('--context', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    context = json.loads(args.context.read_text(encoding='utf-8')) if args.context else None
    compile_ir(json.loads(args.ir.read_text(encoding='utf-8')), args.template, args.output, context)

if __name__ == '__main__':
    main()

