import json
from datetime import datetime
from zoneinfo import ZoneInfo

from database.queries import db

MOSCOW_TZ = ZoneInfo('Europe/Moscow')


def _attach_levels(rules):
    rows = db(
        '''
        SELECT rule_code, level, threshold, reward FROM wish_reward_rule_levels
        ORDER BY rule_code, level
        ''',
    ).all()
    levels = {}
    for row in rows:
        levels.setdefault(row['rule_code'], []).append(row)
    return [{**rule, 'levels': levels[rule['code']]} for rule in rules]


def list_wish_reward_rules():
    rules = db('SELECT * FROM wish_reward_rules ORDER BY sort_order, code').all()
    return _attach_levels(rules)


def _validate_level(level):
    threshold = level['threshold']
    reward = level['reward']
    if reward < 1 or reward > 1000:
        raise ValueError('Награда должна быть от 1 до 1000 молитв')
    if threshold < 1 or threshold > 100:
        raise ValueError('Порог должен быть от 1 до 100')
    return {'level': level.get('level', 1), 'threshold': threshold, 'reward': reward}


def update_wish_reward_rule(
    admin_tg_id, code, reward, threshold, daily_limit=None, monthly_limit=None, is_active=True,
    levels=None,
):
    _validate_level({'reward': reward, 'threshold': threshold})
    if daily_limit is not None and daily_limit < 1:
        raise ValueError('Дневной лимит должен быть положительным')
    if monthly_limit is not None and monthly_limit < 1:
        raise ValueError('Месячный лимит должен быть положительным')
    normalized_levels = None
    if levels is not None:
        if len(levels) != 3 or [level['level'] for level in levels] != [1, 2, 3]:
            raise ValueError('Нужно указать порог и награду для всех трёх уровней')
        normalized_levels = [_validate_level(level) for level in levels]
        for previous, current in zip(normalized_levels, normalized_levels[1:]):
            if current['threshold'] <= previous['threshold']:
                raise ValueError('Порог каждого следующего уровня должен быть больше')
            if current['reward'] <= previous['reward']:
                raise ValueError('Награда каждого следующего уровня должна быть больше')
        reward = normalized_levels[0]['reward']
        threshold = normalized_levels[0]['threshold']

    with db.transaction() as tx:
        row = tx(
            '''
            UPDATE wish_reward_rules
            SET reward = %s, threshold = %s, daily_limit = %s,
                monthly_limit = %s, is_active = %s
            WHERE code = %s RETURNING code
            ''',
            (reward, threshold, daily_limit, monthly_limit, is_active, code),
        ).one()
        if not row:
            raise ValueError('Правило награды не найдено')
        if normalized_levels:
            for level in normalized_levels:
                tx(
                    '''
                    INSERT INTO wish_reward_rule_levels (rule_code, level, threshold, reward)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (rule_code, level) DO UPDATE SET
                        threshold = EXCLUDED.threshold, reward = EXCLUDED.reward
                    ''',
                    (code, level['level'], level['threshold'], level['reward']),
                ).close()
        tx(
            '''
            INSERT INTO admin_audit_log (admin_tg_id, action, entity_type, entity_id, details)
            VALUES (%s, 'update', 'wish_reward_rule', %s, %s::jsonb)
            ''',
            (
                admin_tg_id, code,
                json.dumps({
                    'reward': reward, 'threshold': threshold, 'is_active': is_active,
                    'levels': normalized_levels,
                }),
            ),
        ).close()


def _rule_levels_tx(tx, rule_code):
    return tx(
        '''
        SELECT level, threshold, reward FROM wish_reward_rule_levels
        WHERE rule_code = %s ORDER BY level
        ''',
        (rule_code,),
    ).all()


def record_wish_activity_tx(
    tx, event_id, user_id, rule_code, source_type, source_id, now=None, progress_value=None,
):
    now = now or datetime.now(MOSCOW_TZ)
    activity_date = now.astimezone(MOSCOW_TZ).date()
    rule = tx(
        'SELECT * FROM wish_reward_rules WHERE code = %s AND is_active = TRUE',
        (rule_code,),
    ).one()
    if not rule or not tx(
        "SELECT 1 FROM wish_events WHERE id = %s AND status = 'ACTIVE'", (event_id,),
    ).one():
        return None
    if not tx('SELECT 1 FROM users WHERE id = %s AND left_at IS NULL', (user_id,)).one():
        return None

    event = tx('SELECT pull_allowance FROM wish_events WHERE id = %s', (event_id,)).one()
    tx(
        '''
        INSERT INTO wish_participants (event_id, user_id, remaining)
        VALUES (%s, %s, %s) ON CONFLICT (event_id, user_id) DO NOTHING
        ''',
        (event_id, user_id, event['pull_allowance']),
    ).close()
    tx(
        'SELECT 1 FROM wish_participants WHERE event_id = %s AND user_id = %s FOR UPDATE',
        (event_id, user_id),
    ).close()
    activity = tx(
        '''
        INSERT INTO wish_reward_activities (
            event_id, user_id, rule_code, source_type, source_id, activity_date
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (event_id, user_id, rule_code, source_type, source_id) DO NOTHING
        RETURNING id
        ''',
        (event_id, user_id, rule_code, source_type, str(source_id), activity_date),
    ).one()
    if not activity:
        return None

    if progress_value is None:
        progress = tx(
            '''
            SELECT COUNT(*) AS count FROM wish_reward_activities
            WHERE event_id = %s AND user_id = %s AND rule_code = %s AND activity_date = %s
            ''',
            (event_id, user_id, rule_code, activity_date),
        ).one()['count']
    else:
        progress = progress_value
    current_level = tx(
        '''
        SELECT COALESCE(MAX(level), 0) AS level FROM wish_reward_activities
        WHERE event_id = %s AND user_id = %s AND rule_code = %s AND amount > 0
        ''',
        (event_id, user_id, rule_code),
    ).one()['level']
    if current_level >= 3:
        return None
    levels = _rule_levels_tx(tx, rule_code)
    if progress_value is not None:
        reached_levels = [level for level in levels if progress >= level['threshold']]
        if not reached_levels:
            return None
        reached = reached_levels[-1]
    else:
        reached = levels[current_level]
        if progress < reached['threshold']:
            return None
    daily_awards = tx(
        '''
        SELECT COUNT(*) AS count FROM wish_reward_activities
        WHERE event_id = %s AND user_id = %s AND rule_code = %s
          AND activity_date = %s AND amount > 0
        ''',
        (event_id, user_id, rule_code, activity_date),
    ).one()['count']
    if rule['daily_limit'] is not None and daily_awards >= rule['daily_limit']:
        return None
    monthly_awards = tx(
        '''
        SELECT COUNT(*) AS count FROM wish_reward_activities
        WHERE event_id = %s AND user_id = %s AND rule_code = %s AND amount > 0
        ''',
        (event_id, user_id, rule_code),
    ).one()['count']
    if rule['monthly_limit'] is not None and monthly_awards >= rule['monthly_limit']:
        return None

    tx(
        'UPDATE wish_reward_activities SET amount = %s, level = %s WHERE id = %s',
        (reached['reward'], reached['level'], activity['id']),
    ).close()
    tx(
        '''
        UPDATE wish_participants
        SET remaining = remaining + %s, bonus_earned = bonus_earned + %s, updated_at = now()
        WHERE event_id = %s AND user_id = %s
        ''',
        (reached['reward'], reached['reward'], event_id, user_id),
    ).close()
    return {
        'rule_code': rule_code, 'title': rule['title'], 'amount': reached['reward'],
        'level': reached['level'], 'activity_id': activity['id'],
    }


def record_wish_activity(
    rule_code, user_id, source_type, source_id, event_id=None, now=None, progress_value=None,
):
    if event_id is None:
        from database.wishes import get_or_create_current_wish_event

        event_id = get_or_create_current_wish_event()['id']
    with db.transaction() as tx:
        return record_wish_activity_tx(
            tx, event_id, user_id, rule_code, source_type, source_id, now, progress_value,
        )


def record_wish_activity_for_tg(rule_code, tg_id, source_type, source_id, now=None):
    from database.wishes import get_or_create_current_wish_event

    event = get_or_create_current_wish_event()
    with db.transaction() as tx:
        user = tx('SELECT id FROM users WHERE tg_id = %s AND left_at IS NULL', (tg_id,)).one()
        if not user:
            return None
        return record_wish_activity_tx(
            tx, event['id'], user['id'], rule_code, source_type, source_id, now,
        )


def record_new_tag_activity(tg_id, tag_id, now=None):
    from database.wishes import get_or_create_current_wish_event

    now = now or datetime.now(MOSCOW_TZ)
    activity_date = now.astimezone(MOSCOW_TZ).date()
    event = get_or_create_current_wish_event()
    with db.transaction() as tx:
        user = tx('SELECT id FROM users WHERE tg_id = %s AND left_at IS NULL', (tg_id,)).one()
        tag = tx(
            '''
            SELECT 1 FROM tag
            WHERE id = %s AND created_by = %s AND status = 'ACTIVE'
              AND (created_at AT TIME ZONE 'Europe/Moscow')::date = %s
            ''',
            (tag_id, tg_id, activity_date),
        ).one()
        if not user or not tag:
            return None
        return record_wish_activity_tx(
            tx, event['id'], user['id'], 'new_tag', 'tag', tag_id, now,
        )


def get_wish_reward_progress(event_id, user_id):
    today = datetime.now(MOSCOW_TZ).date()
    rules = [rule for rule in list_wish_reward_rules() if rule['is_active']]
    activities = db(
        '''
        SELECT rule_code, activity_date, amount, level FROM wish_reward_activities
        WHERE event_id = %s AND user_id = %s
        ''',
        (event_id, user_id),
    ).all()
    result = []
    for rule in rules:
        rule_activities = [row for row in activities if row['rule_code'] == rule['code']]
        period_activities = (
            rule_activities if rule['code'] == 'first_ten_five_star'
            else [row for row in rule_activities if row['activity_date'] == today]
        )
        current_level = max(
            (row['level'] for row in rule_activities if row['amount'] > 0), default=0,
        )
        target_level = min(current_level + 1, 3)
        target = rule['levels'][target_level - 1]
        period_awards = sum(row['amount'] > 0 for row in period_activities)
        monthly_awards = sum(row['amount'] > 0 for row in rule_activities)
        daily_reached = (
            rule['daily_limit'] is not None and period_awards >= rule['daily_limit']
        )
        monthly_reached = (
            rule['monthly_limit'] is not None and monthly_awards >= rule['monthly_limit']
        )
        if current_level >= 3:
            progress = target['threshold']
        elif rule['code'] == 'first_ten_five_star' and current_level:
            progress = rule['levels'][current_level - 1]['threshold']
        else:
            progress = min(len(period_activities), target['threshold'])
        result.append({
            **rule,
            'threshold': target['threshold'],
            'reward': target['reward'],
            'level': current_level,
            'target_level': target_level,
            'progress': progress,
            'completed': current_level >= 3,
            'daily_reached': daily_reached,
            'monthly_reached': monthly_reached,
            'earned': sum(row['amount'] for row in rule_activities),
        })
    return result


def list_wish_reward_grants(event_id, user_id=None, limit=20):
    where = 'wra.event_id = %s AND wra.amount > 0'
    params = [event_id]
    if user_id is not None:
        where += ' AND wra.user_id = %s'
        params.append(user_id)
    params.append(limit)
    return db(
        f'''
        SELECT wra.amount, wra.level, wra.created_at, wra.rule_code, wrr.title,
            u.tag, u.id AS user_id
        FROM wish_reward_activities wra
        JOIN wish_reward_rules wrr ON wrr.code = wra.rule_code
        JOIN users u ON u.id = wra.user_id
        WHERE {where}
        ORDER BY wra.created_at DESC, wra.id DESC LIMIT %s
        ''',
        tuple(params),
    ).all()


def get_wish_reward_summary(event_id, user_id):
    row = db(
        '''
        SELECT COALESCE(SUM(amount), 0) AS total,
            COALESCE(SUM(amount) FILTER (WHERE activity_date = %s), 0) AS today
        FROM wish_reward_activities
        WHERE event_id = %s AND user_id = %s
        ''',
        (datetime.now(MOSCOW_TZ).date(), event_id, user_id),
    ).one()
    return {'total': row['total'], 'today': row['today']}
