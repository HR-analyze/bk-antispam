import asyncio
import hashlib
import logging
import os
import time
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message
from dotenv import load_dotenv

from moderation import classify, contains_link

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

router = Router()

REASONS = {
    "link": "ссылка",
    "profanity": "мат",
    "spam": "спам/реклама",
    "flood": "флуд/повтор",
}

# Память процесса: для первой версии базы данных не требуется.
# Храним только короткое окно активности пользователей.
WINDOW_SECONDS = 60
MAX_TIMESTAMPS_PER_USER = 20
MAX_RECENT_MESSAGES_PER_USER = 5

user_timestamps: dict[tuple[int, int], deque[float]] = defaultdict(deque)
user_recent_hashes: dict[tuple[int, int], deque[tuple[float, str]]] = defaultdict(deque)


def cleanup_user_state(key: tuple[int, int], now: float) -> None:
    timestamps = user_timestamps[key]
    while timestamps and now - timestamps[0] > WINDOW_SECONDS:
        timestamps.popleft()

    recent = user_recent_hashes[key]
    while recent and now - recent[0][0] > WINDOW_SECONDS:
        recent.popleft()


def message_fingerprint(text: str) -> str:
    normalized = " ".join((text or "").casefold().split())
    normalized = normalized[:2000]
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def is_flood(message: Message, text: str) -> bool:
    user = message.from_user
    if not user or not text.strip():
        return False

    key = (message.chat.id, user.id)
    now = time.monotonic()
    cleanup_user_state(key, now)

    timestamps = user_timestamps[key]
    recent = user_recent_hashes[key]

    timestamps.append(now)
    while len(timestamps) > MAX_TIMESTAMPS_PER_USER:
        timestamps.popleft()

    fingerprint = message_fingerprint(text)
    # Повтор того же сообщения от одного пользователя в течение минуты.
    if any(old_hash == fingerprint for _, old_hash in recent):
        recent.append((now, fingerprint))
        while len(recent) > MAX_RECENT_MESSAGES_PER_USER:
            recent.popleft()
        return True

    recent.append((now, fingerprint))
    while len(recent) > MAX_RECENT_MESSAGES_PER_USER:
        recent.popleft()

    # Сильный флуд: 6+ текстовых сообщений за минуту.
    if len(timestamps) >= 6:
        return True

    return False


def has_any_link(message: Message, text: str) -> bool:
    # URL может быть спрятан в кликабельном тексте и тогда regex его не увидит.
    entities = list(message.entities or []) + list(message.caption_entities or [])
    if any(entity.type in {"url", "text_link"} for entity in entities):
        return True
    return contains_link(text)


@router.message()
async def moderate(message: Message, bot: Bot) -> None:
    text = message.text or message.caption or ""

    # Любая ссылка — безусловное удаление.
    if has_any_link(message, text):
        reason = "link"
    else:
        reason = classify(text)

    # Антифлуд применяется только к текстовым/подписанным сообщениям,
    # чтобы обычные фото/видео клиентов не блокировались на этом этапе.
    if reason is None and is_flood(message, text):
        reason = "flood"

    if not reason:
        return

    try:
        await bot.delete_message(
            chat_id=message.chat.id,
            message_id=message.message_id,
        )
        logging.info(
            "Deleted chat=%s message=%s reason=%s user=%s",
            message.chat.id,
            message.message_id,
            REASONS.get(reason, reason),
            message.from_user.id if message.from_user else "unknown",
        )
    except Exception:
        logging.exception(
            "Failed to delete chat=%s message=%s reason=%s",
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
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
    )


if __name__ == "__main__":
    asyncio.run(main())
