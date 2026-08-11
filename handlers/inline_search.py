import logging
from uuid import uuid4

from telegram import Update, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import ContextTypes

from services.auth import auth
from database.queries import (
    get_active_tags, get_tag_subscribers, get_all_users,
    get_user_subscriptions, search_characters, get_user_language,
)
from handlers.characters_admin import is_admin
from handlers.tagging import create_subscribe_markup
from message.loader import message
from message.keys import inline_top_all, inline_top_users, inline_top15, inline_subscribers_prefix

logger = logging.getLogger(__name__)


async def inline_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query
    user = update.effective_user

    await auth(user.id, user.username)
    lang = get_user_language(user.id)

    results = []

    characters = search_characters(query.query)[::-1]
    all_characters = get_active_tags()

    top_characters = []
    for character in all_characters:
        subs = get_tag_subscribers(character['name'])
        top_characters.append((character['name'], len(subs)))
    top_characters.sort(key=lambda c: c[1], reverse=True)

    if is_admin(user.id):
        top_str = "\n".join(f'{n+1}. {c[0]} - {c[1]}' for n, c in enumerate(top_characters))
        results.append(InlineQueryResultArticle(
            id=str(uuid4()), title="✨ Топ всех ✨[ADMIN]",
            input_message_content=InputTextMessageContent(message(lang, inline_top_all, 'inline', top_str)),
        ))

        all_users = get_all_users()
        top_users = []
        for u in all_users:
            subs = get_user_subscriptions(u['tg_id'])
            top_users.append((u['tag'], len(subs)))
        top_users.sort(key=lambda c: c[1], reverse=True)

        top_users_str = "\n".join(f'{n+1}. {c[0]} - {c[1]}' for n, c in enumerate(top_users))
        results.append(InlineQueryResultArticle(
            id=str(uuid4()), title="✨ Топ пользователей ✨[ADMIN]",
            input_message_content=InputTextMessageContent(message(lang, inline_top_users, 'inline', top_users_str)),
        ))

    top15_str = "\n".join(f'{n+1}. {c[0]} - {c[1]}' for n, c in enumerate(top_characters[:15]))
    results.append(InlineQueryResultArticle(
        id=str(uuid4()), title="Топ 15",
        input_message_content=InputTextMessageContent(message(lang, inline_top15, 'inline', top15_str)),
    ))

    for character in characters[:40]:
        subs = get_tag_subscribers(character['name'])
        subs_str = ", ".join(s['tag'] for s in subs)
        if subs_str:
            results.append(InlineQueryResultArticle(
                id=str(uuid4()), title=character['name'],
                input_message_content=InputTextMessageContent(
                    f'#{character["name"]}\n\n' + message(lang, inline_subscribers_prefix, 'inline', subs_str)
                ),
                reply_markup=create_subscribe_markup(character['name']),
            ))

    await query.answer(results, cache_time=0)
    logger.info("Inline-запрос от %s: '%s', результатов %d", user.id, query.query, len(results))