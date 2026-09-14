"""Manual investment records. Never connects to a brokerage or places orders."""
import calendar
import copy
import math
from datetime import date
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QInputDialog, QMessageBox)


def monthly_result(month, opening, closing, flows):
    start = date.fromisoformat(month + '-01')
    days = calendar.monthrange(start.year, start.month)[1]
    opening, closing = float(opening), float(closing)
    if not all(math.isfinite(v) and v >= 0 for v in (opening, closing)):
        raise ValueError('자산은 유한한 0 이상의 금액이어야 합니다.')
    net = weighted = 0
    for stamp, amount in flows:
        day = date.fromisoformat(stamp)
        amount = float(amount)
        if day.strftime('%Y-%m') != month or not math.isfinite(amount):
            raise ValueError('입출금 날짜와 금액을 확인하세요.')
        net += amount
        weighted += (days - day.day) / days * amount
    profit = closing - opening - net
    denominator = opening + weighted
    return profit, profit / denominator if denominator > 0 else None


class RecordView(QWidget):
    def __init__(self, stock, kind):
        super().__init__(); self.stock = stock; self.kind = kind
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        titles = {'watchlist': '관심종목 추가', 'trades': '매매 기록 추가', 'months': '월별 성과 입력'}
        add = QPushButton(titles[kind]); add.clicked.connect(self.add); row.addWidget(add)
        delete = QPushButton('선택 기록 삭제'); delete.clicked.connect(self.remove); row.addWidget(delete)
        layout.addLayout(row)
        self.table = QTableWidget(0, 1); self.table.setHorizontalHeaderLabels([titles[kind]])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.table)
        if kind == 'watchlist':
            self.table.cellDoubleClicked.connect(self.chart)
            self.table.setContextMenuPolicy(Qt.CustomContextMenu)
            self.table.customContextMenuRequested.connect(self.menu)
        self.refresh()

    def rows(self): return self.stock.c.store.investments[self.kind]

    def save(self, rows):
        store = self.stock.c.store
        old = copy.deepcopy(store.investments[self.kind])
        store.investments[self.kind] = rows
        try: store.save()
        except OSError as exc:
            store.investments[self.kind] = old
            QMessageBox.warning(self, '저장 실패', str(exc)); return
        self.refresh()

    def add(self):
        prompts = {
            'watchlist': ('관심종목', '시장,종목코드,이름 (시장: US/KRX/KOSDAQ)\n예: US,AAPL,Apple'),
            'trades': ('매매 기록 · 보유수량은 별도로 수정', '날짜,시장,종목코드,계좌,매수/매도,수량,가격\n예: 2026-09-14,US,AAPL,기본 계좌,매수,1,200'),
            'months': ('월별 성과 · 원화 환산 금액 직접 입력', '첫 줄: 연-월,월초 총자산,월말 총자산\n다음 줄: 입출금 날짜,금액 (입금 + / 출금 -)\n매매대금은 입출금에 넣지 마세요. 일말 입출금 기준 Modified Dietz 추정값입니다.')}
        title, prompt = prompts[self.kind]
        text, ok = QInputDialog.getMultiLineText(self, title, prompt)
        if not ok: return
        try:
            from stocks import provider_symbol
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            values = [v.strip() for v in lines[0].split(',')]
            if self.kind == 'watchlist':
                market, symbol, name = values; market = market.upper(); symbol = symbol.upper()
                provider_symbol(symbol, market)
                item = dict(market=market, symbol=symbol, name=name)
                if any(r['market'] == market and r['symbol'] == symbol for r in self.rows()):
                    raise ValueError('이미 등록된 관심종목입니다.')
            elif self.kind == 'trades':
                stamp, market, symbol, account, side, qty, price = values
                date.fromisoformat(stamp); provider_symbol(symbol, market)
                qty, price = float(qty), float(price)
                if side not in ('매수', '매도') or not account or not all(math.isfinite(v) and v > 0 for v in (qty, price)):
                    raise ValueError('매매 구분·계좌·수량·가격을 확인하세요.')
                item = dict(date=stamp, market=market, symbol=symbol.upper(), account=account, side=side, quantity=qty, price=price)
            else:
                month, opening, closing = values
                flows = [line.split(',') for line in lines[1:]]
                flows = [(stamp.strip(), float(amount)) for stamp, amount in flows]
                profit, rate = monthly_result(month, opening, closing, flows)
                item = dict(month=month, opening=float(opening), closing=float(closing), flows=flows)
                if any(r['month'] == month for r in self.rows()):
                    raise ValueError('같은 월이 있습니다. 기존 기록을 삭제한 뒤 입력하세요.')
            self.save(self.rows() + [item])
        except (ValueError, IndexError, TypeError) as exc:
            QMessageBox.warning(self, '입력 확인', str(exc))

    def remove(self):
        index = self.table.currentRow()
        if index < 0: return
        if QMessageBox.question(self, '기록 삭제', '선택 기록을 삭제할까요? 보유수량은 변경되지 않습니다.') != QMessageBox.Yes: return
        rows = list(self.rows()); rows.pop(index); self.save(rows)

    def refresh(self):
        self.table.setRowCount(len(self.rows()))
        for i, item in enumerate(self.rows()):
            if self.kind == 'watchlist': text = f"{item['market']} / {item['symbol']} · {item['name']} · 더블클릭: 차트"
            elif self.kind == 'trades': text = f"{item['date']} · {item['account']} · {item['symbol']} {item['side']} {item['quantity']:g}주 @ {item['price']:g} · 기록 전용"
            else:
                profit, rate = monthly_result(item['month'], item['opening'], item['closing'], item['flows'])
                result = '계산 불가' if rate is None else f'{rate:+.2%}'
                text = f"{item['month']} · 월초 {item['opening']:,.0f}원 → 월말 {item['closing']:,.0f}원 · 손익 {profit:+,.0f}원 · 추정 {result}"
            import json
            cell = QTableWidgetItem(text)
            cell.setToolTip(json.dumps(item, ensure_ascii=False, indent=2))
            self.table.setItem(i, 0, cell)

    def chart(self, row, column=0):
        from charts import ChartWindow
        from stocks import provider_symbol
        item = self.rows()[row]
        ChartWindow(provider_symbol(item['symbol'], item['market']), self).exec()

    def menu(self, point):
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        from urllib.parse import quote
        from stocks import provider_symbol
        row = self.table.rowAt(point.y())
        if row < 0: return
        item = self.rows()[row]; menu = QMenu(self)
        menu.addAction('내부 차트', lambda: self.chart(row))
        tv = item['symbol'] if item['market'] == 'US' else 'KRX:' + item['symbol']
        for title, url in [('TradingView', 'https://www.tradingview.com/chart/?symbol=' + quote(tv)), ('Yahoo Finance', 'https://finance.yahoo.com/quote/' + quote(provider_symbol(item['symbol'], item['market'])))]:
            menu.addAction(title, lambda checked=False, url=url: QDesktopServices.openUrl(QUrl(url)))
        menu.exec(self.table.mapToGlobal(point))
