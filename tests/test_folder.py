import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from folder_server import FolderTools
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from app import Controller, STYLE
from core import Store

APP=QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False)

class FolderTests(unittest.TestCase):
    def test_traversal_and_links(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            service=FolderTools(root)
            for name in ['../out.txt','/tmp/x','C:\\secret.txt','x/../../a','a:stream','CON.txt','.env','a./x']:
                with self.assertRaises(ValueError): service.path(name)
            Path(root,'link').symlink_to(outside,target_is_directory=True)
            with self.assertRaises(ValueError): service.path('link/x.txt')
            Path(root,'a.txt').write_text('x')
            os.link(Path(root,'a.txt'),Path(root,'b.txt'))
            with self.assertRaises(ValueError): service.read('a.txt')

    def test_move_write_and_collision(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root); (p/'a.txt').write_text('읽은 내용',encoding='utf-8')
            service=FolderTools(root); service.listing(); self.assertEqual(service.read('a.txt'),'읽은 내용')
            moves=[dict(source='a.txt',destination='문서/a.txt')]
            writes=[dict(path='감상.txt',content='문서에 대한 감상')]
            service.apply(moves,writes)
            self.assertEqual((p/'문서/a.txt').read_text(encoding='utf-8'),'읽은 내용')
            self.assertFalse((p/'a.txt').exists())
            with self.assertRaises(ValueError): service.apply([],writes)
            self.assertEqual((p/'감상.txt').read_text(encoding='utf-8'),'문서에 대한 감상')

    def test_changed_original_and_rollback(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root); (p/'a.txt').write_text('a'); (p/'b.txt').write_text('b')
            service=FolderTools(root); service.listing(); (p/'a.txt').write_text('changed')
            moves=[dict(source='a.txt',destination='docs/a.txt'),dict(source='b.txt',destination='docs/b.txt')]
            with self.assertRaises(ValueError): service.apply(moves,[])
            service.listing()
            real=os.link
            def fail_second(src,dst,**kw):
                if Path(dst).name=='b.txt': raise OSError('simulated failure')
                return real(src,dst,**kw)
            with patch('folder_server.os.link',side_effect=fail_second):
                with self.assertRaises(OSError): service.apply(moves,[])
            self.assertEqual((p/'a.txt').read_text(),'changed')
            self.assertTrue((p/'b.txt').exists()); self.assertFalse((p/'docs').exists())

    def test_binary_and_large_text(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root); (p/'photo.jpg').write_bytes(b'fake'); (p/'large.txt').write_bytes(b'x'*64001)
            service=FolderTools(root)
            for name in ['photo.jpg','large.txt']:
                with self.assertRaises(ValueError): service.read(name)

    def test_chat_to_real_mcp_execution_and_layout(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as files:
            file=Path(files,'memo.txt'); file.write_text('오늘은 피아노 연습을 했다.',encoding='utf-8')
            c=Controller(Store(root),with_tray=False); c.startup_timer.stop()
            try:
                c.store.settings.update(demo=False,provider='ollama'); c.folder_root=files
                agent=c.folder_agent
                def model(*args):
                    if agent.steps==2:
                        self.assertEqual(agent.transcript[-1]['arguments']['path'],'memo.txt')
                        self.assertIn('피아노',json.dumps(agent.transcript,ensure_ascii=False))
                    proposal = {'tool':'read_text','arguments':{'path':'memo.txt'}} if agent.steps==1 else {'tool':'apply_plan','arguments':{'moves':[{'source':'memo.txt','destination':'문서/memo.txt'}],'writes':[{'path':'감상.txt','content':'피아노 연습 기록을 읽었습니다.'}]}}
                    QTimer.singleShot(0,lambda: agent.proposal(json.dumps(proposal), 'thinking'))
                agent.client.send=model
                timer=QTimer(); timer.timeout.connect(lambda: agent.review.accept() if agent.review else None); timer.start(20)
                self.assertTrue(c.send('폴더를 정리하고 읽은 감상을 감상.txt로 저장해줘'))
                for _ in range(250):
                    QTest.qWait(20)
                    if not c.busy: break
                timer.stop()
                self.assertFalse(c.busy)
                self.assertTrue(Path(files,'문서/memo.txt').exists())
                self.assertIn('피아노',Path(files,'감상.txt').read_text(encoding='utf-8'))
                self.assertIn('완료',c.store.history[-1]['content'])
                c.stocks.refresh=lambda:None; c.stocks.auto_timer.stop()
                c.store.portfolio=[dict(symbol='AAPL',market='US',name='Apple',quantity=2,average=100) for _ in range(20)]
                c.stocks.render(); c.stocks.resize(850,560); c.stocks.show(); QTest.qWait(50)
                before=c.stocks.table.viewport().height()
                c.stocks.view_picker.setCurrentIndex(1); QTest.qWait(50)
                c.stocks.view_picker.setCurrentIndex(0); QTest.qWait(50)
                self.assertGreaterEqual(c.stocks.table.viewport().height(),250)
                self.assertEqual(before,c.stocks.table.viewport().height())
                self.assertFalse(c.stocks.position_dialog.isVisible())
            finally:
                c.shutdown(); c.pet.hide(); c.chat.hide(); c.stocks.hide()

    def test_rejected_plan_never_writes(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as files:
            c=Controller(Store(root),with_tray=False); c.startup_timer.stop()
            try:
                c.folder_root=files; agent=c.folder_agent; agent.running=True
                with patch.object(QDialog,'exec',return_value=QDialog.Rejected):
                    agent.proposal(json.dumps({'tool':'apply_plan','arguments':{'moves':[],'writes':[{'path':'x.txt','content':'x'}]}}),'cozy')
                self.assertFalse(Path(files,'x.txt').exists()); self.assertFalse(agent.running)
            finally:
                c.shutdown(); c.pet.hide(); c.chat.hide(); c.stocks.hide()

    def test_cancel_ignores_late_model_proposal(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as files:
            c=Controller(Store(root),with_tray=False); c.startup_timer.stop()
            try:
                c.folder_root=files; c.store.settings.update(demo=False,provider='ollama')
                c.folder_agent.client.send=lambda *args:None
                c.send('정리해줘'); QTest.qWait(80); c.cancel()
                c.folder_agent.proposal(json.dumps({'tool':'apply_plan','arguments':{'moves':[],'writes':[{'path':'late.txt','content':'x'}]}}),'cozy')
                self.assertFalse(c.busy); self.assertFalse(Path(files,'late.txt').exists())
            finally:
                c.shutdown(); c.pet.hide(); c.chat.hide(); c.stocks.hide()
