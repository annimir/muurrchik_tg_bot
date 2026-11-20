import json

from database.queries import db


def _values(title, summary, content):
    title = title.strip()
    summary = summary.strip()
    content = content.strip()
    if not 1 <= len(title) <= 120:
        raise ValueError('Заголовок должен содержать от 1 до 120 символов')
    if not 1 <= len(summary) <= 300:
        raise ValueError('Краткое описание должно содержать от 1 до 300 символов')
    if not 1 <= len(content) <= 20000:
        raise ValueError('Текст новости должен содержать от 1 до 20000 символов')
    return title, summary, content


def _audit(tx, admin_tg_id, action, news_id, details):
    tx(
        '''
        INSERT INTO admin_audit_log (admin_tg_id, action, entity_type, entity_id, details)
        VALUES (%s, %s, 'news', %s, %s::jsonb)
        ''',
        (admin_tg_id, action, str(news_id), json.dumps(details, ensure_ascii=False)),
    ).close()


def list_public_news(limit=None):
    query = '''
        SELECT id, title, summary, published_at FROM news_posts
        WHERE is_published ORDER BY published_at DESC, id DESC
    '''
    params = ()
    if limit is not None:
        query += ' LIMIT %s'
        params = (limit,)
    return db(query, params).all()


def get_public_news(news_id):
    return db(
        'SELECT * FROM news_posts WHERE id = %s AND is_published', (news_id,),
    ).one()


def list_admin_news():
    return db('SELECT * FROM news_posts ORDER BY created_at DESC, id DESC').all()


def get_admin_news(news_id):
    return db('SELECT * FROM news_posts WHERE id = %s', (news_id,)).one()


def create_news(admin_tg_id, title, summary, content, is_published):
    title, summary, content = _values(title, summary, content)
    with db.transaction() as tx:
        row = tx(
            '''
            INSERT INTO news_posts (
                title, summary, content, is_published, published_at, created_by
            ) VALUES (%s, %s, %s, %s, CASE WHEN %s THEN now() END, %s)
            RETURNING *
            ''',
            (title, summary, content, is_published, is_published, admin_tg_id),
        ).one()
        _audit(tx, admin_tg_id, 'create', row['id'], {'title': title, 'published': is_published})
        return row


def update_news(admin_tg_id, news_id, title, summary, content, is_published):
    title, summary, content = _values(title, summary, content)
    with db.transaction() as tx:
        row = tx(
            '''
            UPDATE news_posts
            SET title = %s, summary = %s, content = %s, is_published = %s,
                published_at = CASE
                    WHEN %s THEN COALESCE(published_at, now())
                    ELSE published_at
                END,
                updated_at = now()
            WHERE id = %s RETURNING *
            ''',
            (title, summary, content, is_published, is_published, news_id),
        ).one()
        if not row:
            raise ValueError('Новость не найдена')
        _audit(tx, admin_tg_id, 'update', news_id, {'title': title, 'published': is_published})
        return row


def delete_news(admin_tg_id, news_id):
    with db.transaction() as tx:
        row = tx('DELETE FROM news_posts WHERE id = %s RETURNING title', (news_id,)).one()
        if not row:
            raise ValueError('Новость не найдена')
        _audit(tx, admin_tg_id, 'delete', news_id, {'title': row['title']})


def mark_news_telegram_sent(news_id, message_id):
    return db(
        '''
        UPDATE news_posts SET telegram_message_id = %s, telegram_sent_at = now()
        WHERE id = %s RETURNING *
        ''',
        (message_id, news_id),
    ).one()
