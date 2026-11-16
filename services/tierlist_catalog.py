import json
from functools import lru_cache
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent.parent / 'web' / 'content' / 'tierlist_characters.json'
TIER_CODES = ('S', 'A', 'B', 'C', 'D', 'UNRANKED')
RANKED_TIER_CODES = TIER_CODES[:-1]


@lru_cache(maxsize=1)
def _characters():
    with CATALOG_PATH.open(encoding='utf-8') as file:
        return tuple(json.load(file))


def list_tierlist_characters(game_codes=()):
    allowed = set(game_codes)
    return [
        character for character in _characters()
        if not allowed or character['game'] in allowed
    ]


def get_tierlist_character(character_id):
    return next((character for character in _characters() if character['id'] == character_id), None)


def get_tierlist_filter_options(game_codes=()):
    characters = list_tierlist_characters(game_codes)
    options = {
        key: sorted(
            {character[key]['id']: character[key] for character in characters}.values(),
            key=lambda value: value['name'].casefold(),
        )
        for key in ('region', 'element', 'gender')
    }
    options['affiliation'] = sorted(
        {
            affiliation['id']: affiliation
            for character in characters
            for affiliation in character.get('affiliations', [])
        }.values(),
        key=lambda value: value['name'].casefold(),
    )
    return options


def tierlist_game_codes():
    return sorted({character['game'] for character in _characters()})
