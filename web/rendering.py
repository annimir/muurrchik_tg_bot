import re
from pathlib import Path
from urllib.parse import urlencode

from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE_DIR / 'templates')


def datetime_ru(value):
    return value.strftime('%d.%m.%Y %H:%M') if value else ''


def date_ru(value):
    return value.strftime('%d.%m.%Y') if value else ''


def media_kind(value):
    return {'photo': 'Фото', 'video': 'Видео', 'video_link': 'Ссылка'}.get(value, value)


def media_caption(value):
    if not value:
        return value
    caption = re.sub(r'(?<!\S)#\w+(?:-\w+)*', '', value)
    lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in caption.splitlines()]
    return '\n'.join(line for line in lines if line)


def media_url(tag_ids=(), kind='', sort='newest', date_from='', date_to='', page=None):
    kind_values = [kind] if isinstance(kind, str) else kind
    sort_values = [sort] if isinstance(sort, str) else sort
    params = [('tag', tag_id) for tag_id in tag_ids]
    params.extend(('kind', value) for value in kind_values if value)
    params.extend(('sort', value) for value in sort_values if value)
    params.extend(
        (key, value) for key, value in (('date_from', date_from), ('date_to', date_to)) if value
    )
    if page is not None:
        params.append(('page', page))
    return f'/media?{urlencode(params)}'


def number_ru(value):
    return f'{value:,}'.replace(',', ' ')


def status_ru(value):
    return {'ACTIVE': 'Активен', 'DELETED': 'Удалён', 'BLOCKED': 'Заблокирован'}.get(value, value)


templates.env.filters['datetime_ru'] = datetime_ru
templates.env.filters['date_ru'] = date_ru
templates.env.filters['media_kind'] = media_kind
templates.env.filters['media_caption'] = media_caption
templates.env.filters['number_ru'] = number_ru
templates.env.filters['status_ru'] = status_ru
templates.env.globals['media_url'] = media_url
