"""Bounded MCP client: bundled stdio fixture and remote HTTPS JSON/SSE.

This is not an OS sandbox. Arbitrary local executables are intentionally disabled.
All remote tools require explicit allowlisting and every write is confirmed.
"""
import json
import sys
import uuid
import re
from pathlib import Path
from urllib.parse import urlsplit
from PySide6.QtCore import QObject, Signal, QProcess, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from core import KeyVault, atomic_json, read_json

LIMIT = 2 * 1024 * 1024


def redact_result(value, token=''):
    if isinstance(value, dict):
        return {str(k): '[REDACTED]' if re.search(r'password|secret|token|authorization|api.?key|certificate|account.?number', str(k), re.I) else redact_result(v, token) for k, v in value.items()}
    if isinstance(value, list): return [redact_result(v, token) for v in value]
    if isinstance(value, str):
        if token: value = value.replace(token, '[REDACTED]')
        value = re.sub(r'(?i)(bearer\s+)[^\s"<>]+', r'\1[REDACTED]', value)
        return value
    return value


def validate_server(server):
    if server.get('transport') not in ('stdio', 'https'):
        raise ValueError('지원하지 않는 연결 방식')
    if server['transport'] == 'https':
        parsed = urlsplit(server.get('url', ''))
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('인증정보·쿼리 없는 HTTPS 주소를 입력하세요.')
    return server


class SecretVault(KeyVault):
    def __init__(self, root, ident):
        uuid.UUID(ident)
        self.path = Path(root) / ('mcp-' + ident + '.dpapi')
        self.session_key = ''; self.warning = ''
        if sys.platform == 'win32' and self.path.exists():
            try: self.session_key = self._crypt(self.path.read_bytes(), False).decode('utf-8')
            except Exception: self.warning = '암호화 키를 읽지 못했습니다.'


class McpConnection(QObject):
    ready = Signal(list)
    result = Signal(dict)
    failed = Signal(str)
    def __init__(self, server, token='', parent=None):
        super().__init__(parent)
        self.server = validate_server(server); self.token = token
        self.manager = QNetworkAccessManager(self)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.read_stdio)
        self.process.readyReadStandardError.connect(lambda: self.process.readAllStandardError())
        self.process.errorOccurred.connect(lambda _: self.fail('로컬 테스트 서버 실행 실패'))
        self.process.finished.connect(self.process_ended)
        self.timer = QTimer(self); self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self.fail('MCP 요청 시간 초과'))
        self.seq = 0; self.pending = None; self.reply = None
        self.buffer = b''; self.http_buffer = b''; self.session = ''; self.tools = []; self.closed = False

    def start(self):
        self.closed = False
        if self.server['transport'] == 'stdio':
            if getattr(sys, 'frozen', False):
                self.fail('이 빌드에서는 stdio 모의 서버를 소스 실행으로 검증하세요.'); return
            self.process.started.connect(self.initialize)
            script = 'folder_server.py' if self.server.get('local_folder') else 'mock_mcp_server.py'
            args = ['-u', str(Path(__file__).with_name(script))]
            if self.server.get('local_folder'): args.append(str(self.server['local_folder']))
            executable = Path(sys.executable)
            if executable.name.lower() == 'pythonw.exe': executable = executable.with_name('python.exe')
            self.process.start(str(executable), args)
            self.timer.start(15000)
        else: self.initialize()

    def initialize(self):
        self.request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'IzunaDesktop', 'version': '0.5'}}, 'initialize')

    def request(self, method, params, phase):
        if self.pending:
            raise ValueError('MCP 요청이 진행 중입니다.')
        self.seq += 1; self.pending = (self.seq, phase)
        self.timer.start(15000)
        self.send({'jsonrpc': '2.0', 'id': self.seq, 'method': method, 'params': params})

    def send(self, message):
        raw = json.dumps(message).encode('utf-8')
        if len(raw) > LIMIT:
            self.fail('MCP 요청 크기 초과'); return
        if self.server['transport'] == 'stdio':
            self.process.write(raw + b'\n'); return
        request = QNetworkRequest(QUrl(self.server['url']))
        request.setHeader(QNetworkRequest.ContentTypeHeader, 'application/json')
        request.setRawHeader(b'Accept', b'application/json, text/event-stream')
        request.setRawHeader(b'MCP-Protocol-Version', b'2025-06-18')
        if self.session: request.setRawHeader(b'Mcp-Session-Id', self.session.encode('ascii'))
        if self.token: request.setRawHeader(b'Authorization', ('Bearer ' + self.token).encode('utf-8'))
        request.setTransferTimeout(15000)
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.ManualRedirectPolicy)
        reply = self.manager.post(request, raw)
        if 'id' not in message or 'method' not in message:
            reply.finished.connect(reply.deleteLater); return
        self.reply = reply; self.http_buffer = b''
        reply.readyRead.connect(lambda: self.read_http(reply))
        reply.finished.connect(lambda: self.finish_http(reply))

    def read_http(self, reply):
        if reply is not self.reply: return
        self.http_buffer += bytes(reply.readAll())
        if len(self.http_buffer) > LIMIT:
            self.fail('MCP 응답 크기 초과'); return
        if bytes(reply.rawHeader('Content-Type')).startswith(b'text/event-stream'):
            self.http_buffer = self.http_buffer.replace(b'\r\n', b'\n')
            while b'\n\n' in self.http_buffer:
                block, self.http_buffer = self.http_buffer.split(b'\n\n', 1)
                data = b'\n'.join(line[5:].lstrip() for line in block.split(b'\n') if line.startswith(b'data:'))
                if data:
                    try:
                        decoded = json.loads(data)
                    except ValueError:
                        self.fail('MCP SSE 형식 오류'); return
                    if isinstance(decoded, dict) and self.pending and decoded.get('id') == self.pending[0] and 'method' not in decoded:
                        session = bytes(reply.rawHeader('Mcp-Session-Id')).decode('ascii', errors='ignore')
                        if session and all(33 <= ord(c) <= 126 for c in session): self.session = session
                        self.reply = None
                        reply.abort()
                        self.handle_bytes(data)
                        return
                    self.handle_bytes(data)

    def finish_http(self, reply):
        if reply is not self.reply:
            reply.deleteLater(); return
        self.read_http(reply)
        if reply is not self.reply:
            return
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        session = bytes(reply.rawHeader('Mcp-Session-Id')).decode('ascii', errors='ignore')
        if session and all(33 <= ord(c) <= 126 for c in session): self.session = session
        raw = self.http_buffer; self.reply = None
        content_type = bytes(reply.rawHeader('Content-Type'))
        reply.deleteLater()
        if status != 200:
            self.fail('MCP HTTPS 연결 실패 (인증·주소·서버 상태 확인)'); return
        if not content_type.startswith(b'text/event-stream'): self.handle_bytes(raw)

    def read_stdio(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        if len(self.buffer) > LIMIT:
            self.fail('MCP 응답 크기 초과'); return
        while b'\n' in self.buffer:
            raw, self.buffer = self.buffer.split(b'\n', 1)
            self.handle_bytes(raw)

    def handle_bytes(self, raw):
        try: data = json.loads(raw)
        except (ValueError, TypeError):
            self.fail('MCP JSON 응답 오류'); return
        if not isinstance(data, dict):
            self.fail('MCP 응답 형식 오류'); return
        if 'method' in data:
            # No roots, sampling, elicitation, shell, or client-side execution.
            if 'id' in data:
                self.send({'jsonrpc': '2.0', 'id': data['id'], 'error': {'code': -32601, 'message': 'Client requests disabled'}})
            return
        if not self.pending or data.get('id') != self.pending[0]: return
        _, phase = self.pending; self.pending = None; self.timer.stop()
        if 'error' in data:
            self.fail('MCP 서버가 요청을 거절했습니다.'); return
        result = data.get('result')
        if not isinstance(result, dict):
            self.fail('MCP 결과 형식 오류'); return
        if phase == 'initialize':
            if result.get('protocolVersion') != '2025-06-18':
                self.fail('지원 프로토콜: 2025-06-18'); return
            self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
            self.request('tools/list', {}, 'list')
        elif phase == 'list':
            items = result.get('tools')
            if not isinstance(items, list) or not all(isinstance(t, dict) and isinstance(t.get('name'), str) and isinstance(t.get('inputSchema'), dict) for t in items):
                self.fail('도구 목록 형식 오류'); return
            self.tools.extend(items)
            if len(self.tools) > 500:
                self.fail('도구 목록 한도 초과'); return
            if result.get('nextCursor'):
                self.request('tools/list', {'cursor': result['nextCursor']}, 'list')
            else: self.ready.emit(self.tools)
        else: self.result.emit(result)

    def call(self, name, arguments):
        if name not in self.server.get('allowed', []): raise ValueError('허용되지 않은 도구')
        if not any(t['name'] == name for t in self.tools): raise ValueError('서버에 없는 도구')
        if not isinstance(arguments, dict): raise ValueError('인자는 JSON 객체여야 합니다.')
        self.request('tools/call', {'name': name, 'arguments': arguments}, 'call')

    def process_ended(self):
        if not self.closed and self.pending: self.fail('MCP 서버 연결 종료')

    def fail(self, message):
        self.close(); self.failed.emit(message)

    def close(self):
        self.closed = True
        if self.pending:
            self.send({'jsonrpc': '2.0', 'method': 'notifications/cancelled', 'params': {'requestId': self.pending[0], 'reason': 'User cancelled'}})
        self.pending = None; self.timer.stop()
        if self.reply:
            reply, self.reply = self.reply, None; reply.abort()
        if self.process.state() != QProcess.NotRunning:
            self.process.kill()


class McpRegistry:
    def __init__(self, root):
        self.root = Path(root); self.path = self.root / 'mcp-servers.json'
        raw = read_json(self.path, [])
        self.servers = []
        if isinstance(raw, list):
            for item in raw:
                try:
                    uuid.UUID(item['id']); validate_server(item)
                    if not isinstance(item.get('allowed', []), list): continue
                    self.servers.append(item)
                except (ValueError, TypeError, KeyError, AttributeError): pass
    def save(self): atomic_json(self.path, self.servers)
