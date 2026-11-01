from pathlib import Path

from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE_DIR / 'templates')


def datetime_ru(value):
    return value.strftime('%d.%m.%Y %H:%M') if value else ''


def date_ru(value):
    return value.strftime('%d.%m.%Y') if value else ''


def media_kind(value):
    return {'photo': 'Фото', 'video': 'Видео', 'video_link': 'Ссылка'}.get(value, value)


templates.env.filters['datetime_ru'] = datetime_ru
templates.env.filters['date_ru'] = date_ru
templates.env.filters['media_kind'] = media_kind
