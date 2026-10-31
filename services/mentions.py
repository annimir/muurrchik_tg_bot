import html
import math
import random

from telegram.ext import ContextTypes

CRAB_EMOJIS = list("🪬🧸🔫🪁🪼🍁🍙🤿🛸⚠️")


async def mention_users(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    users: list[dict],
    message_thread_id: int | None = None,
):
    for i in range(math.ceil(len(users) / 5)):
        batch = users[i * 5:(i + 1) * 5]
        mentions = []
        for user in batch:
            label = f'@{user["username"]}' if user['username'] else 'участник'
            mentions.append(
                f'<a href="tg://user?id={user["tg_id"]}">{html.escape(label, quote=False)}</a>'
            )

        emoji = random.choice(CRAB_EMOJIS) if random.randint(0, 500) == 77 else "🦀"
        await context.bot.send_message(
            chat_id=chat_id,
            text=f'{emoji} {" ".join(mentions)}',
            parse_mode='HTML',
            message_thread_id=message_thread_id,
        )
