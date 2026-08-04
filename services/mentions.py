import math
import random

from telegram.ext import ContextTypes

CRAB_EMOJIS = list("🪬🧸🔫🪁🪼🍁🍙🤿🛸⚠️")

async def mention_users(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    tags: list[str],
    message_thread_id: int | None = None,
):
    for i in range(math.ceil(len(tags) / 5)):
        batch = tags[i * 5:(i + 1) * 5]
        mentions = " ".join(f"@{tag}" for tag in batch)

        emoji = random.choice(CRAB_EMOJIS) if random.randint(0, 500) == 77 else "🦀"

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{emoji} {mentions}",
            message_thread_id=message_thread_id,
        )