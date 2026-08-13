import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, filters

from database.queries import (
    add_flavor_role, get_flavor_role_by_name, get_users_with_role,
    delete_flavor_role, get_all_flavor_roles, get_user_by_tg_id, create_user, get_users_without_role,
)

from services.flavor_roles import assign_random_role
from services.admin import is_admin, admin_lang
from message.loader import message
from message.keys import (
    common_private_only, roles_not_admin, roles_usage_add, roles_added, roles_already_exists,
    roles_usage_remove, roles_not_found, roles_removed, roles_list_header, roles_list_empty,
    roles_reroll_prompt, roles_reroll_forward_invalid, roles_reroll_done, roles_no_roles_available,
    backfill_none_needed, backfill_done,
)

logger = logging.getLogger(__name__)

WAITING_REROLL_FORWARD = range(1)[0]


def _guard_ok(update: Update, lang: str) -> bool:
    return update.effective_chat.type == 'private' and is_admin(update.effective_user.id)


async def add_role_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = admin_lang()

    if update.effective_chat.type != 'private':
        await update.message.reply_text(message(lang, common_private_only, 'common'))
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(message(lang, roles_not_admin, 'roles'))
        return

    if not context.args:
        await update.message.reply_text(message(lang, roles_usage_add, 'roles'))
        return

    name = ' '.join(context.args).strip()
    role_id = add_flavor_role(name)

    if role_id is None:
        await update.message.reply_text(message(lang, roles_already_exists, 'roles', name))
        return

    logger.info("Админ добавил роль '%s' (id=%d)", name, role_id)
    await update.message.reply_text(message(lang, roles_added, 'roles', name))


async def remove_role_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = admin_lang()

    if update.effective_chat.type != 'private':
        await update.message.reply_text(message(lang, common_private_only, 'common'))
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(message(lang, roles_not_admin, 'roles'))
        return

    if not context.args:
        await update.message.reply_text(message(lang, roles_usage_remove, 'roles'))
        return

    name = ' '.join(context.args).strip()
    role = get_flavor_role_by_name(name)

    if not role:
        await update.message.reply_text(message(lang, roles_not_found, 'roles', name))
        return

    affected_users = get_users_with_role(role['id'])
    delete_flavor_role(role['id'])
    logger.info("Админ удалил роль '%s', затронуто пользователей: %d", name, len(affected_users))

    reassigned = 0
    for u in affected_users:
        new_role = assign_random_role(u['id'])
        if new_role:
            reassigned += 1

    await update.message.reply_text(
        message(lang, roles_removed, 'roles', name, reassigned, len(affected_users))
    )


async def list_roles_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = admin_lang()

    if update.effective_chat.type != 'private':
        await update.message.reply_text(message(lang, common_private_only, 'common'))
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(message(lang, roles_not_admin, 'roles'))
        return

    roles = get_all_flavor_roles()
    if not roles:
        await update.message.reply_text(message(lang, roles_list_empty, 'roles'))
        return

    names = "\n".join(f'• {r["name"]}' for r in roles)
    await update.message.reply_text(
        f'{message(lang, roles_list_header, "roles")}\n{names}', parse_mode='Markdown'
    )


async def start_reroll_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = admin_lang()

    if update.effective_chat.type != 'private':
        await update.message.reply_text(message(lang, common_private_only, 'common'))
        return ConversationHandler.END
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(message(lang, roles_not_admin, 'roles'))
        return ConversationHandler.END

    if not get_all_flavor_roles():
        await update.message.reply_text(message(lang, roles_no_roles_available, 'roles'))
        return ConversationHandler.END

    await update.message.reply_text(message(lang, roles_reroll_prompt, 'roles'))
    return WAITING_REROLL_FORWARD


async def receive_reroll_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = admin_lang()
    origin = update.message.forward_origin

    if origin is None or origin.type != 'user':
        await update.message.reply_text(message(lang, roles_reroll_forward_invalid, 'roles'))
        return WAITING_REROLL_FORWARD

    target_user = origin.sender_user

    db_user = get_user_by_tg_id(target_user.id)
    if not db_user:
        create_user(target_user.id, target_user.username or target_user.full_name)
        db_user = get_user_by_tg_id(target_user.id)

    from database.queries import get_user_flavor_role
    old_role = get_user_flavor_role(db_user['id'])
    old_role_id = old_role['id'] if old_role else None

    new_role_name = assign_random_role(db_user['id'], exclude_role_id=old_role_id)
    logger.info(
        "Админ перевыдал роль пользователю %s: было '%s', стало '%s'",
        target_user.id, old_role['name'] if old_role else None, new_role_name,
    )

    await update.message.reply_text(
        message(lang, roles_reroll_done, 'roles', target_user.full_name, new_role_name),
        parse_mode='Markdown',
    )
    return ConversationHandler.END

async def backfill_cards_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = admin_lang()

    if update.effective_chat.type != 'private':
        await update.message.reply_text(message(lang, common_private_only, 'common'))
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(message(lang, roles_not_admin, 'roles'))
        return

    users = get_users_without_role()

    if not users:
        await update.message.reply_text(message(lang, backfill_none_needed, 'backfill'))
        return

    for u in users:
        assign_random_role(u['id'])

    logger.info("Админ выполнил бэкафилл ролей для %d пользователей без роли", len(users))
    await update.message.reply_text(message(lang, backfill_done, 'backfill', len(users)))