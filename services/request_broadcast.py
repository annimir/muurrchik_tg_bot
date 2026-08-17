import logging

from telegram.error import TelegramError

from database.queries import get_all_admin_ids, save_request_notification, get_request_notifications

logger = logging.getLogger(__name__)


async def broadcast_to_admins(context, request_type, request_id, send_fn):
    """
    send_fn(admin_tg_id) -> awaitable, возвращает отправленное Message.
    Рассылает всем текущим админам, сохраняет message_id каждой копии
    для последующей синхронизации.
    """
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
    build_fn(admin_tg_id) -> (text, reply_markup_or_None).
    Обновляет ВСЕ сохранённые копии уведомления под новое состояние,
    кроме exclude_admin_tg_id (обычно — тот, кто только что нажал кнопку,
    у него копия уже обновлена напрямую через query).
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