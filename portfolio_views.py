"""Portfolio valuation views; missing/stale prices never silently disappear."""
import math
import time
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QCheckBox, QLabel, QDoubleSpinBox, QTableWidget, QTableWidgetItem, QMessageBox

COLORS = ['#81dce8', '#b39ddb', '#ffad75', '#7ed499', '#ff8394', '#8da9f5', '#dbce85', '#7e8e9f']


def allocations(positions, quotes, group='symbol', fx=None, include_cash=True, small=.02, now=None):
    fx = fx or {'KRW': 1}
    now = time.time() if now is None else now
    totals, members, warnings = {}, {}, []
    for index, item in enumerate(positions):
        if item.get('cash') and not include_cash:
            continue
        quote = quotes.get(index, {})
        currency = item.get('currency') or quote.get('currency') or ('USD' if item['market'] == 'US' else 'KRW')
        try:
            price = 1 if item.get('cash') else float(quote['price'])
            rate = float(fx[currency])
            quantity = float(item['quantity'])
            if not all(math.isfinite(v) and v >= 0 for v in (price, rate, quantity)) or rate == 0:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            warnings.append(item['symbol'] + ': 가격/환율 누락'); continue
        if not item.get('cash') and (not quote.get('timestamp') or now - quote['timestamp'] > 86400):
            warnings.append(item['symbol'] + ': 24시간 이상 경과 또는 기준시각 미확인')
        key = currency if group == 'currency' else str(item.get(group) or ('미분류' if group == 'sector' else '수동 계좌' if group == 'account' else item['symbol']))
        totals[key] = totals.get(key, 0) + price * quantity * rate
        members.setdefault(key, []).append(item['symbol'])
    total = sum(totals.values())
    rows, other, other_members = [], 0, []
    for key, value in sorted(totals.items(), key=lambda v: -v[1]):
        if value <= 0: continue
        if total and value / total < small:
            other += value; other_members.extend(members[key])
        else:
            rows.append((key, value, value / total, members[key]))
    if other:
        rows.append(('기타', other, other / total, other_members))
    return rows, warnings


class Donut(QWidget):
    selected = Signal(int)
    def __init__(self):
        super().__init__(); self.rows = []; self.setMinimumSize(240, 220)
    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        size = min(self.width(), self.height()) - 30
        rect = QRectF((self.width() - size) / 2, (self.height() - size) / 2, size, size)
        angle = 90 * 16
        for i, row in enumerate(self.rows):
            span = round(row[2] * 360 * 16)
            p.setPen(Qt.NoPen); p.setBrush(QColor(COLORS[i % len(COLORS)]))
            p.drawPie(rect, angle, -span); angle -= span
        inner = rect.adjusted(size * .28, size * .28, -size * .28, -size * .28)
        p.setBrush(QColor('#121e2b')); p.drawEllipse(inner)
        p.setPen(QColor('#e6edf5'))
        p.drawText(inner, Qt.AlignCenter, '평가 가능 자산\n' + f'{sum(r[1] for r in self.rows):,.0f}원')
    def mousePressEvent(self, event):
        dx, dy = event.position().x() - self.width() / 2, event.position().y() - self.height() / 2
        radius = (min(self.width(), self.height()) - 30) / 2
        if not radius * .44 <= math.hypot(dx, dy) <= radius:
            return
        fraction = (math.atan2(dx, -dy) % (2 * math.pi)) / (2 * math.pi)
        end = 0
        for i, row in enumerate(self.rows):
            end += row[2]
            if fraction < end:
                self.selected.emit(i); return


class AllocationView(QWidget):
    def __init__(self, stock_window):
        super().__init__(); self.stock = stock_window
        layout = QVBoxLayout(self); controls = QHBoxLayout()
        self.group = QComboBox()
        for title, key in [('종목별', 'symbol'), ('섹터별', 'sector'), ('계좌별', 'account'), ('통화별', 'currency')]:
            self.group.addItem(title, key)
        self.cash = QCheckBox('현금 포함'); self.cash.setChecked(True)
        self.fx = QDoubleSpinBox(); self.fx.setRange(0, 100000); self.fx.setDecimals(2)
        self.fx.setPrefix('USD/KRW 수동 '); self.fx.setSpecialValueText('환율 미설정')
        self.threshold = QDoubleSpinBox(); self.threshold.setRange(1, 100); self.threshold.setValue(30); self.threshold.setSuffix('% 집중도')
        options = self.stock.c.store.settings.get('investment_options', {})
        self.fx.setValue(float(options.get('fx', 0)))
        self.threshold.setValue(float(options.get('threshold', 30)))
        self.cash.setChecked(options.get('cash', True))
        self.group.setCurrentIndex(max(0, self.group.findData(options.get('group', 'symbol'))))
        for widget in (self.group, self.cash): controls.addWidget(widget)
        controls.addStretch()
        layout.addLayout(controls)
        settings = QHBoxLayout()
        settings.addWidget(self.fx); settings.addWidget(self.threshold)
        layout.addLayout(settings)
        content = QHBoxLayout()
        self.donut = Donut(); content.addWidget(self.donut, 1)
        self.legend = QTableWidget(0, 3); self.legend.setHorizontalHeaderLabels(['분류', '원화 평가액', '비중'])
        self.legend.verticalHeader().hide()
        self.legend.horizontalHeader().setStretchLastSection(True)
        self.legend.setEditTriggers(QTableWidget.NoEditTriggers); content.addWidget(self.legend, 1)
        layout.addLayout(content, 1)
        self.warning = QLabel(); self.warning.setWordWrap(True); self.warning.setMaximumHeight(44); layout.addWidget(self.warning)
        self.group.currentIndexChanged.connect(self.refresh); self.cash.toggled.connect(self.refresh)
        self.fx.valueChanged.connect(self.refresh); self.threshold.valueChanged.connect(self.refresh)
        for signal in (self.group.currentIndexChanged, self.cash.toggled, self.fx.valueChanged, self.threshold.valueChanged):
            signal.connect(self.save_options)
        self.donut.selected.connect(self.detail)
        self.legend.cellDoubleClicked.connect(lambda row, col: self.detail(row))
    def save_options(self, *_):
        self.stock.c.store.settings['investment_options'] = dict(fx=self.fx.value(), threshold=self.threshold.value(), cash=self.cash.isChecked(), group=self.group.currentData())
        self.stock.c.persist()
    def detail(self, index):
        if 0 <= index < len(self.donut.rows):
            row = self.donut.rows[index]
            QMessageBox.information(self, row[0], '\n'.join(row[3]))
    def refresh(self):
        fx = {'KRW': 1}
        if self.fx.value(): fx['USD'] = self.fx.value()
        rows, warnings = allocations(self.stock.c.store.portfolio, self.stock.quotes, self.group.currentData(), fx, self.cash.isChecked())
        self.donut.rows = rows; self.donut.update(); self.legend.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate((row[0], f'{row[1]:,.0f}원', f'{row[2]:.2%}' + (' · 집중' if row[2] * 100 > self.threshold.value() else ''))):
                cell = QTableWidgetItem(value); cell.setForeground(QColor(COLORS[i % len(COLORS)])); self.legend.setItem(i, j, cell)
        self.legend.resizeColumnsToContents()
        self.warning.setText('평가 가능한 자산 기준 · 수동 환율' + (f' · 가격/환율 주의 {len(warnings)}건 (마우스로 확인)' if warnings else ''))
        self.warning.setToolTip('\n'.join(warnings))
