import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import tempfile
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from core import Store, atomic_json
from app import Controller, SettingsDialog
from charts import moving_average, rsi, daily_bars, PriceCanvas, compare_values
from portfolio_views import allocations
from mcp_client import McpConnection, validate_server, redact_result

APP = QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False)


class UpgradeTests(unittest.TestCase):
    def test_legacy_scale_ignored_and_defaults_independent(self):
        with tempfile.TemporaryDirectory() as root:
            atomic_json(Path(root) / 'settings.json', {'interface_scale': 150, 'default_character': 'kokona'})
            store = Store(root)
            self.assertNotIn('interface_scale', store.settings)
            store.active_chat['character'] = 'izuna'
            store.new_chat()
            self.assertEqual(store.character, 'kokona')
            store.save()
            self.assertEqual(Store(root).character, 'kokona')

    def test_geometry_and_profile_selection(self):
        with tempfile.TemporaryDirectory() as root:
            c = Controller(Store(root), with_tray=False)
            c.startup_timer.stop()
            try:
                c.open_chat(); c.chat.resize(620, 510); c.chat.move(20, 30)
                c.chat.save_geometry()
                saved = dict(c.store.settings['window_geometry'])
                c.chat.hide(); c.open_chat()
                self.assertEqual(c.chat.width(), saved['width'])
                self.assertEqual(c.chat.height(), saved['height'])
                dialog = SettingsDialog(c)
                dialog.nickname.setText('이즈나 호칭')
                dialog.current_character.setCurrentIndex(1)
                self.assertEqual(dialog.nickname.text(), '선생님')
                dialog.nickname.setText('코코나 호칭')
                dialog.current_character.setCurrentIndex(0)
                self.assertEqual(dialog.nickname.text(), '이즈나 호칭')
                dialog.reject()
                self.assertEqual(c.store.character, 'izuna')
                self.assertNotEqual(c.store.profiles['izuna']['nickname'], '이즈나 호칭')
            finally:
                c.shutdown(); c.chat.hide(); c.pet.hide(); c.stocks.hide()

    def test_indicators(self):
        self.assertEqual(moving_average([1, 2, 3, 4], 3), [None, None, 2, 3])
        self.assertEqual(rsi([10] * 20)[-1], 50)
        self.assertEqual(rsi(list(range(1, 30)))[-1], 100)
        self.assertEqual(rsi(list(range(30, 1, -1)))[-1], 0)

    def test_bad_bars_and_split_warning(self):
        data = {'chart': {'result': [{'timestamp': [1, 2], 'meta': {}, 'events': {'splits': {'2': {}}}, 'indicators': {'quote': [{'open': [1, None], 'high': [3, 2], 'low': [1, 1], 'close': [2, 1], 'volume': [100, 200]}]}}]}}
        bars, _, warnings = daily_bars(data)
        self.assertEqual(len(bars), 1)
        self.assertEqual(len(warnings), 2)
        widget = PriceCanvas(); widget.bars = bars; widget.resize(600, 400)
        self.assertFalse(widget.grab().isNull())

    def test_donut_fx_missing_and_stale(self):
        holdings = [dict(symbol='A', market='US', quantity=1), dict(symbol='B', market='KRX', quantity=1)]
        quotes = {0: dict(price=100, currency='USD', timestamp=100), 1: dict(price=1000, currency='KRW', timestamp=100)}
        rows, warnings = allocations(holdings, quotes, now=200000)
        self.assertEqual(rows[0][0], 'B'); self.assertEqual(rows[0][2], 1)
        self.assertEqual(len(warnings), 2)
        rows, _ = allocations(holdings, quotes, fx={'KRW': 1, 'USD': 1000}, now=100)
        self.assertAlmostEqual(sum(r[2] for r in rows), 1)
        self.assertEqual(rows[-1][0], '기타')

    def test_mcp_urls(self):
        for url in ('http://example.com', 'https://user:pass@example.com', 'https://example.com/?token=secret', 'file:///etc/passwd'):
            with self.assertRaises(ValueError): validate_server(dict(transport='https', url=url))
        validate_server(dict(transport='https', url='https://example.com/mcp'))

    def test_redaction(self):
        raw = {'api_key': 'secret', 'nested': [{'text': 'Bearer token123 and abc987'}]}
        cleaned = json.dumps(redact_result(raw, 'abc987'))
        self.assertNotIn('secret', cleaned); self.assertNotIn('token123', cleaned); self.assertNotIn('abc987', cleaned)

    def test_comparison_rebases_common_date(self):
        bars = [(86400, 0, 0, 0, 100, 0), (172800, 0, 0, 0, 120, 0)]
        other = [(86400, 0, 0, 0, 50, 0), (172800, 0, 0, 0, 55, 0)]
        values = compare_values(bars, other)
        self.assertEqual(values[0], 100); self.assertAlmostEqual(values[1], 110)

    def test_mcp_mock_handshake_call_and_cancel(self):
        connection = McpConnection({'transport': 'stdio', 'allowed': ['utc_time']})
        ready, results, errors = [], [], []
        connection.ready.connect(ready.append); connection.result.connect(results.append); connection.failed.connect(errors.append)
        def wait_for(predicate):
            deadline = time.monotonic() + 5
            while not predicate() and time.monotonic() < deadline: QTest.qWait(10)
            self.assertTrue(predicate(), str(errors))
        try:
            connection.start(); wait_for(lambda: bool(ready or errors))
            self.assertFalse(errors)
            self.assertEqual(ready[0][0]['name'], 'utc_time')
            with self.assertRaises(ValueError): connection.call('shell', {})
            connection.call('utc_time', {}); wait_for(lambda: bool(results or errors))
            self.assertIn('content', results[0])
            connection.call('utc_time', {}); connection.close(); QTest.qWait(100)
            self.assertEqual(len(results), 1)
        finally:
            connection.close(); QTest.qWait(100)

    def test_mcp_http_json_and_sse_mock(self):
        class Handler(BaseHTTPRequestHandler):
            sse = False
            seen = []
            def log_message(self, *args): pass
            def do_POST(self):
                message = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                Handler.seen.append((message, {k.lower(): v for k, v in self.headers.items()}))
                if 'id' not in message:
                    self.send_response(202); self.end_headers(); return
                method = message['method']
                if method == 'initialize':
                    result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'test', 'version': '1'}}
                elif method == 'tools/list':
                    result = {'tools': [{'name': 'test', 'inputSchema': {'type': 'object'}}]}
                else: result = {'content': [{'type': 'text', 'text': 'ok'}]}
                raw = json.dumps({'jsonrpc': '2.0', 'id': message['id'], 'result': result}).encode()
                self.send_response(200)
                self.send_header('Mcp-Session-Id', 'test-session')
                self.send_header('Content-Type', 'text/event-stream' if Handler.sse else 'application/json')
                self.end_headers()
                try: self.wfile.write(b'data: ' + raw + b'\n\n' if Handler.sse else raw)
                except (BrokenPipeError, ConnectionResetError): pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        class LocalManager(QNetworkAccessManager):
            def createRequest(self, operation, request, data=None):
                local = QNetworkRequest(request)
                local.setUrl(QUrl(f'http://127.0.0.1:{server.server_port}/mcp'))
                return super().createRequest(operation, local, data)
        try:
            for sse in (False, True):
                Handler.sse = sse; Handler.seen = []
                conn = McpConnection({'transport': 'https', 'url': 'https://test.invalid/mcp', 'allowed': ['test']}, 'mock-token')
                conn.manager = LocalManager(conn)
                ready, results, errors = [], [], []
                conn.ready.connect(ready.append); conn.result.connect(results.append); conn.failed.connect(errors.append)
                try:
                    conn.start()
                    end = time.monotonic() + 3
                    while not (ready or errors) and time.monotonic() < end: QTest.qWait(10)
                    self.assertTrue(ready, str(errors)); conn.call('test', {})
                    end = time.monotonic() + 3
                    while not (results or errors) and time.monotonic() < end: QTest.qWait(10)
                    self.assertTrue(results, str(errors))
                    calls = [(m, h) for m, h in Handler.seen if m.get('method') == 'tools/call']
                    self.assertEqual(calls[0][1]['mcp-session-id'], 'test-session')
                    self.assertEqual(calls[0][1]['authorization'], 'Bearer mock-token')
                finally: conn.close(); QTest.qWait(20)
        finally: server.shutdown(); server.server_close(); thread.join(timeout=2)


if __name__ == '__main__': unittest.main()
