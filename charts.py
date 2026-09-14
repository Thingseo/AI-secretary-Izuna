"""Daily price viewer. All network I/O stays asynchronous in Qt."""
import json
import math
from datetime import datetime, timezone
from urllib.parse import quote
from PySide6.QtCore import Qt, QUrl, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QPainterPath
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QCheckBox, QLabel, QWidget


def daily_bars(data):
    result = data['chart']['result'][0]
    values = result['indicators']['quote'][0]
    bars, skipped = [], 0
    for i, stamp in enumerate(result.get('timestamp', [])):
        try:
            row = [float(values[key][i]) for key in ('open', 'high', 'low', 'close')]
            if not all(math.isfinite(v) and v > 0 for v in row):
                raise ValueError()
            if row[1] < max(row[0], row[2], row[3]) or row[2] > min(row[0], row[3]):
                raise ValueError()
            volume = values.get('volume', [])[i] or 0
            bars.append((int(stamp), *row, max(0, float(volume))))
        except (ValueError, TypeError, IndexError):
            skipped += 1
    if not bars:
        raise ValueError('유효한 일봉 데이터 없음')
    warnings = []
    if skipped:
        warnings.append(f'결측·오류 일봉 {skipped}개 제외')
    if any(b[0] - a[0] > 7 * 86400 for a, b in zip(bars, bars[1:])):
        warnings.append('7일 이상 데이터 공백: 휴장 또는 누락 확인 필요')
    if result.get('events', {}).get('splits'):
        warnings.append('주식분할 포함: 공급사 가격 조정 기준 확인 필요')
    return bars, result.get('meta', {}), warnings


def moving_average(values, length):
    return [None if i + 1 < length else sum(values[i + 1 - length:i + 1]) / length for i in range(len(values))]


def compare_values(bars, other):
    # Match UTC calendar dates; no forward-filling across unmatched sessions.
    lookup = {datetime.fromtimestamp(b[0], timezone.utc).date(): b[4] for b in other}
    values = [lookup.get(datetime.fromtimestamp(b[0], timezone.utc).date()) for b in bars]
    first = next((i for i, v in enumerate(values) if v is not None), None)
    if first is None: return [None] * len(bars)
    return [None if value is None else value / values[first] * bars[first][4] for value in values]


def rsi(values, length=14):
    result = [None] * len(values)
    if len(values) <= length:
        return result
    diffs = [b - a for a, b in zip(values, values[1:])]
    gain = sum(max(v, 0) for v in diffs[:length]) / length
    loss = sum(max(-v, 0) for v in diffs[:length]) / length
    def score():
        return 50 if gain == loss == 0 else 100 if loss == 0 else 100 - 100 / (1 + gain / loss)
    result[length] = score()
    for i in range(length + 1, len(values)):
        gain = (gain * (length - 1) + max(diffs[i - 1], 0)) / length
        loss = (loss * (length - 1) + max(-diffs[i - 1], 0)) / length
        result[i] = score()
    return result


class PriceCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bars = []
        self.trades = []
        self.candles = True
        self.volume = True
        self.show_rsi = False
        self.averages = [20]
        self.count = 250
        self.offset = 0
        self.comparison = []
        self.setMinimumSize(480, 260)
        self.setMouseTracking(True)

    def wheelEvent(self, event):
        self.count = max(10, min(max(10, len(self.bars)), round(self.count * (0.8 if event.angleDelta().y() > 0 else 1.25))))
        self.update()

    def mousePressEvent(self, event):
        self.drag_x = event.position().x()
        self.drag_offset = self.offset

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and hasattr(self, 'drag_x'):
            self.offset = max(0, min(max(0, len(self.bars) - self.count), self.drag_offset + round((event.position().x() - self.drag_x) * self.count / max(1, self.width() - 85))))
            self.update()
        elif self.bars:
            end = len(self.bars) - self.offset
            start = max(0, end - self.count)
            index = min(end - 1, max(start, start + int((event.position().x() - 55) / max(1, self.width() - 85) * (end - start))))
            b = self.bars[index]
            self.setToolTip(f'{datetime.fromtimestamp(b[0]):%Y-%m-%d}\nO {b[1]:,.2f} H {b[2]:,.2f} L {b[3]:,.2f} C {b[4]:,.2f}\n거래량 {b[5]:,.0f}')
            stamp = datetime.fromtimestamp(b[0], timezone.utc).strftime('%Y-%m-%d')
            records = [f"{t['account']} {t['side']} {t['quantity']:g}주 @ {t['price']:g}" for t in self.trades if t['date'] == stamp]
            if records: self.setToolTip(self.toolTip() + '\n' + '\n'.join(records))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor('#0e1925'))
        if not self.bars:
            p.setPen(QColor('#9bb0c2'))
            p.drawText(self.rect(), Qt.AlignCenter, '일봉 데이터 대기 중')
            return
        end = len(self.bars) - self.offset
        start = max(0, end - self.count)
        bars = self.bars[start:end]
        lo, hi = min(b[3] for b in bars), max(b[2] for b in bars)
        comparison = compare_values(bars, self.comparison)
        available = [v for v in comparison if v is not None]
        if available:
            lo, hi = min(lo, min(available)), max(hi, max(available))
        spread = max(hi - lo, hi * .01)
        lo, hi = lo - spread * .05, hi + spread * .05
        chart = QRectF(55, 20, self.width() - 85, self.height() * (.56 if self.show_rsi else .7) - 20)
        step = chart.width() / len(bars)
        def x(i): return chart.left() + (i + .5) * step
        def y(v): return chart.bottom() - (v - lo) / (hi - lo) * chart.height()
        p.setPen(QColor('#637b91'))
        for j in range(5):
            price = lo + (hi - lo) * j / 4
            p.drawText(QRectF(0, y(price) - 10, 52, 20), Qt.AlignRight, f'{price:,.1f}')
            p.drawLine(QPointF(chart.left(), y(price)), QPointF(chart.right(), y(price)))
        if self.candles:
            for i, b in enumerate(bars):
                color = QColor('#ff707d' if b[4] >= b[1] else '#73a7ff')
                p.setPen(color)
                p.drawLine(QPointF(x(i), y(b[2])), QPointF(x(i), y(b[3])))
                p.fillRect(QRectF(x(i) - max(1, step * .32), min(y(b[1]), y(b[4])), max(1, step * .64), max(1, abs(y(b[1]) - y(b[4])))), color)
        def line(values, color, mapper=y):
            path = QPainterPath()
            begun = False
            for i, v in enumerate(values):
                if v is None:
                    begun = False
                    continue
                point = QPointF(x(i), mapper(v))
                if begun: path.lineTo(point)
                else: path.moveTo(point)
                begun = True
            p.setPen(QPen(QColor(color), 1.5))
            p.drawPath(path)
        closes = [b[4] for b in self.bars]
        for i, bar in enumerate(bars):
            stamp = datetime.fromtimestamp(bar[0], timezone.utc).strftime('%Y-%m-%d')
            records = [t for t in self.trades if t['date'] == stamp]
            if records:
                p.setPen(QColor('#ffdf80'))
                sides = ''.join('▲' if t['side'] == '매수' else '▼' for t in records)
                p.drawText(QPointF(x(i) - 6, y(bar[2]) - 4), sides)
        if not self.candles:
            line(closes[start:end], '#81dce8')
        if available:
            line(comparison, '#ffffff')
        for period, color in zip((5, 20, 60, 120), ('#f4d35e', '#b39ddb', '#7cd992', '#f89c65')):
            if period in self.averages:
                line(moving_average(closes, period)[start:end], color)
        if self.volume:
            max_volume = max(1, max(b[5] for b in bars))
            bottom = self.height() - 25
            for i, b in enumerate(bars):
                h = b[5] / max_volume * self.height() * .15
                p.fillRect(QRectF(x(i) - step * .3, bottom - h, max(1, step * .6), h), QColor('#365a75'))
        if self.show_rsi:
            top = chart.bottom() + 20
            line(rsi(closes)[start:end], '#d3a4ff', lambda v: top + (100 - v) / 100 * self.height() * .15)
            p.drawText(QPointF(5, top + 12), 'RSI14')
        p.setPen(QColor('#9bb0c2'))
        p.drawText(QPointF(chart.left(), self.height() - 5), datetime.fromtimestamp(bars[0][0]).strftime('%Y-%m-%d'))
        p.drawText(QPointF(chart.right() - 85, self.height() - 5), datetime.fromtimestamp(bars[-1][0]).strftime('%Y-%m-%d'))


class ChartWindow(QDialog):
    def __init__(self, symbol, parent=None):
        super().__init__(parent)
        self.symbol = symbol
        self.setWindowTitle(symbol + ' · 내부 차트')
        self.resize(900, 640)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.period = QComboBox()
        for title, key in [('1개월', '1mo'), ('3개월', '3mo'), ('6개월', '6mo'), ('1년', '1y'), ('3년', '5y'), ('전체', 'max')]:
            self.period.addItem(title, key)
        self.period.setCurrentIndex(3)
        row.addWidget(self.period)
        self.canvas = PriceCanvas()
        self.kind = QComboBox()
        self.kind.addItems(['캔들', '라인'])
        self.kind.currentIndexChanged.connect(self.options)
        row.addWidget(self.kind)
        self.volume = QCheckBox('거래량'); self.volume.setChecked(True)
        self.rsi = QCheckBox('RSI')
        self.mas = []
        for n in (5, 20, 60, 120):
            checkbox = QCheckBox(f'MA{n}')
            checkbox.setChecked(n == 20)
            checkbox.toggled.connect(self.options)
            self.mas.append((n, checkbox)); row.addWidget(checkbox)
        for checkbox in (self.volume, self.rsi):
            row.addWidget(checkbox); checkbox.toggled.connect(self.options)
        layout.addLayout(row)
        self.compare = QComboBox()
        for title, key in [('비교 없음', ''), ('SPY 비교', 'SPY'), ('QQQ 비교', 'QQQ'), ('SOXX 비교', 'SOXX'), ('KOSPI 비교', '^KS11')]:
            self.compare.addItem(title, key)
        self.compare.currentIndexChanged.connect(self.fetch_comparison)
        layout.addWidget(self.compare)
        layout.addWidget(self.canvas, 1)
        self.status = QLabel('휠: 확대·축소 / 드래그: 좌우 이동 / 마우스: 가격 확인')
        self.status.setWordWrap(True); layout.addWidget(self.status)
        self.manager = QNetworkAccessManager(self)
        self.reply = None
        self.compare_reply = None
        self.period.currentIndexChanged.connect(self.fetch)
        self.finished.connect(self.cancel)
        self.fetch()

    def options(self):
        self.canvas.candles = self.kind.currentIndex() == 0
        self.canvas.volume = self.volume.isChecked()
        self.canvas.show_rsi = self.rsi.isChecked()
        self.canvas.averages = [n for n, cb in self.mas if cb.isChecked()]
        self.canvas.update()

    def cancel(self):
        if self.reply:
            reply, self.reply = self.reply, None
            reply.abort()
        if self.compare_reply:
            reply, self.compare_reply = self.compare_reply, None
            reply.abort()

    def fetch_comparison(self):
        if self.compare_reply:
            reply, self.compare_reply = self.compare_reply, None; reply.abort()
        self.canvas.comparison = []; self.canvas.update()
        if not self.compare.currentData() or not self.canvas.bars: return
        request = QNetworkRequest(QUrl('https://query1.finance.yahoo.com/v8/finance/chart/' + quote(self.compare.currentData(), safe='') + '?interval=1d&range=' + self.period.currentData()))
        request.setTransferTimeout(15000)
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.ManualRedirectPolicy)
        request.setRawHeader(b'User-Agent', b'IzunaDesktop/0.5')
        reply = self.compare_reply = self.manager.get(request)
        def finish():
            if reply is not self.compare_reply:
                reply.deleteLater(); return
            self.compare_reply = None
            try:
                if reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) != 200: raise ValueError()
                bars, _, _ = daily_bars(json.loads(bytes(reply.readAll())))
                self.canvas.comparison = bars; self.canvas.update()
                self.status.setText(self.status.text().split('\n비교:')[0] + '\n비교: 흰색 선 · 화면의 첫 공통 거래일 가격에 상대수익률을 맞춤. 배당·환율 미반영, UTC 날짜 기준.')
            except (ValueError, TypeError, KeyError, IndexError):
                self.status.setText(self.status.text().split('\n비교:')[0] + '\n비교: 데이터 수신 실패')
            finally: reply.deleteLater()
        reply.finished.connect(finish)

    def fetch(self):
        self.cancel()
        self.canvas.bars = []; self.canvas.update()
        self.canvas.comparison = []
        request = QNetworkRequest(QUrl('https://query1.finance.yahoo.com/v8/finance/chart/' + quote(self.symbol, safe='') + '?interval=1d&events=splits&range=' + self.period.currentData()))
        request.setTransferTimeout(15000)
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.ManualRedirectPolicy)
        request.setRawHeader(b'User-Agent', b'IzunaDesktop/0.5')
        reply = self.reply = self.manager.get(request)
        self.status.setText('일봉 불러오는 중…')
        reply.finished.connect(lambda: self.loaded(reply))

    def loaded(self, reply):
        if reply is not self.reply:
            reply.deleteLater(); return
        self.reply = None
        try:
            if reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) != 200:
                raise ValueError('시세 서버 응답 실패')
            bars, meta, warnings = daily_bars(json.loads(bytes(reply.readAll())))
            if self.period.currentText() == '3년':
                cutoff = bars[-1][0] - 3 * 365.25 * 86400
                bars = [b for b in bars if b[0] >= cutoff]
            self.canvas.bars = bars
            self.canvas.offset = 0; self.canvas.count = len(bars)
            self.canvas.update()
            self.status.setText(f"{self.symbol} · {meta.get('currency', '')} · 종가 {bars[-1][4]:,.2f} · 일봉 {datetime.fromtimestamp(bars[-1][0]):%Y-%m-%d %H:%M} · 비공식/지연 가능\n" + ' / '.join(warnings or ['휠 확대·축소 / 드래그 좌우 이동 / 마우스 가격 확인']))
            self.fetch_comparison()
        except (ValueError, KeyError, IndexError, TypeError):
            self.status.setText('일봉을 가져오지 못했습니다. 네트워크 또는 공급사 응답을 확인하세요.')
        finally:
            reply.deleteLater()
