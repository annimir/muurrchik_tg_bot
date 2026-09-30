import re


def slugify_game_name(name: str) -> str:
    """Генерирует code из имени игры: 'Wuthering Waves' -> 'wuthering_waves'."""
    slug = name.strip().lower()
    slug = re.sub(r'[^a-z0-9]+', '_', slug).strip('_')
    return slug or 'game'