"""Bundled read-only JSON-RPC stdio fixture. No file, shell or network tools."""
import json
import sys
from datetime import datetime, timezone

for line in sys.stdin:
    try:
        request = json.loads(line)
        if 'id' not in request:
            continue
        method = request.get('method')
        if method == 'initialize':
            result = dict(protocolVersion='2025-06-18', capabilities={'tools': {}}, serverInfo={'name': 'Izuna mock', 'version': '1'})
        elif method == 'tools/list':
            result = {'tools': [dict(name='utc_time', description='현재 UTC 시각 조회 (모의 연결 테스트)', inputSchema={'type': 'object', 'properties': {}, 'additionalProperties': False}, annotations={'readOnlyHint': True})]}
        elif method == 'tools/call' and request.get('params', {}).get('name') == 'utc_time':
            result = {'content': [{'type': 'text', 'text': datetime.now(timezone.utc).isoformat()}], 'isError': False}
        else:
            print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'error': {'code': -32601, 'message': 'Unsupported method'}}), flush=True)
            continue
        print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
    except (ValueError, TypeError, KeyError):
        pass
