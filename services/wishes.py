import random

INITIAL_WISH_STATE = {
    'pity5': 0,
    'pity4': 0,
    'featured5_guaranteed': False,
    'featured4_guaranteed': False,
    'radiance_streak': 0,
}


def _choose(items, rarity, featured, rng):
    pool = [item for item in items if item['rarity'] == rarity and item['featured'] == featured]
    if not pool:
        raise ValueError(f'В баннере нет предметов {rarity}★ с featured={featured}')
    return pool[min(int(rng() * len(pool)), len(pool) - 1)]


def _five_star_probability(pity):
    if pity >= 90:
        return 1.0
    if pity < 74:
        return 0.006
    return min(1.0, 0.006 + (pity - 73) * 0.06)


def _roll_five_star(state, rng):
    if state['featured5_guaranteed']:
        state['featured5_guaranteed'] = False
        return True, False
    if state['radiance_streak'] >= 3:
        state['radiance_streak'] = 0
        return True, True
    if rng() < 0.5:
        state['radiance_streak'] = 0
        return True, False
    if rng() < 0.00018:
        state['radiance_streak'] = 0
        return True, True
    state['featured5_guaranteed'] = True
    state['radiance_streak'] += 1
    return False, False


def perform_ten_wishes(items, current_state=None, rng=None):
    if len(items) < 1:
        raise ValueError('Баннер пуст')
    state = dict(INITIAL_WISH_STATE | (current_state or {}))
    rng = rng or random.SystemRandom().random
    drops = []
    for _ in range(10):
        state['pity5'] += 1
        state['pity4'] += 1
        pity5_at = state['pity5']
        pity4_at = state['pity4']
        is_five_star = rng() < _five_star_probability(state['pity5'])
        is_radiant = False
        if is_five_star:
            featured, is_radiant = _roll_five_star(state, rng)
            item = _choose(items, 5, featured, rng)
            state['pity5'] = 0
            state['pity4'] = 0
        elif state['pity4'] >= 10 or rng() < 0.051:
            if state['featured4_guaranteed']:
                featured = True
                state['featured4_guaranteed'] = False
            else:
                featured = rng() < 0.5
                state['featured4_guaranteed'] = not featured
            item = _choose(items, 4, featured, rng)
            state['pity4'] = 0
        else:
            featured = False
            item = _choose(items, 3, False, rng)
        drops.append({
            'name': item['name'],
            'rarity': item['rarity'],
            'item_type': item['item_type'],
            'image_url': item.get('image_url'),
            'featured': featured,
            'radiant': is_radiant,
            'pity5_at': pity5_at,
            'pity4_at': pity4_at,
        })
    return state, drops
