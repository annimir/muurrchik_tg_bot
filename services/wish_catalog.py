import json
from functools import lru_cache
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent.parent / 'web' / 'content' / 'wish_items.json'


@lru_cache(maxsize=1)
def _items():
    with CATALOG_PATH.open(encoding='utf-8') as file:
        return {item['name']: item for item in json.load(file)}


def get_item_localization(name):
    return _items().get(name, {})
