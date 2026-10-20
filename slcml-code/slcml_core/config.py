from dataclasses import dataclass

MODEL_SETTINGS = {
    'gpt': {'model': 'gpt-5', 'transport': 'openai', 'key_env': 'OPENAI_API_KEY',
            'url_env': 'OPENAI_BASE_URL', 'url': 'https://api.openai.com/v1',
            'parameters': {'reasoning_effort': 'medium'}},
    'claude': {'model': 'claude-sonnet-4-5-20250929', 'transport': 'anthropic',
               'key_env': 'ANTHROPIC_API_KEY', 'url_env': 'ANTHROPIC_BASE_URL',
               'url': 'https://api.anthropic.com',
               'parameters': {'temperature': 0.1, 'thinking': {'type': 'disabled'}}},
    'gemini': {'model': 'gemini-3.1-pro-preview', 'transport': 'gemini',
               'key_env': 'GEMINI_API_KEY', 'url_env': 'GEMINI_BASE_URL',
               'url': 'https://generativelanguage.googleapis.com/v1beta',
               'parameters': {'temperature': 0.9, 'thinkingConfig': {'thinkingLevel': 'high'}}},
}

TOKEN_LIMITS = {'socr': 8200, 'ir': 16384, 'solidity': 16384, 'runtime': 4196}
MODULES = ('intermediate_representation', 'structured_reasoning', 'schema_validation',
           'formal_checking', 'state_machine', 'audit_template')
CONFIGURATIONS = {'baseline': frozenset(), 'full': frozenset(MODULES)}
CONFIGURATIONS.update({'without_' + name: frozenset(MODULES) - {name} for name in MODULES})

@dataclass(frozen=True)
class RunSettings:
    timeout_seconds: int = 300
    maximum_attempts: int = 3
    retry_backoff_seconds: tuple = (3, 6)
    maximum_repairs: int = 1
    chunk_threshold: int = 6000
    stream: bool = True

