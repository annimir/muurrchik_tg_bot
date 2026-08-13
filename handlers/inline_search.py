import logging
from uuid import uuid4

from telegram import Update, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import ContextTypes

from services.auth import auth
from database.queries import (
    get_top_tags_by_subscribers, get_top_tags_by_usage, get_top_users_by_subscriptions,
    get_tag_subscribers, search_tags, get_user_language,
)
from services.admin import is_admin
from handlers.tagging import create_subscribe_markup
from message.loader import message
from message.keys import inline_top_all, inline_top_users, inline_top15, inline_subscribers_prefix, inline_top_usage, inline_top_usage_admin

logger = logging.getLogger(__name__)


async def inline_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query
    user = update.effective_user

    await auth(user.id, user.username)
    lang = get_user_language(user.id)

    results = []

    tags = search_tags(query.query)[::-1]

    top_by_subs = get_top_tags_by_subscribers()
    top_by_usage_30d = get_top_tags_by_usage(days=30)

    if is_admin(user.id):
        top_str = "\n".join(f'{n+1}. {row["name"]} - {row["cnt"]}' for n, row in enumerate(top_by_subs))
        results.append(InlineQueryResultArticle(
            id=str(uuid4()), title="✨ Топ подписчиков ✨[ADMIN]",
            input_message_content=InputTextMessageContent(message(lang, inline_top_all, 'inline', top_str)),
        ))

        top_usage_str = "\n".join(f'{n+1}. {row["name"]} - {row["cnt"]}' for n, row in enumerate(top_by_usage_30d))
        results.append(InlineQueryResultArticle(
            id=str(uuid4()), title="✨ Топ использований (30д) ✨[ADMIN]",
            input_message_content=InputTextMessageContent(message(lang, inline_top_usage_admin, 'inline', top_usage_str)),
        ))

        top_users = get_top_users_by_subscriptions()
        top_users_str = "\n".join(f'{n+1}. {row["username"]} - {row["cnt"]}' for n, row in enumerate(top_users))
        results.append(InlineQueryResultArticle(
            id=str(uuid4()), title="✨ Топ пользователей ✨[ADMIN]",
            input_message_content=InputTextMessageContent(message(lang, inline_top_users, 'inline', top_users_str)),
        ))

    top15_str = "\n".join(f'{n+1}. {row["name"]} - {row["cnt"]}' for n, row in enumerate(top_by_subs[:15]))
    results.append(InlineQueryResultArticle(
        id=str(uuid4()), title="Топ 15 (подписчики)",
        input_message_content=InputTextMessageContent(message(lang, inline_top15, 'inline', top15_str)),
    ))

    top_usage15_str = "\n".join(f'{n+1}. {row["name"]} - {row["cnt"]}' for n, row in enumerate(top_by_usage_30d[:15]))
    results.append(InlineQueryResultArticle(
        id=str(uuid4()), title="Топ 15 (использования, 30д)",
        input_message_content=InputTextMessageContent(message(lang, inline_top_usage, 'inline', top_usage15_str)),
    ))

    for tag in tags[:40]:
        # search_tags() уже отдаёт id вместе с name — лишний запрос
        # get_tag_by_name() на каждой итерации не нужен
        subs = get_tag_subscribers(tag['id'])
        subs_str = ", ".join(s['username'] for s in subs)
        if subs_str:
            results.append(InlineQueryResultArticle(
                id=str(uuid4()), title=tag['name'],
                input_message_content=InputTextMessageContent(
                    f'#{tag["name"]}\n\n' + message(lang, inline_subscribers_prefix, 'inline', subs_str)
                ),
                reply_markup=create_subscribe_markup(tag['name']),
            ))

    await query.answer(results, cache_time=0)
    logger.info("Inline-запрос от %s: '%s', результатов %d", user.id, query.query, len(results))