import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stocks import provider_symbol, parse_chart_response, position_values


class StockTests(unittest.TestCase):
    def test_symbols_are_mapped_and_validated(self):
        self.assertEqual(provider_symbol('005930', 'KRX'), '005930.KS')
        self.assertEqual(provider_symbol('247540', 'KOSDAQ'), '247540.KQ')
        self.assertEqual(provider_symbol('nvda', 'US'), 'NVDA')
        with self.assertRaises(ValueError):
            provider_symbol('../secret', 'US')
        with self.assertRaises(ValueError):
            provider_symbol('5930', 'KRX')

    def test_quote_parse_and_portfolio_math(self):
        data = {'chart': {'result': [{'meta': {
            'symbol': 'NVDA', 'regularMarketPrice': 125.0,
            'chartPreviousClose': 100.0, 'currency': 'USD',
            'regularMarketTime': 1234567890}}]}}
        quote = parse_chart_response(data)
        self.assertEqual(quote['percent'], 25.0)
        value, profit, percent = position_values(
            {'quantity': 2, 'average': 80}, quote)
        self.assertEqual((value, profit, percent), (250.0, 90.0, 56.25))

    def test_invalid_quote_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_chart_response({'chart': {'result': []}})


if __name__ == '__main__':
    unittest.main()
