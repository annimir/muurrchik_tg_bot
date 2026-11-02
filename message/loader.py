import configparser
from functools import lru_cache

DEFAULT_LANGUAGE = "RU"

LANGUAGE_PATHS = {
    "RU": "message/translations/messages_ru.properties",
    "EN": "message/translations/messages_en.properties",
}


@lru_cache(maxsize=None)
def _load_parser(language: str) -> configparser.ConfigParser:
    """Отдельный парсер на каждый язык, закэшированный после первого чтения."""
    if language not in LANGUAGE_PATHS:
        language = DEFAULT_LANGUAGE

    parser = configparser.ConfigParser(allow_no_value=True, delimiters=('=',), interpolation=None)
    parser.read(LANGUAGE_PATHS[language], encoding='utf-8')
    return parser


def message(language: str, key: str, section: str, *args) -> str:
    """
    language: 'RU' / 'EN'
    key: ключ внутри секции, например 'start.message'
    section: секция в .properties, например 'welcome'
    """
    parser = _load_parser(language)

    try:
        raw = parser[section][key]
    except KeyError:
        # fallback на язык по умолчанию, если в текущем не хватает перевода
        if language != DEFAULT_LANGUAGE:
            fallback_parser = _load_parser(DEFAULT_LANGUAGE)
            raw = fallback_parser[section][key]
        else:
            raise

    return str(raw).format(*args) if args else str(raw)


def reload_translations():
    """Сбросить кэш — вызывать, если .properties изменили на лету без рестарта бота."""
    _load_parser.cache_clear()