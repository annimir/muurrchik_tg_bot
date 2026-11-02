import json
from datetime import date
from functools import lru_cache
from pathlib import Path

LORE_PATH = Path(__file__).resolve().parent / 'content' / 'lore.json'
CHAT_ID = 1825070005


@lru_cache(maxsize=1)
def _load_lore():
    with LORE_PATH.open(encoding='utf-8') as file:
        data = json.load(file)
    entries = []
    for item in data['entries']:
        entries.append({
            **item,
            'date': date.fromisoformat(item['date']),
            'source_url': f'https://t.me/c/{CHAT_ID}/{item["source"]}',
        })
    return data['games'], entries


def get_lore(game=''):
    games, entries = _load_lore()
    if game and game not in games:
        return None
    game_cards = [
        {
            **metadata,
            'key': key,
            'entry_count': sum(entry['game'] == key for entry in entries),
        }
        for key, metadata in games.items()
    ]
    selected_entries = [entry for entry in entries if not game or entry['game'] == game]
    return {
        'games': game_cards,
        'game_names': {key: metadata['name'] for key, metadata in games.items()},
        'selected_game': game,
        'selected_game_name': games[game]['name'] if game else 'Все игры',
        'entries': sorted(selected_entries, key=lambda entry: (entry['date'], entry['source'])),
    }
