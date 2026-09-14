"""Read-only market quotes and local portfolio calculations.

The default quote source is Yahoo Finance's public chart endpoint. It is an
unofficial integration: prices may be delayed, rate-limited, or unavailable.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote as url_quote

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest


def provider_symbol(symbol, market):
    raw = str(symbol).strip().upper()
    if not raw or len(raw) > 30 or not re.fullmatch(r'[A-Z0-9.^=-]+', raw):
        raise ValueError('종목 코드는 영문·숫자로 입력해 주세요.')
    if market in ('KRX', 'KOSDAQ'):
        if not re.fullmatch(r'\d{6}', raw):
            raise ValueError('국내 종목 코드는 6자리 숫자예요.')
        return raw + ('.KS' if market == 'KRX' else '.KQ')
    if market != 'US':
        raise ValueError('지원하지 않는 시장이에요.')
    return raw


def parse_chart_response(data, fallback_symbol=''):
    try:
        result = data['chart']['result'][0]
        meta = result['meta']
        price = meta.get('regularMarketPrice')
        if price is None:
            closes = result.get('indicators', {}).get('quote', [{}])[0].get('close', [])
            price = next((value for value in reversed(closes) if value is not None), None)
        previous = meta.get('chartPreviousClose', meta.get('previousClose'))
        timestamp = meta.get('regularMarketTime') or (result.get('timestamp') or [None])[-1]
        price = float(price)
        previous = float(previous) if previous not in (None, 0, '0') else None
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError('시세 응답을 읽지 못했어요.')
    change = price - previous if previous else None
    percent = change / previous * 100 if previous else None
    return dict(symbol=str(meta.get('symbol') or fallback_symbol),
                name=str(meta.get('longName') or meta.get('shortName') or ''),
                price=price, previous=previous, change=change, percent=percent,
                currency=str(meta.get('currency') or ''), timestamp=timestamp,
                exchange=str(meta.get('exchangeName') or meta.get('fullExchangeName') or ''))


def position_values(position, market_quote):
    quantity = float(position['quantity'])
    average = float(position['average'])
    value = market_quote['price'] * quantity
    cost = average * quantity
    profit = value - cost
    percent = profit / cost * 100 if cost else None
    return value, profit, percent


class MarketClient(QObject):
    quoteLoaded = Signal(int, dict)
    failed = Signal(int, str)
    completed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = QNetworkAccessManager(self)
        self.replies = {}
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.cancel)

    def fetch(self, positions):
        self.cancel(emit=False)
        if not positions:
            self.completed.emit()
            return
        for index, item in enumerate(positions):
            if item.get('cash'):
                self.quoteLoaded.emit(index, dict(price=1, percent=None, currency='USD' if item['market'] == 'US' else 'KRW'))
                continue
            try:
                symbol = provider_symbol(item['symbol'], item['market'])
            except ValueError as exc:
                self.failed.emit(index, str(exc))
                continue
            url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + url_quote(symbol, safe='') + '?interval=1m&range=1d'
            request = QNetworkRequest(QUrl(url))
            request.setRawHeader(b'User-Agent', b'IzunaDesktop/0.4')
            request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.ManualRedirectPolicy)
            reply = self.manager.get(request)
            self.replies[reply] = (index, symbol)
            reply.finished.connect(lambda r=reply: self._finish(r))
        if self.replies:
            self.timer.start(15000)
        else:
            self.completed.emit()

    def cancel(self, emit=True):
        self.timer.stop()
        replies, self.replies = self.replies, {}
        for reply, (index, _) in replies.items():
            reply.abort()
            if emit:
                self.failed.emit(index, '시세 요청 시간이 초과됐어요.')
        if emit and replies:
            self.completed.emit()

    def _finish(self, reply):
        item = self.replies.pop(reply, None)
        if item is None:
            reply.deleteLater()
            return
        index, symbol = item
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        raw = bytes(reply.readAll())
        reply.deleteLater()
        if status != 200:
            self.failed.emit(index, '시세를 받지 못했어요.' if status else '시세 서버에 연결하지 못했어요.')
        else:
            try:
                self.quoteLoaded.emit(index, parse_chart_response(json.loads(raw), symbol))
            except (ValueError, json.JSONDecodeError):
                self.failed.emit(index, '시세 응답을 읽지 못했어요.')
        if not self.replies:
            self.timer.stop()
            self.completed.emit()
