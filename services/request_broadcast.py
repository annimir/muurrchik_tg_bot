import logging

from telegram.error import TelegramError

from database.queries import get_all_admin_ids, save_request_notification, get_request_notifications, claim_request

logger = logging.getLogger(__name__)


async def broadcast_to_admins(context, request_type, request_id, send_fn):
    for admin_tg_id in get_all_admin_ids():
        try:
            sent = await send_fn(admin_tg_id)
        except TelegramError as e:
            logger.warning("Не удалось отправить заявку %s#%d админу %s: %s", request_type, request_id, admin_tg_id, e)
            continue
        if sent:
            save_request_notification(request_type, request_id, admin_tg_id, sent.message_id)


async def sync_all_copies(context, request_type, request_id, build_fn, exclude_admin_tg_id=None, is_photo=False):
    """
    Используется только для approve/reject — там query.message гарантированно
    собственная копия нажавшего (approve/reject видны только после claim,
    только в его собственном уведомлении), так что этот путь остаётся корректным.
    """
    notifications = get_request_notifications(request_type, request_id)

    for note in notifications:
        admin_tg_id = note['admin_tg_id']
        if exclude_admin_tg_id is not None and admin_tg_id == exclude_admin_tg_id:
            continue

        text, markup = build_fn(admin_tg_id)

        try:
            if is_photo:
                await context.bot.edit_message_caption(
                    chat_id=admin_tg_id, message_id=note['message_id'],
                    caption=text, parse_mode='Markdown', reply_markup=markup,
                )
            else:
                await context.bot.edit_message_text(
                    chat_id=admin_tg_id, message_id=note['message_id'],
                    text=text, parse_mode='Markdown', reply_markup=markup,
                )
        except TelegramError as e:
            logger.warning(
                "Не удалось синхронизировать копию заявки %s#%d у админа %s: %s",
                request_type, request_id, admin_tg_id, e,
            )


async def claim_and_sync(context, request_type, request_id, admin_tg_id, build_claimer_view, build_other_view):
    """
    ДОБАВЛЕНО (исправление бага): в отличие от sync_all_copies, НЕ полагается
    на query.message как на "собственную копию" нажавшего — обновляет ВСЕ
    копии (включая копию самого claimer'а) строго по записям
    request_notifications (chat_id+message_id). Единственный надёжный способ,
    раз клик "Взять в работу" теперь может прийти и из личного уведомления
    админа, и из общего /pendingrequests.

    build_claimer_view(admin_tg_id) -> (text_or_caption, markup, is_photo)
    build_other_view(admin_tg_id) -> (text_or_caption, markup, is_photo)
    """
    claim_request(request_type, request_id, admin_tg_id)

    notifications = get_request_notifications(request_type, request_id)

    for note in notifications:
        target_admin_tg_id = note['admin_tg_id']
        is_claimer = target_admin_tg_id == admin_tg_id

        text, markup, is_photo = build_claimer_view(target_admin_tg_id) if is_claimer else build_other_view(target_admin_tg_id)

        try:
            if is_photo:
                await context.bot.edit_message_caption(
                    chat_id=target_admin_tg_id, message_id=note['message_id'],
                    caption=text, parse_mode='Markdown', reply_markup=markup,
                )
            else:
                await context.bot.edit_message_text(
                    chat_id=target_admin_tg_id, message_id=note['message_id'],
                    text=text, parse_mode='Markdown', reply_markup=markup,
                )
        except TelegramError as e:
            logger.warning(
                "Не удалось обновить копию заявки %s#%d у админа %s: %s",
                request_type, request_id, target_admin_tg_id, e,
            )