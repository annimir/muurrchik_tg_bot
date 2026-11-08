from datetime import datetime
from zoneinfo import ZoneInfo

from database.queries import db

MOSCOW_TZ = ZoneInfo('Europe/Moscow')


def list_wish_reward_rules():
    return db('SELECT * FROM wish_reward_rules ORDER BY sort_order, code').all()


def update_wish_reward_rule(
    admin_tg_id, code, reward, threshold, daily_limit=None, monthly_limit=None, is_active=True,
):
    if reward < 1 or reward > 1000:
        raise ValueError('Награда должна быть от 1 до 1000 молитв')
    if threshold < 1 or threshold > 100:
        raise ValueError('Порог должен быть от 1 до 100')
    if daily_limit is not None and daily_limit < 1:
        raise ValueError('Дневной лимит должен быть положительным')
    if monthly_limit is not None and monthly_limit < 1:
        raise ValueError('Месячный лимит должен быть положительным')
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
        tx(
            '''
            INSERT INTO admin_audit_log (admin_tg_id, action, entity_type, entity_id, details)
            VALUES (%s, 'update', 'wish_reward_rule', %s, %s::jsonb)
            ''',
            (
                admin_tg_id, code,
                f'{{"reward": {reward}, "threshold": {threshold}, "is_active": {str(is_active).lower()}}}',
            ),
        ).close()


def record_wish_activity_tx(tx, event_id, user_id, rule_code, source_type, source_id, now=None):
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

    progress = tx(
        '''
        SELECT COUNT(*) AS count FROM wish_reward_activities
        WHERE event_id = %s AND user_id = %s AND rule_code = %s AND activity_date = %s
        ''',
        (event_id, user_id, rule_code, activity_date),
    ).one()['count']
    if progress < rule['threshold']:
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
        'UPDATE wish_reward_activities SET amount = %s WHERE id = %s',
        (rule['reward'], activity['id']),
    ).close()
    tx(
        '''
        UPDATE wish_participants
        SET remaining = remaining + %s, bonus_earned = bonus_earned + %s, updated_at = now()
        WHERE event_id = %s AND user_id = %s
        ''',
        (rule['reward'], rule['reward'], event_id, user_id),
    ).close()
    return {
        'rule_code': rule_code, 'title': rule['title'], 'amount': rule['reward'],
        'activity_id': activity['id'],
    }


def record_wish_activity(rule_code, user_id, source_type, source_id, event_id=None, now=None):
    if event_id is None:
        from database.wishes import get_or_create_current_wish_event

        event_id = get_or_create_current_wish_event()['id']
    with db.transaction() as tx:
        return record_wish_activity_tx(
            tx, event_id, user_id, rule_code, source_type, source_id, now,
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
        SELECT rule_code, activity_date, amount FROM wish_reward_activities
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
        progress = len(period_activities)
        period_awards = sum(row['amount'] > 0 for row in period_activities)
        monthly_awards = sum(row['amount'] > 0 for row in rule_activities)
        daily_reached = (
            rule['daily_limit'] is not None and period_awards >= rule['daily_limit']
        )
        monthly_reached = (
            rule['monthly_limit'] is not None and monthly_awards >= rule['monthly_limit']
        )
        result.append({
            **rule,
            'progress': min(progress, rule['threshold']),
            'completed': daily_reached or monthly_reached,
            'monthly_reached': monthly_reached and not daily_reached,
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
        SELECT wra.amount, wra.created_at, wra.rule_code, wrr.title, u.tag, u.id AS user_id
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
