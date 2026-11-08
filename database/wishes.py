import random
from datetime import datetime
from zoneinfo import ZoneInfo

from database.queries import db
from services.wishes import perform_ten_wishes

MOSCOW_TZ = ZoneInfo('Europe/Moscow')
DEFAULT_ALLOWANCE = 300

FEATURED_FOUR_STARS = ('Valeriy', 'Charlotte', 'Rosaria')
STANDARD_FIVE_STARS = (
    'Diluc', 'Jean', 'Mona', 'Qiqi', 'Keqing', 'Tighnari', 'Dehya', 'Mizuki',
)
STANDARD_FOUR_CHARACTERS = (
    'Amber', 'Kaeya', 'Lisa', 'Barbara', 'Razor', 'Xiangling', 'Beidou', 'Xingqiu',
    'Ningguang', 'Fischl', 'Bennett', 'Noelle', 'Chongyun', 'Sucrose', 'Diona',
    'Xinyan', 'Kujou Sara', 'Sayu', 'Thoma', 'Gorou', 'Kuki Shinobu',
    'Shikanoin Heizou', 'Collei', 'Dori', 'Candace', 'Layla', 'Faruzan', 'Kaveh',
    'Kirara', 'Lynette', 'Freminet', 'Chevreuse', 'Gaming', 'Sethos', 'Kachina',
    'Ororon', 'Iansan', 'Ifa', 'Dahlia', 'Aino', 'Jahoda', 'Illuga',
)
STANDARD_FOUR_WEAPONS = (
    'Favonius Sword', 'Favonius Greatsword', 'Favonius Lance', 'Favonius Codex',
    'Favonius Warbow', 'Sacrificial Sword', 'Sacrificial Greatsword', 'Sacrificial Fragments',
    'Sacrificial Bow', 'The Stringless', 'The Bell', 'The Flute', 'Lion’s Roar',
    'Rainslasher', 'Dragon’s Bane', 'Eye of Perception', 'Rust',
)
STANDARD_THREE_WEAPONS = (
    'Cool Steel', 'Debate Club', 'Black Tassel', 'White Tassel', 'Harbinger of Dawn',
    'Ferrous Shadow', 'Skyrider Sword', 'Skyrider Greatsword',
    'Slingshot', 'Sharpshooter’s Oath', 'Raven Bow', 'Emerald Orb', 'Thrilling Tales of Dragon Slayers',
    'Magic Guide', 'Otherworldly Story', 'Dark Iron Sword', 'Bloodtainted Greatsword',
    'White Iron Greatsword', 'Halberd',
)


def _audit(tx, admin_tg_id, action, entity_type, entity_id):
    tx(
        '''
        INSERT INTO admin_audit_log (admin_tg_id, action, entity_type, entity_id)
        VALUES (%s, %s, %s, %s)
        ''',
        (admin_tg_id, action, entity_type, str(entity_id)),
    ).close()


def _add_item(tx, banner_id, name, rarity, item_type, featured=False):
    tx(
        '''
        INSERT INTO wish_items (banner_id, name, rarity, item_type, featured)
        VALUES (%s, %s, %s, %s, %s) ON CONFLICT (banner_id, name) DO NOTHING
        ''',
        (banner_id, name, rarity, item_type, featured),
    ).close()


def _add_default_banner(tx, event_id, name, featured_five):
    banner = tx(
        'INSERT INTO wish_banners (event_id, name) VALUES (%s, %s) RETURNING id',
        (event_id, name),
    ).one()
    banner_id = banner['id']
    _add_item(tx, banner_id, featured_five, 5, 'character', True)
    for name in STANDARD_FIVE_STARS:
        _add_item(tx, banner_id, name, 5, 'character')
    for name in FEATURED_FOUR_STARS:
        _add_item(tx, banner_id, name, 4, 'character', True)
    for name in STANDARD_FOUR_CHARACTERS:
        _add_item(tx, banner_id, name, 4, 'character')
    for name in STANDARD_FOUR_WEAPONS:
        _add_item(tx, banner_id, name, 4, 'weapon')
    for name in STANDARD_THREE_WEAPONS:
        _add_item(tx, banner_id, name, 3, 'weapon')


def _copy_content(tx, source_event_id, target_event_id):
    banners = tx('SELECT * FROM wish_banners WHERE event_id = %s ORDER BY sort_order, id', (source_event_id,)).all()
    for banner in banners:
        copied = tx(
            '''
            INSERT INTO wish_banners (event_id, name, is_active, sort_order)
            VALUES (%s, %s, %s, %s) RETURNING id
            ''',
            (target_event_id, banner['name'], banner['is_active'], banner['sort_order']),
        ).one()
        tx(
            '''
            INSERT INTO wish_items (
                banner_id, name, rarity, item_type, featured, image_url, sort_order
            )
            SELECT %s, name, rarity, item_type, featured, image_url, sort_order
            FROM wish_items WHERE banner_id = %s
            ''',
            (copied['id'], banner['id']),
        ).close()


def _create_event(tx, period, allowance, admin_tg_id, source=None):
    if source:
        tx("UPDATE wish_events SET status = 'ARCHIVED' WHERE id = %s", (source['id'],)).close()
    row = tx(
        '''
        INSERT INTO wish_events (period, pull_allowance, reset_from_id, created_by)
        VALUES (%s, %s, %s, %s) RETURNING *
        ''',
        (period, allowance, source['id'] if source else None, admin_tg_id),
    ).one()
    if source:
        _copy_content(tx, source['id'], row['id'])
    else:
        _add_default_banner(tx, row['id'], 'Myriad Patterns Unfold', 'Mitya')
        _add_default_banner(tx, row['id'], 'Chanson of Many Waters', 'Furina')
    if admin_tg_id:
        _audit(tx, admin_tg_id, 'create', 'wish_event', row['id'])
    return row


def get_or_create_current_wish_event():
    period = datetime.now(MOSCOW_TZ).strftime('%Y-%m')
    with db.transaction() as tx:
        tx('SELECT pg_advisory_xact_lock(761203)').close()
        active = tx("SELECT * FROM wish_events WHERE status = 'ACTIVE'").one()
        if active and active['period'] == period:
            return active
        source = active or tx('SELECT * FROM wish_events ORDER BY created_at DESC LIMIT 1').one()
        return _create_event(
            tx, period, source['pull_allowance'] if source else DEFAULT_ALLOWANCE, None, source,
        )


def get_wish_event(event_id):
    return db('SELECT * FROM wish_events WHERE id = %s', (event_id,)).one()


def list_wish_events():
    return db('SELECT * FROM wish_events ORDER BY created_at DESC').all()


def list_wish_banners(event_id, active_only=False):
    where = 'event_id = %s'
    if active_only:
        where += ' AND is_active = TRUE'
    return db(
        f'SELECT * FROM wish_banners WHERE {where} ORDER BY sort_order, id',
        (event_id,),
    ).all()


def get_wish_banner(banner_id):
    return db('SELECT * FROM wish_banners WHERE id = %s', (banner_id,)).one()


def list_wish_items(banner_id):
    return db(
        'SELECT * FROM wish_items WHERE banner_id = %s ORDER BY rarity DESC, featured DESC, sort_order, id',
        (banner_id,),
    ).all()


def get_participant(event_id, user_id):
    return db(
        '''
        SELECT wp.*, we.pull_allowance,
            we.pull_allowance - wp.remaining AS used
        FROM wish_participants wp
        JOIN wish_events we ON we.id = wp.event_id
        WHERE wp.event_id = %s AND wp.user_id = %s
        ''',
        (event_id, user_id),
    ).one()


def perform_wishes(event_id, user_id, banner_id):
    with db.transaction() as tx:
        event = tx("SELECT * FROM wish_events WHERE id = %s AND status = 'ACTIVE' FOR UPDATE", (event_id,)).one()
        if not event:
            raise ValueError('Ивент неактивен')
        if not tx('SELECT 1 FROM users WHERE id = %s AND left_at IS NULL', (user_id,)).one():
            raise ValueError('Игрок не найден')
        if not tx(
            'SELECT 1 FROM wish_banners WHERE id = %s AND event_id = %s AND is_active = TRUE',
            (banner_id, event_id),
        ).one():
            raise ValueError('Баннер не найден')
        tx(
            '''
            INSERT INTO wish_participants (event_id, user_id, remaining)
            VALUES (%s, %s, %s) ON CONFLICT (event_id, user_id) DO NOTHING
            ''',
            (event_id, user_id, event['pull_allowance']),
        ).close()
        participant = tx(
            '''
            SELECT * FROM wish_participants
            WHERE event_id = %s AND user_id = %s FOR UPDATE
            ''',
            (event_id, user_id),
        ).one()
        if participant['remaining'] < 10:
            raise ValueError('Недостаточно молитв: для выполнения нужно 10')
        items = tx('SELECT * FROM wish_items WHERE banner_id = %s ORDER BY id', (banner_id,)).all()
        state, drops = perform_ten_wishes(items, participant)
        tx(
            '''
            UPDATE wish_participants SET remaining = remaining - 10,
                pity5 = %s, pity4 = %s, featured5_guaranteed = %s,
                featured4_guaranteed = %s, radiance_streak = %s, updated_at = now()
            WHERE event_id = %s AND user_id = %s
            ''',
            (
                state['pity5'], state['pity4'], state['featured5_guaranteed'],
                state['featured4_guaranteed'], state['radiance_streak'], event_id, user_id,
            ),
        ).close()
        used = event['pull_allowance'] - participant['remaining']
        for index, drop in enumerate(drops, start=1):
            tx(
                '''
                INSERT INTO wish_drops (
                    event_id, user_id, banner_id, item_name, rarity, item_type,
                    featured, radiant, pull_number, pity5_at, pity4_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''',
                (
                    event_id, user_id, banner_id, drop['name'], drop['rarity'], drop['item_type'],
                    drop['featured'], drop['radiant'], used + index, drop['pity5_at'], drop['pity4_at'],
                ),
            ).close()
        return {'drops': drops, 'state': state, 'remaining': participant['remaining'] - 10}


def get_recent_drops(event_id, user_id, limit=10):
    return db(
        '''
        SELECT * FROM wish_drops WHERE event_id = %s AND user_id = %s
        ORDER BY id DESC LIMIT %s
        ''',
        (event_id, user_id, limit),
    ).all()


def get_wish_participant_stats(event_id):
    return db(
        '''
        SELECT u.id, u.tag, wp.remaining, we.pull_allowance,
            we.pull_allowance - wp.remaining AS used,
            wp.pity5, wp.pity4, wp.featured5_guaranteed, wp.featured4_guaranteed,
            COUNT(wd.id) FILTER (WHERE wd.rarity = 5) AS five_star_count,
            COUNT(wd.id) FILTER (WHERE wd.rarity = 4) AS four_star_count,
            COUNT(wd.id) FILTER (WHERE wd.rarity = 3) AS three_star_count,
            COUNT(wd.id) FILTER (WHERE wd.rarity = 5 AND wd.featured) AS featured_five_count,
            AVG(wd.pity5_at) FILTER (WHERE wd.rarity = 5) AS average_five_pity
        FROM wish_participants wp
        JOIN users u ON u.id = wp.user_id
        JOIN wish_events we ON we.id = wp.event_id
        LEFT JOIN wish_drops wd ON wd.event_id = wp.event_id AND wd.user_id = wp.user_id
        WHERE wp.event_id = %s
        GROUP BY u.id, u.tag, wp.remaining, we.pull_allowance, wp.pity5, wp.pity4,
            wp.featured5_guaranteed, wp.featured4_guaranteed
        ORDER BY u.tag NULLS LAST, u.id
        ''',
        (event_id,),
    ).all()


def list_wish_winners(event_id):
    return db(
        '''
        SELECT ww.kind, u.id AS user_id, u.tag
        FROM wish_winners ww JOIN users u ON u.id = ww.user_id
        WHERE ww.event_id = %s ORDER BY ww.kind
        ''',
        (event_id,),
    ).all()


def calculate_wish_winners(event_id):
    existing = list_wish_winners(event_id)
    if existing:
        return existing
    stats = [row for row in get_wish_participant_stats(event_id) if row['remaining'] == 0]
    if not stats:
        return []
    winners = []
    for kind in ('LUCKIEST', 'UNLUCKIEST'):
        if kind == 'LUCKIEST':
            best_count = max(row['five_star_count'] for row in stats)
            candidates = [row for row in stats if row['five_star_count'] == best_count]
            best_average = (
                None if best_count == 0
                else min(row['average_five_pity'] for row in candidates)
            )
        else:
            best_count = min(row['five_star_count'] for row in stats)
            candidates = [row for row in stats if row['five_star_count'] == best_count]
            if best_count == 0:
                best_average = None
            else:
                best_average = max(row['average_five_pity'] for row in candidates)
        if best_average is not None:
            candidates = [row for row in candidates if row['average_five_pity'] == best_average]
        winners.append((kind, random.SystemRandom().choice(candidates)))
    with db.transaction() as tx:
        for kind, row in winners:
            tx(
                'INSERT INTO wish_winners (event_id, user_id, kind) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING',
                (event_id, row['id'], kind),
            ).close()
    return list_wish_winners(event_id)


def set_wish_allowance(admin_tg_id, event_id, allowance):
    with db.transaction() as tx:
        event = tx('SELECT * FROM wish_events WHERE id = %s FOR UPDATE', (event_id,)).one()
        if not event:
            raise ValueError('Ивент не найден')
        difference = allowance - event['pull_allowance']
        tx(
            '''
            UPDATE wish_participants SET remaining = remaining + %s, updated_at = now()
            WHERE event_id = %s
            ''',
            (difference, event_id),
        ).close()
        if tx('SELECT 1 FROM wish_participants WHERE event_id = %s AND remaining < 0', (event_id,)).one():
            raise ValueError('Новый лимит меньше уже использованных молитв')
        tx(
            'UPDATE wish_events SET pull_allowance = %s WHERE id = %s',
            (allowance, event_id),
        ).close()
        _audit(tx, admin_tg_id, 'update', 'wish_event', event_id)


def restart_wish_event(admin_tg_id, event_id):
    with db.transaction() as tx:
        source = tx("SELECT * FROM wish_events WHERE id = %s AND status = 'ACTIVE' FOR UPDATE", (event_id,)).one()
        if not source:
            raise ValueError('Активный ивент не найден')
        return _create_event(
            tx, source['period'], source['pull_allowance'], admin_tg_id, source,
        )


def create_wish_banner(admin_tg_id, event_id, name):
    with db.transaction() as tx:
        row = tx(
            'INSERT INTO wish_banners (event_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING id',
            (event_id, name),
        ).one()
        if not row:
            raise ValueError('Баннер с таким названием уже существует')
        _audit(tx, admin_tg_id, 'create', 'wish_banner', row['id'])
        return row['id']


def set_wish_banner_active(admin_tg_id, banner_id, active):
    with db.transaction() as tx:
        row = tx(
            'UPDATE wish_banners SET is_active = %s WHERE id = %s RETURNING id',
            (active, banner_id),
        ).one()
        if not row:
            raise ValueError('Баннер не найден')
        _audit(tx, admin_tg_id, 'update', 'wish_banner', banner_id)


def add_wish_item(admin_tg_id, banner_id, name, rarity, item_type, featured, image_url=None):
    with db.transaction() as tx:
        row = tx(
            '''
            INSERT INTO wish_items (banner_id, name, rarity, item_type, featured, image_url)
            VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING id
            ''',
            (banner_id, name, rarity, item_type, featured, image_url),
        ).one()
        if not row:
            raise ValueError('Такой предмет уже есть в баннере')
        _audit(tx, admin_tg_id, 'create', 'wish_item', row['id'])
        return row['id']


def delete_wish_item(admin_tg_id, item_id):
    with db.transaction() as tx:
        row = tx('DELETE FROM wish_items WHERE id = %s RETURNING id', (item_id,)).one()
        if not row:
            raise ValueError('Предмет не найден')
        _audit(tx, admin_tg_id, 'delete', 'wish_item', item_id)
