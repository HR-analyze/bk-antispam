import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message
from dotenv import load_dotenv

from moderation import classify

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

router = Router()

REASONS = {
    "link": "ссылка",
    "profanity": "мат",
    "spam": "спам/реклама",
}


@router.message()
async def moderate(message: Message, bot: Bot) -> None:
    # Text/caption is enough for the first rule-based stage.
    text = message.text or message.caption or ""
    reason = classify(text)

    if not reason:
        return

    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        logging.info(
            "Deleted message chat=%s message=%s reason=%s user=%s",
            message.chat.id,
            message.message_id,
            REASONS[reason],
            message.from_user.id if message.from_user else "unknown",
        )
    except Exception:
        logging.exception(
            "Failed to delete message chat=%s message=%s reason=%s",
            message.chat.id,
            message.message_id,
            reason,
        )


async def main() -> None:
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    me = await bot.get_me()
    logging.info("Bot started: @%s (%s)", me.username, me.id)
    await dp.start_polling(bot, allowed_updates=["message"])


if __name__ == "__main__":
    asyncio.run(main())
