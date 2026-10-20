import copy
import json
import os
import time
from urllib.parse import urlparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import requests
from .config import MODEL_SETTINGS, RunSettings

class InvocationError(RuntimeError):
    def __init__(self, kind, attempts):
        super().__init__(kind)
        self.attempts = attempts

def request_spec(model_name, messages, limit, settings=None):
    settings = settings or RunSettings()
    model = copy.deepcopy(MODEL_SETTINGS[model_name])
    transport = os.getenv(model_name.upper() + '_TRANSPORT', model['transport'])
    base = os.getenv(model['url_env'], model['url']).rstrip('/')
    key = os.getenv(model['key_env'])
    if not key:
        raise InvocationError('missing_api_key', [])
    headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key}
    system = '\n\n'.join(m['content'] for m in messages if m['role'] == 'system')
    body = [m for m in messages if m['role'] != 'system']
    if transport == 'openai':
        endpoint = base + '/chat/completions'
        params = {'reasoning_effort': 'medium'} if model_name == 'gpt' else {'temperature': model['parameters']['temperature']}
        if model_name == 'gemini':
            params['reasoning_effort'] = 'high'
        payload = {'model': model['model'], 'messages': messages, **params,
                   'max_completion_tokens': limit, 'stream': settings.stream}
        if settings.stream:
            payload['stream_options'] = {'include_usage': True}
    elif transport == 'anthropic':
        endpoint = base + '/v1/messages'
        headers.update({'x-api-key': key, 'anthropic-version': '2023-06-01'})
        payload = {'model': model['model'], 'system': system, 'messages': body,
                   'max_tokens': limit, **model['parameters'], 'stream': settings.stream}
    elif transport == 'gemini':
        if urlparse(base).hostname == 'generativelanguage.googleapis.com':
            headers.pop('Authorization', None)
        method = ':streamGenerateContent?alt=sse' if settings.stream else ':generateContent'
        endpoint = base + '/models/' + model['model'] + method
        headers['x-goog-api-key'] = key
        payload = {'systemInstruction': {'parts': [{'text': system}]},
                   'contents': [{'role': 'model' if m['role'] == 'assistant' else 'user',
                                 'parts': [{'text': m['content']}]} for m in body],
                   'generationConfig': {**model['parameters'], 'maxOutputTokens': limit}}
    else:
        raise ValueError('Unsupported transport')
    return transport, endpoint, headers, payload

def unpack(transport, data):
    if transport == 'openai':
        choices = data.get('choices', [])
        choice = choices[0] if choices else {}
        text = choice.get('delta', choice.get('message', {})).get('content') or ''
        return text, {'returned_model': data.get('model'), 'response_id': data.get('id'),
                      'usage': data.get('usage'), 'finish_reason': choice.get('finish_reason')}
    if transport == 'anthropic':
        msg = data.get('message', data)
        text = ''.join(x.get('text', '') for x in data.get('content', []) if x.get('type') == 'text')
        text += data.get('delta', {}).get('text', '')
        return text, {'returned_model': msg.get('model'), 'response_id': msg.get('id'),
                      'usage': data.get('usage', msg.get('usage')),
                      'finish_reason': data.get('delta', {}).get('stop_reason', data.get('stop_reason'))}
    candidates = data.get('candidates', [])
    choice = candidates[0] if candidates else {}
    text = ''.join(p.get('text', '') for p in choice.get('content', {}).get('parts', []) if not p.get('thought'))
    return text, {'returned_model': data.get('modelVersion'), 'response_id': data.get('responseId'),
                  'usage': data.get('usageMetadata'), 'finish_reason': choice.get('finishReason')}

def invoke(model_name, messages, limit, settings=None, session=None):
    settings = settings or RunSettings()
    transport, endpoint, headers, payload = request_spec(model_name, messages, limit, settings)
    owned = session is None
    session = session or requests.Session()
    attempts = []
    try:
        for attempt in range(settings.maximum_attempts):
            started = time.monotonic()
            response = None
            try:
                response = session.post(endpoint, headers=headers, json=payload,
                                        timeout=(min(15, settings.timeout_seconds), settings.timeout_seconds),
                                        stream=settings.stream)
                entry = {'attempt': attempt + 1, 'http_status': response.status_code}
                attempts.append(entry)
                retryable = response.status_code in {408, 429, 500, 502, 503, 504}
                if response.status_code >= 400:
                    if not retryable or attempt + 1 == settings.maximum_attempts:
                        raise InvocationError('http_' + str(response.status_code), attempts)
                    retry_after = response.headers.get('Retry-After')
                    wait = settings.retry_backoff_seconds[attempt]
                    if retry_after:
                        try:
                            wait = max(0, float(retry_after))
                        except ValueError:
                            try:
                                wait = max(0, (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds())
                            except (TypeError, ValueError):
                                pass
                    response.close()
                    time.sleep(wait)
                    continue
                text_parts, metadata = [], {}
                if settings.stream:
                    chunks = []
                    for line in response.iter_lines(decode_unicode=True):
                        if time.monotonic() - started > settings.timeout_seconds:
                            raise requests.Timeout()
                        if isinstance(line, bytes):
                            line = line.decode('utf-8')
                        if not line or not line.startswith('data:'):
                            continue
                        value = line[5:].strip()
                        if value == '[DONE]':
                            break
                        chunks.append(json.loads(value))
                else:
                    chunks = [response.json()]
                for chunk in chunks:
                    text, meta = unpack(transport, chunk)
                    text_parts.append(text)
                    for key, value in meta.items():
                        if value is not None:
                            if key == 'usage' and isinstance(value, dict):
                                metadata.setdefault('usage', {}).update(value)
                            else:
                                metadata[key] = value
                entry['elapsed_seconds'] = time.monotonic() - started
                return {'text': ''.join(text_parts), 'metadata': metadata, 'attempts': attempts,
                        'requested_model': MODEL_SETTINGS[model_name]['model'], 'request_parameters': payload}
            except (requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError) as exc:
                attempts.append({'attempt': attempt + 1, 'error_type': type(exc).__name__})
                if attempt + 1 == settings.maximum_attempts:
                    raise InvocationError(type(exc).__name__, attempts) from None
                time.sleep(settings.retry_backoff_seconds[attempt])
            except (ValueError, requests.RequestException) as exc:
                raise InvocationError(type(exc).__name__, attempts) from None
            finally:
                if response is not None:
                    response.close()
    finally:
        if owned:
            session.close()
    raise InvocationError('request_failed', attempts)

