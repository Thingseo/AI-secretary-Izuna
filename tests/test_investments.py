import unittest
import tempfile
from pathlib import Path
from investment_tools import monthly_result
from core import Store, atomic_json

class ManualInvestmentTests(unittest.TestCase):
    def test_manual_ui_and_private_audit(self):
        from PySide6.QtWidgets import QApplication
        from app import Controller
        from mcp_ui import McpDialog
        import json
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root:
            c = Controller(Store(root), with_tray=False); c.startup_timer.stop()
            try:
                stock = c.stocks; stock.auto_timer.stop(); stock.refresh = lambda: None
                stock.symbol.setText('AAPL'); stock.quantity.setValue(2); stock.account.setText('A'); stock.add_position()
                stock.account.setText('B'); stock.add_position()
                self.assertEqual(len(c.store.portfolio), 2)
                stock.cash_position.setChecked(True); stock.quantity.setValue(100); stock.add_position()
                stock.refresh = lambda: None
                self.assertEqual(stock.table.item(2, 4).text(), '$100.00')
                stock.allocation.fx.setValue(1400)
                self.assertEqual(Store(root).settings['investment_options']['fx'], 1400)
                dialog = McpDialog(c)
                dialog.key.setText('secret-token'); dialog.arguments.setPlainText('{"password":"secret-pass"}')
                dialog.record_event('도구 실행 요청')
                audit = (Path(root) / 'mcp-events.json').read_text()
                self.assertNotIn('secret', audit); self.assertEqual(len(json.loads(audit)), 1)
                dialog.reject()
            finally:
                c.shutdown(); c.chat.hide(); c.pet.hide(); c.stocks.hide()

    def test_return_without_flows(self):
        self.assertEqual(monthly_result('2026-09', 100, 110, []), (10, .1))

    def test_end_month_deposit(self):
        self.assertEqual(monthly_result('2026-09', 100, 160, [('2026-09-30', 50)]), (10, .1))

    def test_weighted_deposit(self):
        profit, rate = monthly_result('2026-09', 100, 220, [('2026-09-15', 100)])
        self.assertEqual(profit, 20); self.assertAlmostEqual(rate, 20 / 150)

    def test_invalid_and_empty_capital(self):
        self.assertEqual(monthly_result('2026-09', 0, 0, []), (0, None))
        with self.assertRaises(ValueError): monthly_result('2026-09', float('nan'), 1, [])
        with self.assertRaises(ValueError): monthly_result('2026-09', 1, 1, [('2026-10-01', 1)])

    def test_migration_shared_snapshot(self):
        with tempfile.TemporaryDirectory() as root:
            atomic_json(Path(root) / 'portfolio.json', [dict(symbol='AAPL', market='US', quantity=2, average=100)])
            store = Store(root); store.portfolio[0].update(account='A', sector='IT')
            store.investments['watchlist'] = [dict(symbol='MSFT', market='US', name='Microsoft')]
            store.save(); atomic_json(Path(root) / 'portfolio.json', [])
            restored = Store(root)
            self.assertEqual(restored.portfolio[0]['account'], 'A')
            self.assertEqual(restored.investments['watchlist'][0]['symbol'], 'MSFT')

    def test_corrupt_snapshot(self):
        with tempfile.TemporaryDirectory() as root:
            atomic_json(Path(root) / 'portfolio-state.json', {'version': 999})
            with self.assertRaises(ValueError): Store(root)
