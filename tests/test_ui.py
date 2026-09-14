import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QUrl, QPoint, Qt
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from app import Controller, SettingsDialog, STYLE, clamp_position
from core import Store, EMOTIONS, ASSETS

APP = QApplication.instance() or QApplication([])
APP.setStyleSheet(STYLE)
APP.setQuitOnLastWindowClosed(False)

class Handler(BaseHTTPRequestHandler):
    status = 200
    delay = 0
    seen = None
    provider = 'openai'
    requests = []
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        Handler.seen = {'body': body, 'auth': self.headers.get('Authorization'), 'headers': dict(self.headers), 'path': self.path}
        Handler.requests.append(Handler.seen)
        time.sleep(Handler.delay)
        self.send_response(Handler.status)
        self.end_headers()
        is_summary = 'summarize a chat into long-term memory' in json.dumps(body, ensure_ascii=False)
        text = json.dumps({'reply': 'The user likes coffee.' if is_summary else '테스트 답변', 'emotion': 'thinking' if is_summary else 'eureka'})
        data = {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}]}
        if Handler.provider == 'gemini':
            data = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': text}]}}]}
        elif Handler.provider == 'claude':
            data = {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}
        elif Handler.provider == 'ollama':
            data = {'done': True, 'message': {'content': text}}
        elif Handler.provider == 'vercel':
            data = {'choices': [{'finish_reason': 'stop', 'message': {'content': text}}]}
        try:
            self.wfile.write(json.dumps(data).encode())
        except (BrokenPipeError, ConnectionResetError):
            pass
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({'models': [{'name': 'local-test:8b'}]}).encode())

    def log_message(self, *args):
        pass

class LocalManager(QNetworkAccessManager):
    """Only the test swaps the endpoint; no real credential or paid API call."""
    port = 0
    def createRequest(self, op, request, data=None):
        cloned = QNetworkRequest(request)
        cloned.setUrl(QUrl(f'http://127.0.0.1:{self.port}' + request.url().path()))
        return super().createRequest(op, cloned, data)

class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(('127.0.0.1', 0), Handler)
        LocalManager.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c = Controller(Store(self.tmp.name), with_tray=False)
        self.c.open_chat()
        self.c.pet.timer.stop()
        Handler.status = 200
        Handler.provider = 'openai'
        Handler.delay = 0
        Handler.seen = None
        Handler.requests = []
        self.c.client.manager = LocalManager(self.c.client)
        APP.processEvents()

    def tearDown(self):
        self.c.shutdown()
        self.c.pet.hide()
        self.c.chat.hide()
        self.c.pet.deleteLater()
        self.c.chat.deleteLater()
        APP.processEvents()
        self.tmp.cleanup()

    def wait_done(self):
        deadline = time.monotonic() + 3
        while self.c.busy and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertFalse(self.c.busy)

    def api_mode(self):
        self.c.store.settings['demo'] = False
        self.c.vault.set('fake-key-for-test', False)

    def test_summary_then_answer_for_all_providers(self):
        from providers import PRESETS
        for pid in ('openai', 'gemini', 'claude', 'ollama', 'vercel'):
            with self.subTest(provider=pid):
                self.c.store.new_chat()
                self.c.store.history = [dict(role='user' if i%2==0 else 'assistant', content=f'메시지 {i}') for i in range(42)]
                self.c.chat.reload_chat()
                self.c.store.settings.update(provider=pid, model=PRESETS[pid][0], demo=False)
                self.c.vault.set('fake-key', False)
                Handler.provider = pid
                Handler.requests = []
                self.c.send('내 취향이 뭐야?')
                self.assertFalse(self.c.chat.tabs.isEnabled())
                self.wait_done()
                self.assertEqual(len(Handler.requests), 2)
                self.assertEqual(self.c.store.active_chat['summary_until'], 22)
                self.assertEqual(len(self.c.store.history), 44)
                self.assertIn('coffee', self.c.store.active_chat['summary'])
                main = json.dumps(Handler.requests[-1]['body'], ensure_ascii=False)
                self.assertIn('coffee', main)
                self.assertIn('메시지 22', main)
                self.assertNotIn('메시지 0', main)
                self.assertTrue(self.c.chat.tabs.isEnabled())

    def test_summary_failure_and_cancel_preserve_original_and_draft(self):
        self.api_mode()
        self.c.store.history = [dict(role='user' if i%2==0 else 'assistant', content=str(i)) for i in range(42)]
        Handler.status = 500
        self.c.send('다시 보내기')
        self.wait_done()
        self.assertEqual(len(self.c.store.history), 42)
        self.assertEqual(self.c.store.active_chat['summary_until'], 0)
        self.assertEqual(self.c.chat.input.text(), '다시 보내기')
        Handler.status = 200
        Handler.delay = .3
        self.c.send('요약 중 취소')
        QTest.qWait(30)
        self.c.cancel()
        QTest.qWait(400)
        self.assertEqual(self.c.store.active_chat['summary'], '')
        self.assertEqual(len(self.c.store.history), 42)
        self.assertEqual(self.c.chat.input.text(), '요약 중 취소')

    def test_tab_switch_restores_draft_and_character(self):
        self.assertEqual(self.c.chat.new_button.text(), '새 대화')
        first = self.c.store.active_id
        self.c.chat.input.setText('아직 보내지 않음')
        self.c.chat.new_tab()
        self.c.chat.character_select.setCurrentIndex(1)
        self.assertEqual(self.c.store.character, 'kokona')
        self.assertIn('코코나', self.c.chat.character_title.text())
        self.assertFalse(self.c.pet.pix.isNull())
        self.c.send('안녕')
        self.c.chat.new_tab()  # Busy operations are ignored.
        self.assertEqual(len(self.c.store.chats), 2)
        self.wait_done()
        self.assertIn('코코나', self.c.store.history[-1]['content'])
        self.assertEqual(self.c.store.history[-1]['character'], 'kokona')
        self.c.chat.tabs.setCurrentIndex(0)
        self.assertEqual(self.c.store.active_id, first)
        self.assertEqual(self.c.store.character, 'izuna')
        self.assertEqual(self.c.store.history, [])
        self.assertEqual(self.c.chat.input.text(), '아직 보내지 않음')

    def test_appearance_controls_apply_independently(self):
        settings = self.c.store.settings
        settings.update(interface_scale=80, pet_opacity=65, interface_opacity=75,
                        pet_on_top=False, chat_on_top=False)
        self.c.apply_appearance()
        self.assertAlmostEqual(self.c.pet.windowOpacity(), .65, places=2)
        self.assertAlmostEqual(self.c.chat.windowOpacity(), .75, places=2)
        self.assertAlmostEqual(self.c.stocks.windowOpacity(), .75, places=2)
        self.assertFalse(bool(self.c.pet.windowFlags() & Qt.WindowStaysOnTopHint))
        self.assertFalse(bool(self.c.chat.windowFlags() & Qt.WindowStaysOnTopHint))
        self.assertEqual(self.c.chat.minimumWidth(), 288)

    def test_portfolio_round_trip_and_stock_window(self):
        self.c.stocks.market_client.fetch = lambda positions: None
        self.c.stocks.symbol.setText('NVDA')
        self.c.stocks.stock_name.setText('엔비디아')
        self.c.stocks.quantity.setValue(2)
        self.c.stocks.average.setValue(100)
        self.c.stocks.add_position()
        self.assertEqual(len(self.c.store.portfolio), 1)
        self.assertEqual(self.c.stocks.table.item(0, 0).text(), '엔비디아 · 미국/NVDA')
        restored = Store(self.tmp.name)
        self.assertEqual(restored.portfolio[0]['symbol'], 'NVDA')

    def test_two_turns_resend_previous_answer(self):
        self.api_mode()
        self.c.send('내 이름은 민수')
        self.wait_done()
        self.c.send('내 이름은?')
        self.wait_done()
        messages = Handler.seen['body']['input']
        self.assertEqual([m['role'] for m in messages], ['user', 'assistant', 'user'])
        self.assertEqual(messages[0]['content'], '내 이름은 민수')
        self.assertEqual(messages[1]['content'], '테스트 답변')

    def test_assets_and_transparent_hit_region(self):
        for mood in EMOTIONS:
            pix, region = self.c.pet.frame(mood, False)
            self.assertFalse(pix.isNull(), mood)
            self.assertGreater(region.rectCount(), 0)
            self.assertLess(region.boundingRect().width(), self.c.pet.width())
        self.assertFalse(self.c.pet.mask().contains(QPoint(0, 0)))
        self.assertTrue(self.c.pet.mask().contains(QPoint(self.c.pet.width() // 2, self.c.pet.height() // 2)))

    def test_click_and_drag_are_distinct(self):
        pet = self.c.pet
        self.c.chat.hide()
        point = QPoint(pet.width() // 2, pet.height() // 2)
        QTest.mouseClick(pet, Qt.LeftButton, pos=point)
        self.assertTrue(self.c.chat.isVisible())
        self.c.chat.hide()
        QTest.mousePress(pet, Qt.LeftButton, pos=point)
        QTest.mouseMove(pet, point - QPoint(35, 20), 10)
        QTest.mouseRelease(pet, Qt.LeftButton, pos=point)
        self.assertFalse(self.c.chat.isVisible())
        self.assertTrue(pet.dragged)

    def test_demo_send_emotion_and_cancel(self):
        self.assertTrue(self.c.send('오늘 너무 피곤해'))
        self.assertFalse(self.c.send('중복 요청'))
        self.wait_done()
        self.assertEqual(len(self.c.store.history), 2)
        self.assertEqual(self.c.pet.emotion, 'cozy')
        self.c.send('안녕')
        self.c.cancel()
        QTest.qWait(700)
        self.assertEqual(len(self.c.store.history), 2)

    def test_real_client_contract_with_mock_server(self):
        self.api_mode()
        self.c.send('hello')
        self.wait_done()
        self.assertEqual(self.c.store.history[-1]['content'], '테스트 답변')
        self.assertEqual(self.c.pet.emotion, 'eureka')
        self.assertEqual(Handler.seen['auth'], 'Bearer fake-key-for-test')
        self.assertEqual(Handler.seen['body']['input'][-1]['content'], 'hello')

    def test_auth_error_recovers_for_retry(self):
        self.api_mode()
        Handler.status = 401
        self.c.send('hello')
        self.wait_done()
        self.assertIn('API 키', self.c.chat.status.text())
        self.assertEqual(self.c.store.history, [])
        Handler.status = 200
        self.c.send('hello again')
        self.wait_done()
        self.assertEqual(len(self.c.store.history), 2)

    def test_cancel_discards_late_http_response(self):
        self.api_mode()
        Handler.delay = .3
        self.c.send('cancel me')
        QTest.qWait(30)
        self.c.cancel()
        QTest.qWait(400)
        self.assertEqual(self.c.store.history, [])
        self.assertFalse(self.c.busy)

    def test_timeout_recovers_without_pending_request(self):
        self.api_mode()
        Handler.delay = .3
        self.c.send('timeout')
        self.c.client.timer.start(20)
        self.wait_done()
        self.assertIn('90초', self.c.chat.status.text())
        self.assertIsNone(self.c.client.reply)
        QTest.qWait(350)

    def test_settings_reject_missing_key_and_clear_history(self):
        dlg = SettingsDialog(self.c)
        dlg.demo.setChecked(False)
        dlg.save()
        self.assertTrue(self.c.store.settings['demo'])
        self.assertIn('API 키', dlg.error.text())
        dlg.demo.setChecked(True)
        self.c.store.history = [{'role': 'user', 'content': 'delete me'}]
        dlg.clear.setChecked(True)
        dlg.save()
        self.assertEqual(self.c.store.history, [])
        dlg.deleteLater()

    def test_each_provider_uses_own_key_and_native_wire_format(self):
        from providers import PRESETS
        for pid in ('openai', 'gemini', 'claude', 'ollama', 'vercel'):
            with self.subTest(provider=pid):
                Handler.provider = pid
                self.c.store.settings.update(provider=pid, model=PRESETS[pid][0], demo=False)
                self.c.vault.set('fake-' + pid if pid != 'ollama' else '', False)
                self.c.send('안녕')
                self.wait_done()
                self.assertEqual(self.c.store.history[-1]['content'], '테스트 답변')
                sent = Handler.seen
                if pid == 'gemini':
                    self.assertEqual(sent['headers'].get('x-goog-api-key'), 'fake-gemini')
                    self.assertIn('contents', sent['body'])
                    self.assertNotIn('?', sent['path'])
                elif pid == 'claude':
                    self.assertEqual(sent['headers'].get('x-api-key'), 'fake-claude')
                    self.assertEqual(sent['headers'].get('anthropic-version'), '2023-06-01')
                elif pid == 'ollama':
                    self.assertIsNone(sent['auth'])
                    self.assertEqual(sent['path'], '/api/chat')
                    self.assertFalse(sent['body']['stream'])
                else:
                    self.assertEqual(sent['auth'], 'Bearer fake-' + pid)
                self.assertNotIn('fake-', json.dumps(sent['body']))

    def test_provider_drafts_custom_models_and_keyless_ollama(self):
        dlg = SettingsDialog(self.c)
        dlg.key.setText('fake-openai')
        dlg.model.setCurrentText('custom-openai-model')
        dlg.provider.setCurrentIndex(1)
        self.assertEqual(dlg.key.text(), '')
        dlg.key.setText('fake-gemini')
        dlg.model.setCurrentText('custom-gemini-model')
        dlg.provider.setCurrentIndex(0)
        self.assertEqual(dlg.key.text(), 'fake-openai')
        self.assertEqual(dlg.model.currentText(), 'custom-openai-model')
        dlg.provider.setCurrentIndex(3)
        dlg.demo.setChecked(False)
        dlg.model.setCurrentText('my-local-model:custom')
        dlg.save()
        self.assertEqual(self.c.store.settings['provider'], 'ollama')
        self.assertFalse(self.c.store.settings['demo'])
        self.assertEqual(self.c.vault.session_key, '')
        self.assertEqual(self.c.vaults['gemini'].session_key, 'fake-gemini')
        self.assertEqual(self.c.store.settings['provider_models']['openai'], 'custom-openai-model')
        restored = Store(self.tmp.name)
        self.assertEqual(restored.settings['model'], 'my-local-model:custom')
        dlg.deleteLater()

    def test_bounce_stays_inside_window_and_walk_uses_directional_assets(self):
        pet = self.c.pet
        pet.hovered = False
        self.c.chat.hide()
        self.c.store.profiles['izuna']['size'] = 400
        pet.reload_size()
        for t in (0, .04, .08, .12, .2, .4, .8, 1.3):
            pet.bounce_start = time.monotonic() - t
            pet.last_visual = None
            pet.update_visual(0)
            self.assertGreaterEqual(pet.draw_y, 0)
            self.assertGreaterEqual(pet.draw_x, 0)
            self.assertLessEqual(pet.draw_x + pet.pix.width(), pet.width())
            self.assertLessEqual(pet.draw_y + pet.pix.height(), pet.height())
        pet.moving_now = True
        pet.direction = -1
        pet.update_visual(0)
        self.assertEqual(pet.last_visual[0], 'walking to left')
        pet.direction = 1
        pet.update_visual(0)
        self.assertEqual(pet.last_visual[0], 'walking to right')
        self.c.store.settings['click_effect'] = False
        self.assertEqual(pet.bounce_parameters(.1), (1, 1, 0, 0))

    def test_ollama_installed_models_refresh(self):
        dlg = SettingsDialog(self.c)
        dlg.provider.setCurrentIndex(3)
        dlg.catalog.manager = LocalManager(dlg.catalog)
        dlg.refresh_models()
        deadline = time.monotonic() + 2
        while not dlg.refresh.isEnabled() and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertTrue(dlg.refresh.isEnabled())
        self.assertGreaterEqual(dlg.model.findText('local-test:8b'), 0)
        dlg.catalog.cancel()
        dlg.deleteLater()

if __name__ == '__main__':
    unittest.main()
