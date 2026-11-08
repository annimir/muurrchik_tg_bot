import html
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from database.assistance import (
    cancel_help_request, claim_help_request, complete_help_request, confirm_help_request,
    create_help_offer, create_help_request, decline_help_offer, finalize_help_offers,
    get_game_mode, get_help_request, list_assistance_games, list_game_modes,
    list_request_offers, mark_offer_unavailable, reject_help_request, save_offer_message_id,
    save_request_message_id, schedule_help_request, set_helper_dm_available,
)
from database.queries import ensure_user, get_user_by_tg_id, get_user_language
from database.wish_rewards import record_wish_activity
from message.keys import (
    assist_all_declined, assist_already_exists, assist_button_accept, assist_button_cancel,
    assist_button_complete, assist_button_confirm, assist_button_custom, assist_button_decline,
    assist_button_evening, assist_button_reject, assist_button_tomorrow, assist_button_two_hours,
    assist_cancelled, assist_choose_game, assist_choose_mode, assist_choose_time,
    assist_completed, assist_confirmed, assist_created, assist_custom_time_prompt,
    assist_declined, assist_invalid_time, assist_no_games, assist_no_helpers,
    assist_not_allowed, assist_offer, assist_ready, assist_rejected, assist_taken,
    assist_time_sent, assist_unavailable,
)
from message.loader import message

logger = logging.getLogger(__name__)
MOSCOW_TZ = ZoneInfo('Europe/Moscow')


def _user_label(tg_id, tag):
    label = f'@{tag}' if tag else f'Игрок {tg_id}'
    return f'<a href="tg://user?id={tg_id}">{html.escape(label, quote=False)}</a>'


def _format_time(value):
    return value.astimezone(MOSCOW_TZ).strftime('%d.%m.%Y %H:%M')


def _time_keyboard(request_id, lang):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            message(lang, assist_button_two_hours, 'assist'),
            callback_data=f'assist_time:plus2:{request_id}',
        )],
        [InlineKeyboardButton(
            message(lang, assist_button_evening, 'assist'),
            callback_data=f'assist_time:evening:{request_id}',
        ), InlineKeyboardButton(
            message(lang, assist_button_tomorrow, 'assist'),
            callback_data=f'assist_time:tomorrow:{request_id}',
        )],
        [InlineKeyboardButton(
            message(lang, assist_button_custom, 'assist'),
            callback_data=f'assist_time:custom:{request_id}',
        )],
        [InlineKeyboardButton(
            message(lang, assist_button_cancel, 'assist'),
            callback_data=f'assist_request:cancel:{request_id}',
        )],
    ])


def _parse_custom_time(raw):
    raw = raw.strip()
    now = datetime.now(MOSCOW_TZ)
    try:
        if ':' in raw and '.' not in raw:
            parsed_time = datetime.strptime(raw, '%H:%M').time()
            result = datetime.combine(now.date(), parsed_time, tzinfo=MOSCOW_TZ)
            if result <= now:
                result += timedelta(days=1)
        else:
            parsed = datetime.strptime(raw, '%d.%m %H:%M')
            result = parsed.replace(year=now.year, tzinfo=MOSCOW_TZ)
    except ValueError:
        return None
    return result if result > now else None


async def assist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    lang = get_user_language(tg_user.id)
    ensure_user(tg_user.id, tg_user.username or tg_user.full_name)
    games = list_assistance_games()
    if not games:
        await update.effective_message.reply_text(message(lang, assist_no_games, 'assist'))
        return
    buttons = [
        [InlineKeyboardButton(
            game['name'], callback_data=f'assist:select:{tg_user.id}:game:{game["code"]}',
        )]
        for game in games
    ]
    await update.effective_message.reply_text(
        message(lang, assist_choose_game, 'assist'), reply_markup=InlineKeyboardMarkup(buttons),
    )


async def assist_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    lang = get_user_language(query.from_user.id)
    _, _, owner_id, action, value = query.data.split(':', 4)
    if owner_id != str(query.from_user.id):
        await query.answer(message(lang, assist_not_allowed, 'assist'), show_alert=True)
        return
    db_user = get_user_by_tg_id(query.from_user.id)
    if action == 'game':
        modes = list_game_modes(value)
        game = next(game for game in list_assistance_games() if game['code'] == value)
        buttons = [
            [InlineKeyboardButton(
                mode['name'],
                callback_data=f'assist:select:{owner_id}:mode:{mode["id"]}',
            )]
            for mode in modes
        ]
        await query.edit_message_text(
            message(lang, assist_choose_mode, 'assist', game['name']),
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        await query.answer()
        return

    mode = get_game_mode(int(value))
    result = create_help_request(
        db_user['id'], mode['id'], query.message.chat.id, query.message.message_thread_id,
    )
    if result['status'] == 'already_exists':
        await query.edit_message_text(message(lang, assist_already_exists, 'assist'))
    elif result['status'] == 'no_helpers':
        await query.edit_message_text(message(lang, assist_no_helpers, 'assist', mode['name']))
    elif result['status'] == 'created':
        request_id = result['request']['id']
        text = message(lang, assist_created, 'assist', request_id, mode['game_name'], mode['name'])
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                message(lang, assist_button_cancel, 'assist'),
                callback_data=f'assist_request:cancel:{request_id}',
            ),
        ]])
        await query.edit_message_text(text, reply_markup=markup)
        save_request_message_id(request_id, query.message.message_id)
        for helper in result['helpers']:
            offer = create_help_offer(request_id, helper['id'])
            helper_lang = get_user_language(helper['tg_id'])
            try:
                sent = await context.bot.send_message(
                    helper['tg_id'],
                    message(
                        helper_lang, assist_offer, 'assist', request_id, mode['game_name'],
                        mode['name'], helper_label(db_user),
                    ),
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            message(helper_lang, assist_button_accept, 'assist'),
                            callback_data=f'assist_offer:accept:{request_id}',
                        ),
                        InlineKeyboardButton(
                            message(helper_lang, assist_button_decline, 'assist'),
                            callback_data=f'assist_offer:decline:{request_id}',
                        ),
                    ]]),
                )
                save_offer_message_id(offer['id'], sent.message_id)
            except TelegramError:
                mark_offer_unavailable(offer['id'])
                set_helper_dm_available(helper['id'], False)
                logger.info('Не удалось отправить заявку помогатору %s', helper['tg_id'])
        if not finalize_help_offers(request_id):
            await query.edit_message_text(
                message(lang, assist_no_helpers, 'assist', mode['name']),
            )
    else:
        await query.edit_message_text(message(lang, assist_unavailable, 'assist'))
    await query.answer()


def helper_label(db_user):
    return f'@{db_user["tag"]}' if db_user['tag'] else str(db_user['tg_id'])


async def assist_offer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    lang = get_user_language(query.from_user.id)
    action, request_id = query.data.split(':')[1:3]
    request_id = int(request_id)
    helper = get_user_by_tg_id(query.from_user.id)
    if not helper:
        await query.answer(message(lang, assist_not_allowed, 'assist'), show_alert=True)
        return
    if action == 'decline':
        result = decline_help_offer(request_id, helper['id'])
        if result['status'] == 'inactive':
            await query.answer(message(lang, assist_unavailable, 'assist'), show_alert=True)
            return
        await query.edit_message_text(message(lang, assist_declined, 'assist', request_id))
        if result['all_declined']:
            request = get_help_request(request_id)
            await _edit_group_request(
                context, request, message(lang, assist_all_declined, 'assist', request_id),
            )
        await query.answer()
        return

    request = claim_help_request(request_id, helper['id'])
    if not request:
        await query.edit_message_text(message(lang, assist_unavailable, 'assist'))
        await query.answer()
        return
    await query.edit_message_text(
        message(lang, assist_choose_time, 'assist', request_id),
        reply_markup=_time_keyboard(request_id, lang),
    )
    for offer in list_request_offers(request_id):
        if offer['helper_tg_id'] != helper['tg_id'] and offer['telegram_message_id']:
            try:
                await context.bot.edit_message_text(
                    message(lang, assist_taken, 'assist'),
                    chat_id=offer['helper_tg_id'], message_id=offer['telegram_message_id'],
                )
            except TelegramError:
                logger.info('Не удалось закрыть предложение помогатору %s', offer['helper_tg_id'])
    await query.answer()


async def assist_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    lang = get_user_language(query.from_user.id)
    action, request_id = query.data.split(':')[1:3]
    request_id = int(request_id)
    if action == 'custom':
        context.user_data['assist_custom_request'] = request_id
        await query.edit_message_text(message(lang, assist_custom_time_prompt, 'assist'))
        await query.answer()
        return
    now = datetime.now(MOSCOW_TZ)
    if action == 'plus2':
        scheduled = now + timedelta(hours=2)
    elif action == 'evening':
        scheduled = now.replace(hour=20, minute=0, second=0, microsecond=0)
        if scheduled <= now:
            scheduled += timedelta(days=1)
    elif action == 'tomorrow':
        scheduled = now.replace(hour=20, minute=0, second=0, microsecond=0) + timedelta(days=1)
    else:
        await query.answer()
        return
    await _schedule_request(update, context, request_id, scheduled)


async def assist_custom_time_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    request_id = context.user_data.get('assist_custom_request')
    if not request_id or update.effective_chat.type != 'private':
        return
    scheduled = _parse_custom_time(update.effective_message.text)
    lang = get_user_language(update.effective_user.id)
    if not scheduled:
        await update.effective_message.reply_text(message(lang, assist_invalid_time, 'assist'))
        return
    await _schedule_request(update, context, request_id, scheduled)


async def _schedule_request(update, context, request_id, scheduled):
    helper = get_user_by_tg_id(update.effective_user.id)
    lang = get_user_language(update.effective_user.id)
    request = schedule_help_request(request_id, helper['id'], scheduled)
    if not request:
        text = message(lang, assist_unavailable, 'assist')
        if update.callback_query:
            await update.callback_query.edit_message_text(text)
            await update.callback_query.answer()
        else:
            await update.effective_message.reply_text(text)
        return
    context.user_data.pop('assist_custom_request', None)
    text = message(lang, assist_time_sent, 'assist', _format_time(scheduled))
    if update.callback_query:
        await update.callback_query.edit_message_text(text)
        await update.callback_query.answer()
    else:
        await update.effective_message.reply_text(text)
    requester_lang = get_user_language(request['requester_tg_id'])
    ready_text = message(
        requester_lang, assist_ready, 'assist',
        _user_label(request['helper_tg_id'], request['helper_tag']),
        request['game_name'], request['mode_name'], _format_time(scheduled),
    )
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            message(requester_lang, assist_button_confirm, 'assist'),
            callback_data=f'assist_request:confirm:{request_id}',
        ),
        InlineKeyboardButton(
            message(requester_lang, assist_button_reject, 'assist'),
            callback_data=f'assist_request:reject:{request_id}',
        ),
    ]])
    await _edit_group_request(context, request, ready_text, markup)


async def _edit_group_request(context, request, text, markup=None):
    if request['request_message_id']:
        await context.bot.edit_message_text(
            text=text, chat_id=request['chat_id'], message_id=request['request_message_id'],
            parse_mode='HTML', reply_markup=markup,
        )
    else:
        sent = await context.bot.send_message(
            chat_id=request['chat_id'], text=text, message_thread_id=request['message_thread_id'],
            parse_mode='HTML', reply_markup=markup,
        )
        save_request_message_id(request['id'], sent.message_id)


async def assist_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    lang = get_user_language(query.from_user.id)
    action, request_id = query.data.split(':')[1:3]
    request_id = int(request_id)
    user = get_user_by_tg_id(query.from_user.id)
    if action == 'confirm':
        request = confirm_help_request(request_id, user['id'])
        if request:
            text = message(
                lang, assist_confirmed, 'assist', request_id,
                _user_label(request['helper_tg_id'], request['helper_tag']),
                _format_time(request['scheduled_for']),
            )
            markup = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    message(lang, assist_button_complete, 'assist'),
                    callback_data=f'assist_request:complete:{request_id}',
                ),
                InlineKeyboardButton(
                    message(lang, assist_button_cancel, 'assist'),
                    callback_data=f'assist_request:cancel:{request_id}',
                ),
            ]])
            await _edit_group_request(context, request, text, markup)
            await context.bot.send_message(request['helper_tg_id'], text, parse_mode='HTML', reply_markup=markup)
    elif action == 'reject':
        request = reject_help_request(request_id, user['id'])
        if request:
            text = message(lang, assist_rejected, 'assist', request_id)
            await _edit_group_request(context, request, text)
            await context.bot.send_message(request['helper_tg_id'], text)
    elif action == 'cancel':
        request = cancel_help_request(request_id, user['id'])
        if request:
            text = message(lang, assist_cancelled, 'assist', request_id)
            await _edit_group_request(context, request, text)
            if request['helper_tg_id']:
                await context.bot.send_message(request['helper_tg_id'], text)
    elif action == 'complete':
        request = complete_help_request(request_id, user['id'])
        if request:
            text = message(lang, assist_completed, 'assist', request_id)
            reward = record_wish_activity(
                'help_completed', request['assigned_helper_id'], 'help_request', request_id,
            )
            if reward:
                text = f'{text}\nПомогатору начислено +{reward["amount"]} молитв.'
            await _edit_group_request(context, request, text)
            if request['helper_tg_id'] and request['helper_tg_id'] != query.from_user.id:
                await context.bot.send_message(request['helper_tg_id'], text)
    else:
        request = None
    if not request:
        await query.answer(message(lang, assist_not_allowed, 'assist'), show_alert=True)
    else:
        await query.answer()
