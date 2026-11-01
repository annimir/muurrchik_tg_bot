import hashlib
import hmac
import sys
import types
import unittest
from unittest.mock import patch

from fastapi import Request

from web.charts import build_daily_bars, build_line_chart

config_module = types.ModuleType('config.config')
config_module.config = types.SimpleNamespace(
    web_secret_key='test-secret-key', web_session_ttl_seconds=28800,
)
with patch.dict(sys.modules, {'config.config': config_module}):
    from web.auth import SESSION_COOKIE, create_admin_session, read_admin_session, verify_telegram_login


class TelegramLoginTests(unittest.TestCase):
    def test_verifies_signature_and_rejects_tampering(self):
        bot_token = '123456:test-token'
        now = 1_800_000_000
        fields = {'id': '100', 'first_name': 'Admin', 'auth_date': str(now - 30)}
        check_string = '\n'.join(f'{key}={fields[key]}' for key in sorted(fields))
        secret = hashlib.sha256(bot_token.encode()).digest()
        fields['hash'] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()

        self.assertTrue(verify_telegram_login(fields, bot_token, now=now))
        self.assertFalse(verify_telegram_login({**fields, 'id': '200'}, bot_token, now=now))
        self.assertFalse(verify_telegram_login(fields, bot_token, now=now + 601))

    def test_signed_session_roundtrip(self):
        token, csrf = create_admin_session(100)
        request = Request({
            'type': 'http',
            'headers': [(b'cookie', f'{SESSION_COOKIE}={token}'.encode())],
        })

        session = read_admin_session(request)

        self.assertEqual(session['tg_id'], 100)
        self.assertEqual(session['csrf'], csrf)


class ChartTests(unittest.TestCase):
    def test_chart_contains_all_series_and_daily_values(self):
        rows = [
            {'day': __import__('datetime').date(2026, 1, 1), 'total': 2, 'photo': 1, 'video': 1, 'video_link': 0},
            {'day': __import__('datetime').date(2026, 1, 2), 'total': 4, 'photo': 2, 'video': 1, 'video_link': 1},
        ]

        chart = build_line_chart(rows)
        bars = build_daily_bars(rows[-1])

        self.assertEqual(len(chart['series']), 4)
        self.assertEqual(chart['maximum'], 4)
        self.assertEqual([bar['value'] for bar in bars], [4, 2, 1, 1])
        self.assertEqual(bars[0]['percent'], 100)
