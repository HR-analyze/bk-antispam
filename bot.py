import asyncio
import hashlib
import logging
import os
import time
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from dotenv import load_dotenv

from moderation import classify, contains_link

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID_RAW = os.getenv("CHAT_ID", "").strip()

try:
    CHAT_ID = int(CHAT_ID_RAW) if CHAT_ID_RAW else None
except ValueError as exc:
    raise RuntimeError("CHAT_ID must be an integer, for example -1001234567890") from exc

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
    "negative": "негатив",
    "spam": "спам/реклама",
    "flood": "флуд/повтор",
}

WINDOW_SECONDS = 60
MAX_TIMESTAMPS_PER_USER = 20
MAX_RECENT_MESSAGES_PER_USER = 5
# Six different test messages in a minute must not be treated as flood.
# Flood is primarily intended for repeated messages; a higher threshold
# prevents normal rapid conversations and moderation testing from being deleted.
FLOOD_MESSAGE_LIMIT = 15

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
    normalized = " ".join((text or "").casefold().split())[:2000]
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
    if any(old_hash == fingerprint for _, old_hash in recent):
        recent.append((now, fingerprint))
        while len(recent) > MAX_RECENT_MESSAGES_PER_USER:
            recent.popleft()
        return True

    recent.append((now, fingerprint))
    while len(recent) > MAX_RECENT_MESSAGES_PER_USER:
        recent.popleft()

    return len(timestamps) >= FLOOD_MESSAGE_LIMIT


def has_any_link(message: Message, text: str) -> bool:
    entities = list(message.entities or []) + list(message.caption_entities or [])
    if any(entity.type in {"url", "text_link"} for entity in entities):
        return True
    return contains_link(text)


def in_target_chat(message: Message) -> bool:
    return CHAT_ID is None or message.chat.id == CHAT_ID


def profanity_variants(text: str) -> str:
    """Add common Latin/symbol substitutions used to evade profanity filters."""
    lowered = (text or "").lower()
    variant = lowered.translate(str.maketrans({
        "$": "с",
        "s": "с",
    }))
    return text + " " + variant


@router.message(CommandStart())
async def start_command(message: Message) -> None:
    await message.answer("✅ BK AntiSpam работает.")


@router.message(Command("chat_id"))
async def chat_id_command(message: Message) -> None:
    await message.answer(f"CHAT_ID: {message.chat.id}")


@router.message(Command("ping"))
async def ping_command(message: Message) -> None:
    await message.answer("🏓 pong")


@router.message()
async def moderate(message: Message, bot: Bot) -> None:
    if not in_target_chat(message):
        return

    text = message.text or message.caption or ""
    classification_text = profanity_variants(text)

    if has_any_link(message, text):
        reason = "link"
    else:
        reason = classify(classification_text)

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
    logging.info("Bot started: @%s (%s) CHAT_ID=%s", me.username, me.id, CHAT_ID)
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
    )


if __name__ == "__main__":
    asyncio.run(main())
