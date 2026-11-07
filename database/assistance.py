from database.queries import db

ACTIVE_REQUEST_STATUSES = ['OPEN', 'SCHEDULING', 'CONFIRMING', 'ASSIGNED']

REQUEST_SELECT = '''
    SELECT hr.*, gm.name AS mode_name, g.code AS game_code, g.name AS game_name,
        requester.tg_id AS requester_tg_id, requester.tag AS requester_tag,
        helper.tg_id AS helper_tg_id, helper.tag AS helper_tag
    FROM help_requests hr
    JOIN game_modes gm ON gm.id = hr.mode_id
    JOIN games g ON g.code = gm.game_code
    JOIN users requester ON requester.id = hr.requester_user_id
    LEFT JOIN users helper ON helper.id = hr.assigned_helper_id
'''


def list_assistance_games():
    return db(
        '''
        SELECT g.code, g.name
        FROM games g
        WHERE EXISTS (
            SELECT 1 FROM game_modes gm WHERE gm.game_code = g.code AND gm.is_active = TRUE
        )
        ORDER BY g.name
        '''
    ).all()


def list_game_modes(game_code, active_only=True):
    where = 'game_code = %s'
    if active_only:
        where += ' AND is_active = TRUE'
    return db(
        f'SELECT id, game_code, name, is_active FROM game_modes WHERE {where} ORDER BY name',
        (game_code,),
    ).all()


def get_game_mode(mode_id):
    return db(
        '''
        SELECT gm.id, gm.game_code, gm.name, gm.is_active, g.name AS game_name
        FROM game_modes gm JOIN games g ON g.code = gm.game_code
        WHERE gm.id = %s
        ''',
        (mode_id,),
    ).one()


def get_help_request(request_id):
    return db(f'{REQUEST_SELECT} WHERE hr.id = %s', (request_id,)).one()


def _eligible_helpers(tx, mode_id, requester_user_id):
    return tx(
        '''
        SELECT u.id, u.tg_id, u.tag
        FROM helper_modes hm
        JOIN helper_profiles hp ON hp.user_id = hm.user_id
        JOIN users u ON u.id = hm.user_id
        WHERE hm.mode_id = %s AND hm.is_active = TRUE
          AND hp.is_active = TRUE AND hp.is_paused = FALSE AND hp.dm_available = TRUE
          AND u.left_at IS NULL AND u.id <> %s
        ORDER BY u.id
        ''',
        (mode_id, requester_user_id),
    ).all()


def get_helper_profile(user_id):
    return db(
        '''
        SELECT hp.*, u.tg_id, u.tag
        FROM helper_profiles hp JOIN users u ON u.id = hp.user_id
        WHERE hp.user_id = %s
        ''',
        (user_id,),
    ).one()


def get_helper_public_summary(user_id):
    return db(
        '''
        SELECT hp.is_active, hp.is_paused,
            (SELECT COUNT(*) FROM help_requests hr
             WHERE hr.assigned_helper_id = hp.user_id AND hr.status = 'COMPLETED') AS completed_count
        FROM helper_profiles hp
        WHERE hp.user_id = %s
        ''',
        (user_id,),
    ).one()


def set_helper_dm_available(user_id, available=True):
    with db.transaction() as tx:
        if tx('SELECT 1 FROM helper_profiles WHERE user_id = %s', (user_id,)).one():
            tx(
                'UPDATE helper_profiles SET dm_available = %s, updated_at = now() WHERE user_id = %s',
                (available, user_id),
            ).close()


def list_helper_modes(user_id, active_only=False):
    where = 'hm.user_id = %s'
    if active_only:
        where += ' AND hm.is_active = TRUE AND gm.is_active = TRUE'
    return db(
        f'''
        SELECT hm.mode_id, hm.is_active, gm.name AS mode_name,
            g.code AS game_code, g.name AS game_name
        FROM helper_modes hm
        JOIN game_modes gm ON gm.id = hm.mode_id
        JOIN games g ON g.code = gm.game_code
        WHERE {where}
        ORDER BY g.name, gm.name
        ''',
        (user_id,),
    ).all()


def set_helper_mode(user_id, mode_id, enabled):
    with db.transaction() as tx:
        if not tx('SELECT 1 FROM game_modes WHERE id = %s AND is_active = TRUE', (mode_id,)).one():
            return None
        tx(
            'INSERT INTO helper_profiles (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING',
            (user_id,),
        ).close()
        tx(
            '''
            INSERT INTO helper_modes (user_id, mode_id, is_active) VALUES (%s, %s, %s)
            ON CONFLICT (user_id, mode_id) DO UPDATE SET is_active = EXCLUDED.is_active
            ''',
            (user_id, mode_id, enabled),
        ).close()
        if enabled:
            tx(
                'UPDATE helper_profiles SET is_active = TRUE, updated_at = now() WHERE user_id = %s',
                (user_id,),
            ).close()
        else:
            remaining = tx(
                'SELECT COUNT(*) AS cnt FROM helper_modes WHERE user_id = %s AND is_active = TRUE',
                (user_id,),
            ).one()['cnt']
            if not remaining:
                tx(
                    'UPDATE helper_profiles SET is_active = FALSE, updated_at = now() WHERE user_id = %s',
                    (user_id,),
                ).close()
        return enabled


def set_helper_paused(user_id, paused):
    with db.transaction() as tx:
        row = tx(
            '''
            UPDATE helper_profiles SET is_paused = %s, updated_at = now()
            WHERE user_id = %s RETURNING user_id
            ''',
            (paused, user_id),
        ).one()
        return bool(row)


def disable_helper(user_id):
    with db.transaction() as tx:
        tx(
            '''
            UPDATE helper_profiles SET is_active = FALSE, updated_at = now()
            WHERE user_id = %s
            ''',
            (user_id,),
        ).close()
        tx('UPDATE helper_modes SET is_active = FALSE WHERE user_id = %s', (user_id,)).close()


def create_help_request(requester_user_id, mode_id, chat_id, message_thread_id):
    with db.transaction() as tx:
        if not tx('SELECT 1 FROM users WHERE id = %s AND left_at IS NULL', (requester_user_id,)).one():
            return {'status': 'invalid'}
        if not tx('SELECT 1 FROM game_modes WHERE id = %s AND is_active = TRUE', (mode_id,)).one():
            return {'status': 'invalid'}
        if tx(
            '''
            SELECT 1 FROM help_requests
            WHERE requester_user_id = %s AND mode_id = %s AND status = ANY(%s)
            ''',
            (requester_user_id, mode_id, ACTIVE_REQUEST_STATUSES),
        ).one():
            return {'status': 'already_exists'}
        helpers = _eligible_helpers(tx, mode_id, requester_user_id)
        if not helpers:
            return {'status': 'no_helpers'}
        request = tx(
            '''
            INSERT INTO help_requests (
                requester_user_id, mode_id, chat_id, message_thread_id, expires_at
            )
            VALUES (%s, %s, %s, %s, now() + INTERVAL '24 hours')
            RETURNING *
            ''',
            (requester_user_id, mode_id, chat_id, message_thread_id),
        ).one()
        return {'status': 'created', 'request': request, 'helpers': helpers}


def save_request_message_id(request_id, message_id):
    db(
        'UPDATE help_requests SET request_message_id = %s WHERE id = %s',
        (message_id, request_id),
    ).close()


def create_help_offer(request_id, helper_user_id):
    return db(
        '''
        INSERT INTO help_request_offers (request_id, helper_user_id)
        VALUES (%s, %s) RETURNING id
        ''',
        (request_id, helper_user_id),
    ).one()


def save_offer_message_id(offer_id, message_id):
    db(
        'UPDATE help_request_offers SET telegram_message_id = %s WHERE id = %s',
        (message_id, offer_id),
    ).close()


def mark_offer_unavailable(offer_id):
    db(
        '''
        UPDATE help_request_offers SET status = 'UNAVAILABLE', responded_at = now()
        WHERE id = %s AND status = 'PENDING'
        ''',
        (offer_id,),
    ).close()


def list_request_offers(request_id):
    return db(
        '''
        SELECT hro.*, u.tg_id AS helper_tg_id
        FROM help_request_offers hro JOIN users u ON u.id = hro.helper_user_id
        WHERE hro.request_id = %s
        ORDER BY hro.id
        ''',
        (request_id,),
    ).all()


def finalize_help_offers(request_id):
    with db.transaction() as tx:
        request = tx('SELECT status FROM help_requests WHERE id = %s FOR UPDATE', (request_id,)).one()
        if not request or request['status'] != 'OPEN':
            return True
        pending = tx(
            "SELECT COUNT(*) AS cnt FROM help_request_offers WHERE request_id = %s AND status = 'PENDING'",
            (request_id,),
        ).one()['cnt']
        if pending:
            return True
        tx("UPDATE help_requests SET status = 'NO_HELPERS', expires_at = NULL WHERE id = %s", (request_id,)).close()
        return False


def decline_help_offer(request_id, helper_user_id):
    with db.transaction() as tx:
        request = tx('SELECT * FROM help_requests WHERE id = %s FOR UPDATE', (request_id,)).one()
        offer = tx(
            '''
            SELECT * FROM help_request_offers
            WHERE request_id = %s AND helper_user_id = %s FOR UPDATE
            ''',
            (request_id, helper_user_id),
        ).one()
        if not request or request['status'] != 'OPEN' or not offer or offer['status'] != 'PENDING':
            return {'status': 'inactive'}
        tx(
            "UPDATE help_request_offers SET status = 'DECLINED', responded_at = now() WHERE id = %s",
            (offer['id'],),
        ).close()
        pending = tx(
            "SELECT COUNT(*) AS cnt FROM help_request_offers WHERE request_id = %s AND status = 'PENDING'",
            (request_id,),
        ).one()['cnt']
        all_declined = pending == 0
        if all_declined:
            tx(
                "UPDATE help_requests SET status = 'REJECTED', expires_at = NULL, updated_at = now() WHERE id = %s",
                (request_id,),
            ).close()
        return {'status': 'declined', 'all_declined': all_declined}


def claim_help_request(request_id, helper_user_id):
    with db.transaction() as tx:
        request = tx('SELECT * FROM help_requests WHERE id = %s FOR UPDATE', (request_id,)).one()
        offer = tx(
            '''
            SELECT * FROM help_request_offers
            WHERE request_id = %s AND helper_user_id = %s
            ''',
            (request_id, helper_user_id),
        ).one()
        if (
            not request or request['status'] != 'OPEN'
            or request['requester_user_id'] == helper_user_id
            or not offer or offer['status'] != 'PENDING'
        ):
            return None
        if not tx(
            '''
            SELECT 1 FROM helper_modes hm
            JOIN helper_profiles hp ON hp.user_id = hm.user_id
            JOIN users u ON u.id = hm.user_id
            WHERE hm.user_id = %s AND hm.mode_id = %s AND hm.is_active = TRUE
              AND hp.is_active = TRUE AND hp.is_paused = FALSE AND hp.dm_available = TRUE
              AND u.left_at IS NULL
            ''',
            (helper_user_id, request['mode_id']),
        ).one():
            return None
        tx(
            '''
            UPDATE help_request_offers
            SET status = CASE WHEN id = %s THEN 'ACCEPTED' ELSE 'CLOSED' END,
                responded_at = now()
            WHERE request_id = %s AND status = 'PENDING'
            ''',
            (offer['id'], request_id),
        ).close()
        tx(
            '''
            UPDATE help_requests
            SET status = 'SCHEDULING', assigned_helper_id = %s,
                expires_at = now() + INTERVAL '10 minutes',
                lock_version = lock_version + 1, updated_at = now()
            WHERE id = %s
            ''',
            (helper_user_id, request_id),
        ).close()
        return tx(f'{REQUEST_SELECT} WHERE hr.id = %s', (request_id,)).one()


def schedule_help_request(request_id, helper_user_id, scheduled_for):
    with db.transaction() as tx:
        request = tx('SELECT * FROM help_requests WHERE id = %s FOR UPDATE', (request_id,)).one()
        if (
            not request or request['status'] != 'SCHEDULING'
            or request['assigned_helper_id'] != helper_user_id
        ):
            return None
        tx(
            '''
            UPDATE help_requests
            SET status = 'CONFIRMING', scheduled_for = %s,
                expires_at = now() + INTERVAL '1 hour',
                lock_version = lock_version + 1, updated_at = now()
            WHERE id = %s
            ''',
            (scheduled_for, request_id),
        ).close()
        return tx(f'{REQUEST_SELECT} WHERE hr.id = %s', (request_id,)).one()


def confirm_help_request(request_id, requester_user_id):
    with db.transaction() as tx:
        request = tx('SELECT * FROM help_requests WHERE id = %s FOR UPDATE', (request_id,)).one()
        if (
            not request or request['status'] != 'CONFIRMING'
            or request['requester_user_id'] != requester_user_id
        ):
            return None
        tx(
            '''
            UPDATE help_requests
            SET status = 'ASSIGNED', expires_at = NULL,
                lock_version = lock_version + 1, updated_at = now()
            WHERE id = %s
            ''',
            (request_id,),
        ).close()
        return tx(f'{REQUEST_SELECT} WHERE hr.id = %s', (request_id,)).one()


def cancel_help_request(request_id, user_id):
    with db.transaction() as tx:
        request = tx('SELECT * FROM help_requests WHERE id = %s FOR UPDATE', (request_id,)).one()
        if (
            not request or request['status'] not in ACTIVE_REQUEST_STATUSES
            or user_id not in {request['requester_user_id'], request['assigned_helper_id']}
        ):
            return None
        tx(
            '''
            UPDATE help_requests
            SET status = 'CANCELLED', expires_at = NULL,
                lock_version = lock_version + 1, updated_at = now()
            WHERE id = %s
            ''',
            (request_id,),
        ).close()
        tx(
            "UPDATE help_request_offers SET status = 'CLOSED', responded_at = now() WHERE request_id = %s AND status = 'PENDING'",
            (request_id,),
        ).close()
        return tx(f'{REQUEST_SELECT} WHERE hr.id = %s', (request_id,)).one()


def reject_help_request(request_id, requester_user_id):
    with db.transaction() as tx:
        request = tx('SELECT * FROM help_requests WHERE id = %s FOR UPDATE', (request_id,)).one()
        if (
            not request or request['status'] != 'CONFIRMING'
            or request['requester_user_id'] != requester_user_id
        ):
            return None
        tx(
            '''
            UPDATE help_requests
            SET status = 'CANCELLED', expires_at = NULL,
                lock_version = lock_version + 1, updated_at = now()
            WHERE id = %s
            ''',
            (request_id,),
        ).close()
        return tx(f'{REQUEST_SELECT} WHERE hr.id = %s', (request_id,)).one()


def complete_help_request(request_id, user_id):
    with db.transaction() as tx:
        request = tx('SELECT * FROM help_requests WHERE id = %s FOR UPDATE', (request_id,)).one()
        if (
            not request or request['status'] != 'ASSIGNED'
            or user_id not in {request['requester_user_id'], request['assigned_helper_id']}
        ):
            return None
        tx(
            '''
            UPDATE help_requests
            SET status = 'COMPLETED', completed_at = now(), expires_at = NULL,
                lock_version = lock_version + 1, updated_at = now()
            WHERE id = %s
            ''',
            (request_id,),
        ).close()
        return tx(f'{REQUEST_SELECT} WHERE hr.id = %s', (request_id,)).one()


def expire_help_requests():
    with db.transaction() as tx:
        rows = tx(
            '''
            UPDATE help_requests
            SET status = 'EXPIRED', expires_at = NULL,
                lock_version = lock_version + 1, updated_at = now()
            WHERE status IN ('OPEN', 'SCHEDULING', 'CONFIRMING')
              AND expires_at IS NOT NULL AND expires_at <= now()
            RETURNING id
            '''
        ).all()
        if not rows:
            return []
        request_ids = [row['id'] for row in rows]
        tx(
            "UPDATE help_request_offers SET status = 'EXPIRED', responded_at = now() WHERE request_id = ANY(%s) AND status = 'PENDING'",
            (request_ids,),
        ).close()
    return db(f'{REQUEST_SELECT} WHERE hr.id = ANY(%s)', (request_ids,)).all()


def _audit_assistance(tx, admin_tg_id, action, entity_type, entity_id):
    tx(
        '''
        INSERT INTO admin_audit_log (admin_tg_id, action, entity_type, entity_id)
        VALUES (%s, %s, %s, %s)
        ''',
        (admin_tg_id, action, entity_type, str(entity_id)),
    ).close()


def list_admin_game_modes():
    return db(
        '''
        SELECT gm.id, gm.name, gm.is_active, g.code AS game_code, g.name AS game_name,
            (SELECT COUNT(*) FROM helper_modes hm
             WHERE hm.mode_id = gm.id AND hm.is_active = TRUE) AS helper_count
        FROM game_modes gm JOIN games g ON g.code = gm.game_code
        ORDER BY g.name, gm.name
        '''
    ).all()


def create_game_mode(admin_tg_id, game_code, name):
    with db.transaction() as tx:
        if not tx('SELECT 1 FROM games WHERE code = %s', (game_code,)).one():
            raise ValueError('Игра не найдена')
        if tx(
            'SELECT 1 FROM game_modes WHERE game_code = %s AND lower(name) = lower(%s)',
            (game_code, name),
        ).one():
            raise ValueError('Такой режим уже есть у этой игры')
        row = tx(
            'INSERT INTO game_modes (game_code, name) VALUES (%s, %s) RETURNING id',
            (game_code, name),
        ).one()
        _audit_assistance(tx, admin_tg_id, 'create', 'game_mode', row['id'])
        return row['id']


def set_game_mode_active(admin_tg_id, mode_id, active):
    with db.transaction() as tx:
        row = tx(
            'UPDATE game_modes SET is_active = %s WHERE id = %s RETURNING id',
            (active, mode_id),
        ).one()
        if not row:
            raise ValueError('Режим не найден')
        _audit_assistance(tx, admin_tg_id, 'update', 'game_mode', mode_id)


def list_admin_helpers():
    return db(
        '''
        SELECT u.id, u.tg_id, u.tag, hp.is_active, hp.is_paused, hp.dm_available,
            (SELECT STRING_AGG(g.name || ': ' || gm.name, ', ' ORDER BY g.name, gm.name)
             FROM helper_modes hm
             JOIN game_modes gm ON gm.id = hm.mode_id
             JOIN games g ON g.code = gm.game_code
             WHERE hm.user_id = u.id AND hm.is_active = TRUE AND gm.is_active = TRUE) AS modes,
            (SELECT COUNT(*) FROM help_requests hr
             WHERE hr.assigned_helper_id = u.id AND hr.status = 'COMPLETED') AS completed_count
        FROM helper_profiles hp JOIN users u ON u.id = hp.user_id
        ORDER BY u.tag NULLS LAST, u.id
        '''
    ).all()


def set_helper_admin_active(admin_tg_id, user_id, active):
    with db.transaction() as tx:
        row = tx(
            '''
            UPDATE helper_profiles SET is_active = %s, updated_at = now()
            WHERE user_id = %s RETURNING user_id
            ''',
            (active, user_id),
        ).one()
        if not row:
            raise ValueError('Помогатор не найден')
        _audit_assistance(tx, admin_tg_id, 'update', 'helper', user_id)


def list_admin_help_requests(status='', game_code=''):
    where = []
    params = []
    if status:
        where.append('hr.status = %s')
        params.append(status)
    if game_code:
        where.append('g.code = %s')
        params.append(game_code)
    suffix = f"WHERE {' AND '.join(where)}" if where else ''
    return db(
        f'{REQUEST_SELECT} {suffix} ORDER BY hr.created_at DESC LIMIT 100',
        tuple(params),
    ).all()


def admin_cancel_help_request(admin_tg_id, request_id):
    with db.transaction() as tx:
        row = tx(
            '''
            UPDATE help_requests SET status = 'CANCELLED', expires_at = NULL,
                lock_version = lock_version + 1, updated_at = now()
            WHERE id = %s AND status = ANY(%s)
            RETURNING id
            ''',
            (request_id, ACTIVE_REQUEST_STATUSES),
        ).one()
        if not row:
            raise ValueError('Активная заявка не найдена')
        tx(
            "UPDATE help_request_offers SET status = 'CLOSED', responded_at = now() WHERE request_id = %s AND status = 'PENDING'",
            (request_id,),
        ).close()
        _audit_assistance(tx, admin_tg_id, 'cancel', 'help_request', request_id)
