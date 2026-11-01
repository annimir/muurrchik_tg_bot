import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from config.config import config

SESSION_COOKIE = 'paimon_admin_session'


def _serializer():
    if not config.web_secret_key:
        raise RuntimeError('Для админки нужно задать web.secret_key')
    return URLSafeTimedSerializer(config.web_secret_key, salt='paimon-admin')


def create_admin_session(tg_id):
    csrf_token = secrets.token_urlsafe(32)
    token = _serializer().dumps({'tg_id': tg_id, 'csrf': csrf_token})
    return token, csrf_token


def read_admin_session(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=config.web_session_ttl_seconds)
    except BadSignature:
        return None
    if not isinstance(data, dict) or not data.get('tg_id') or not data.get('csrf'):
        return None
    return data


def require_admin(request: Request):
    from database.queries import get_all_admin_ids

    session = read_admin_session(request)
    if not session or session['tg_id'] not in get_all_admin_ids():
        raise HTTPException(status_code=303, headers={'Location': '/admin/login'})
    request.state.admin_session = session
    return session


async def csrf_protect(request: Request):
    session = read_admin_session(request)
    form = await request.form()
    token = form.get('csrf_token', '')
    if not session or not hmac.compare_digest(str(token), session['csrf']):
        raise HTTPException(status_code=403, detail='Недействительный CSRF-токен')


def verify_telegram_login(data, bot_token, now=None):
    fields = {key: value for key, value in data.items() if key != 'hash'}
    received_hash = data.get('hash', '')
    try:
        auth_date = int(fields.get('auth_date', ''))
        int(fields['id'])
    except (KeyError, TypeError, ValueError):
        return False
    current_time = int(time.time()) if now is None else now
    if not 0 <= current_time - auth_date <= 600:
        return False
    check_string = '\n'.join(f'{key}={fields[key]}' for key in sorted(fields))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    expected_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_hash, received_hash)
