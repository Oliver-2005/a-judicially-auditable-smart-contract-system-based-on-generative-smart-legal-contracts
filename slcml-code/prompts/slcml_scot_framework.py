import copy

from slcml_core.config import CONFIGURATIONS
from slcml_core.preprocessing import digest
from slcml_core.prompt_builder import build_prompt
from slcml_core.validation import ACCEPTED, load_schema, validate


class SLCMLPromptFramework:
    OUTPUT_SCHEMA = load_schema()

    @classmethod
    def assemble_prompt(cls, contract_text: str) -> list:
        segment = {'segment_id': 'SEG_001', 'target': contract_text,
                   'input_sha256': digest(contract_text), 'clause_ids': []}
        return build_prompt(segment, CONFIGURATIONS['full'])

    @classmethod
    def get_schema_description(cls) -> dict:
        return copy.deepcopy(load_schema())

    @classmethod
    def validate_output_structure(cls, output: dict) -> dict:
        records = validate(output, {'schema_validation'})
        return {'valid': all(x['status'] in ACCEPTED for x in records),
                'errors': [str(e) for x in records for e in x['errors']],
                'warnings': [str(e) for x in records for e in x['limitations']]}
