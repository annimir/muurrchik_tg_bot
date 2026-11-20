import json

from database.queries import db


def _values(title, summary, content, cover_alt='', tags=()):
    title = title.strip()
    summary = summary.strip()
    content = content.strip()
    cover_alt = cover_alt.strip()
    if not 1 <= len(title) <= 120:
        raise ValueError('Заголовок должен содержать от 1 до 120 символов')
    if not 1 <= len(summary) <= 300:
        raise ValueError('Краткое описание должно содержать от 1 до 300 символов')
    if not 1 <= len(content) <= 20000:
        raise ValueError('Текст новости должен содержать от 1 до 20000 символов')
    if len(cover_alt) > 200:
        raise ValueError('Описание обложки должно содержать не более 200 символов')
    normalized_tags = []
    for tag in tags:
        tag = tag.strip().lstrip('#').strip()
        if not tag:
            continue
        if len(tag) > 50:
            raise ValueError('Каждый тег должен содержать не более 50 символов')
        if tag.casefold() not in {value.casefold() for value in normalized_tags}:
            normalized_tags.append(tag)
    if len(normalized_tags) > 10:
        raise ValueError('Можно указать не более 10 тегов')
    return title, summary, content, cover_alt, normalized_tags


def _audit(tx, admin_tg_id, action, news_id, details):
    tx(
        '''
        INSERT INTO admin_audit_log (admin_tg_id, action, entity_type, entity_id, details)
        VALUES (%s, %s, 'news', %s, %s::jsonb)
        ''',
        (admin_tg_id, action, str(news_id), json.dumps(details, ensure_ascii=False)),
    ).close()


def _public_select():
    return '''
        SELECT n.*, u.id AS author_id, u.tag AS author_tag
        FROM news_posts n LEFT JOIN users u ON u.tg_id = n.created_by
    '''


def list_public_news(limit=None, tag=''):
    query = _public_select() + ' WHERE n.is_published'
    params = []
    if tag:
        query += ' AND %s = ANY(n.tags)'
        params.append(tag)
    query += ' ORDER BY n.published_at DESC, n.id DESC'
    if limit is not None:
        query += ' LIMIT %s'
        params.append(limit)
    return db(query, tuple(params)).all()


def get_public_news(news_id):
    return db(
        _public_select() + ' WHERE n.id = %s AND n.is_published', (news_id,),
    ).one()


def list_admin_news():
    return db('SELECT * FROM news_posts ORDER BY created_at DESC, id DESC').all()


def get_admin_news(news_id):
    return db('SELECT * FROM news_posts WHERE id = %s', (news_id,)).one()


def list_news_tags():
    return db(
        '''
        SELECT DISTINCT unnest(tags) AS name FROM news_posts
        WHERE is_published ORDER BY name
        ''',
    ).all()


def create_news(
    admin_tg_id, title, summary, content, is_published,
    cover_image=None, cover_alt='', tags=(),
):
    title, summary, content, cover_alt, tags = _values(
        title, summary, content, cover_alt, tags,
    )
    with db.transaction() as tx:
        row = tx(
            '''
            INSERT INTO news_posts (
                title, summary, content, is_published, published_at, created_by,
                cover_image, cover_alt, tags
            ) VALUES (%s, %s, %s, %s, CASE WHEN %s THEN now() END, %s, %s, %s, %s)
            RETURNING *
            ''',
            (
                title, summary, content, is_published, is_published, admin_tg_id,
                cover_image or None, cover_alt or None, tags,
            ),
        ).one()
        _audit(tx, admin_tg_id, 'create', row['id'], {'title': title, 'published': is_published})
        return row


def update_news(
    admin_tg_id, news_id, title, summary, content, is_published,
    cover_image=None, cover_alt='', tags=(),
):
    title, summary, content, cover_alt, tags = _values(
        title, summary, content, cover_alt, tags,
    )
    with db.transaction() as tx:
        row = tx(
            '''
            UPDATE news_posts
            SET title = %s, summary = %s, content = %s, is_published = %s,
                published_at = CASE
                    WHEN %s THEN COALESCE(published_at, now())
                    ELSE published_at
                END,
                cover_image = %s, cover_alt = %s, tags = %s, updated_at = now()
            WHERE id = %s RETURNING *
            ''',
            (
                title, summary, content, is_published, is_published,
                cover_image or None, cover_alt or None, tags, news_id,
            ),
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
