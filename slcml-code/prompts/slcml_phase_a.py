import json

from slcml_core.config import CONFIGURATIONS
from slcml_core.prompt_builder import build_prompt
from slcml_core.validation import ACCEPTED, load_schema, validate


PHASE_A_SYSTEM = build_prompt({'segment_id': 'SEG_001', 'target': ''}, CONFIGURATIONS['full'])[0]['content']
PHASE_A_TASK = 'Translate the supplied contract into the canonical SLCML 2.1.0 IR. Return one JSON object.'
PHASE_A_COT = ('Identify roles and objects; decompose conditions and exceptions; map rules and dependencies. '
               'Return concise structured decisions, not private reasoning traces.')
PHASE_A_CONSTRAINTS = ('Preserve source-clause bindings. Do not invent evidence, deadlines or legal effects. '
                       'Configured procedural defaults are not extracted contractual facts. '
                       'Ambiguous and unsupported predicates require review.')
PHASE_A_EXEMPLAR = ''
PHASE_A_SELF_CHECK = ('Check required fields, identifier uniqueness, source and dependency references, '
                     'applicable procedural paths, audit nodes and evidence-template mappings.')


def assemble_prompt(segment, enabled=None):
    return build_prompt(segment, CONFIGURATIONS['full'] if enabled is None else enabled)


def schema_description():
    return json.dumps(load_schema(), ensure_ascii=False, indent=2)


class PhaseAValidator:
    @staticmethod
    def validate(output, source_clauses=()):
        records = validate(output, CONFIGURATIONS['full'], source_clauses)
        failures = [str(dict(item, module=record['module']))
                    for record in records for item in record['errors'] + record['limitations']]
        return all(record['status'] in ACCEPTED for record in records), failures
