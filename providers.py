"""Provider-native REST adapters and editable model presets (2026-09-14)."""
import json
import re
from urllib.parse import urlsplit, quote

PROVIDERS = {'openai': 'OpenAI', 'gemini': 'Google Gemini', 'claude': 'Anthropic Claude',
             'ollama': 'Ollama', 'vercel': 'Vercel AI Gateway'}
PRESETS = {
    'openai': ['gpt-5.6-luna', 'gpt-5.6-terra', 'gpt-5.6-sol', 'gpt-6-astra', 'gpt-4.1-mini'],
    'gemini': ['gemini-3.8-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-2.5-flash', 'gemini-2.5-pro'],
    'claude': ['claude-sonnet-5', 'claude-opus-5', 'claude-fable-5-1', 'claude-haiku-4-5'],
    'ollama': ['qwen3:8b', 'gemma3:4b', 'qwen3:14b', 'llama3.3:70b', 'deepseek-r1:8b'],
    'vercel': ['anthropic/claude-sonnet-5', 'anthropic/claude-fable-5.1', 'anthropic/claude-opus-5', 'openai/gpt-5.6-luna', 'google/gemini-3.8-flash'],
}


def ollama_base(value):
    value = value.strip().rstrip('/')
    u = urlsplit(value)
    if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError('Ollama 서버 주소를 확인해 주세요. 예: http://localhost:11434')
    try:
        u.port
    except ValueError:
        raise ValueError('Ollama 포트 번호가 올바르지 않아요.')
    if u.path not in ('', '/'):
        raise ValueError('Ollama 주소에는 /api/chat 없이 서버 주소와 포트만 입력해 주세요.')
    return value


def build_request(provider, key, payload, base='http://localhost:11434'):
    if provider not in PROVIDERS:
        raise ValueError('지원하지 않는 API 서비스예요.')
    model = payload['model'].strip()
    if not model or len(model) > 160 or any(ch.isspace() for ch in model):
        raise ValueError('모델 이름에 공백이 없는지 확인해 주세요.')
    if provider != 'ollama' and not key:
        raise ValueError('선택한 서비스의 API 키를 입력해 주세요.')
    prompt = payload['instructions']
    schema = payload['text']['format']['schema']
    prompt += '\n반드시 JSON 객체만 출력: {"reply":"대답","emotion":"표정"}. 표정: ' + ', '.join(schema['properties']['emotion']['enum'])
    history = list(payload['input'])
    while history and history[0]['role'] != 'user':
        history.pop(0)
    headers = {}
    if provider == 'openai':
        data = dict(payload)
        data['input'] = history
        data['max_output_tokens'] = 4096
        if model.startswith(('gpt-5', 'gpt-6')):
            data['reasoning'] = {'effort': 'low'}
        return 'https://api.openai.com/v1/responses', {'Authorization': 'Bearer ' + key}, data
    if provider == 'gemini':
        model = model.removeprefix('models/')
        return ('https://generativelanguage.googleapis.com/v1beta/models/' + quote(model, safe='-._') + ':generateContent',
                {'x-goog-api-key': key}, {'systemInstruction': {'parts': [{'text': prompt}]},
                'contents': [{'role': 'model' if m['role'] == 'assistant' else 'user', 'parts': [{'text': m['content']}]} for m in history],
                'generationConfig': {'maxOutputTokens': 4096, 'responseMimeType': 'application/json'}})
    if provider == 'claude':
        extra = {'output_config': {'effort': 'low'}} if model.startswith(('claude-sonnet-5', 'claude-opus-5', 'claude-fable-5')) else {}
        return 'https://api.anthropic.com/v1/messages', {'x-api-key': key, 'anthropic-version': '2023-06-01'}, {
            'model': model, 'system': prompt, 'messages': history, 'max_tokens': 4096, 'stream': False, **extra}
    messages = [{'role': 'system', 'content': prompt}] + history
    if provider == 'ollama':
        if key:
            headers['Authorization'] = 'Bearer ' + key
        return ollama_base(base) + '/api/chat', headers, {
            'model': model, 'messages': messages, 'stream': False, 'format': schema,
            'options': {'num_predict': 4096}}
    return 'https://ai-gateway.vercel.sh/v1/chat/completions', {'Authorization': 'Bearer ' + key}, {
        'model': model, 'messages': messages, 'stream': False, 'max_tokens': 4096}


def decode_text(text):
    from core import AI_EMOTIONS
    text = text.strip()
    if not text:
        raise ValueError('빈 답변을 받았어요. 모델과 출력 설정을 확인해 주세요.')
    candidate = text
    if candidate.startswith('```'):
        candidate = re.sub(r'^```(?:json)?\s*|\s*```$', '', candidate, flags=re.I)
    try:
        data = json.loads(candidate)
    except ValueError:
        # Compatible models may answer normally instead of following the JSON prompt.
        if candidate.startswith('{'):
            raise ValueError('답변 JSON이 완성되지 않았어요. 다시 보내거나 다른 모델을 선택해 주세요.')
        return text[:12000], 'cozy'
    if not isinstance(data, dict) or not isinstance(data.get('reply'), str) or not data['reply'].strip():
        raise ValueError('답변 형식이 맞지 않아요. 다른 대화 모델을 선택해 주세요.')
    mood = data.get('emotion')
    return data['reply'][:12000], mood if mood in AI_EMOTIONS else 'cozy'


def parse_provider_response(provider, data):
    from core import parse_response
    if not isinstance(data, dict) or data.get('error'):
        raise ValueError('서비스에서 오류 응답을 받았어요. 모델 이름과 권한을 확인해 주세요.')
    if provider == 'openai':
        return parse_response(data)
    if provider == 'gemini':
        candidates = data.get('candidates') or []
        if not candidates:
            raise ValueError('Gemini가 답변을 반환하지 않았어요. 차단된 요청이거나 빈 응답일 수 있어요.')
        c = candidates[0]
        if c.get('finishReason') not in (None, 'STOP'):
            raise ValueError('Gemini 답변이 중단됐어요: ' + str(c.get('finishReason'))[:60])
        text = ''.join(p.get('text', '') for p in c.get('content', {}).get('parts', []) if not p.get('thought'))
    elif provider == 'claude':
        if data.get('stop_reason') == 'max_tokens':
            raise ValueError('Claude 답변이 길이 제한으로 중단됐어요. 질문을 짧게 나눠 주세요.')
        text = ''.join(p.get('text', '') for p in data.get('content', []) if p.get('type') == 'text')
    elif provider == 'ollama':
        if data.get('done_reason') == 'length':
            raise ValueError('Ollama 답변이 길이 제한으로 중단됐어요. 질문을 짧게 나눠 주세요.')
        text = data.get('message', {}).get('content', '')
    else:
        choices = data.get('choices') or []
        if not choices:
            raise ValueError('Vercel에서 빈 답변을 받았어요.')
        if choices[0].get('finish_reason') == 'length':
            raise ValueError('답변이 길이 제한으로 중단됐어요.')
        message = choices[0].get('message', {})
        text = message.get('content') or message.get('refusal') or ''
        if isinstance(text, list):
            text = ''.join(p.get('text', '') for p in text if p.get('type') == 'text')
    return decode_text(text)
