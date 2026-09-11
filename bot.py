import asyncio
import hashlib
import logging
import os
import re
import time
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from dotenv import load_dotenv

from database import init_db, mark_moderation, save_message
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
    "job_spam": "предложение работы/подработки",
    "fake_purchase_spam": "фиктивная покупка/доказательство оплаты",
    "flood": "флуд/повтор",
}

WINDOW_SECONDS = 60
MAX_TIMESTAMPS_PER_USER = 20
MAX_RECENT_MESSAGES_PER_USER = 5
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
    variant = lowered.translate(str.maketrans({"$": "с", "s": "с"}))
    return text + " " + variant


def spaced_job_fallback(text: str) -> bool:
    """Catch job words deliberately split by spaces, e.g. 'подрабо тку'."""
    normalized = (text or "").casefold()
    compact = re.sub(r"[^а-яёa-z]", "", normalized)
    return bool(
        re.search(r"подработ\w*", compact, re.IGNORECASE | re.UNICODE)
        or re.search(r"шабаш\w*", compact, re.IGNORECASE | re.UNICODE)
        or re.search(r"ваканс\w*", compact, re.IGNORECASE | re.UNICODE)
    )


def direct_gender_job_fallback(text: str) -> bool:
    """Catch short job requests such as 'Нужны девочки' even without extra context."""
    normalized = " ".join((text or "").casefold().split())
    return bool(
        re.search(r"\bнужн(?:ы|а)\s+девочк\w*\b", normalized)
        or re.search(r"\bнужн(?:ы|а)\s+девуш\w*\b", normalized)
        or re.search(r"\b(?:ищу|требуется|требуются)\s+девочк\w*\b", normalized)
        or re.search(r"\b(?:ищу|требуется|требуются)\s+девуш\w*\b", normalized)
    )


def direct_child_job_fallback(text: str) -> bool:
    """Catch explicit requests for children/minors as workers without blocking ordinary child-related text."""
    normalized = " ".join((text or "").casefold().split())
    child = r"(?:дет(?:и|ей|ям|ьми|ях)?|реб[её]нок|ребят|подрост(?:ок|ка|ки|ков)?|школьник\w*)"
    request = r"(?:нуж(?:ен|на|ны)|ищ(?:у|ем)|требу(?:ется|ются)|ищем|возьм(?:у|ём)|ищется)"
    work_context = r"(?:на\s+работу|для\s+работы|на\s+подработку|для\s+подработки|работать|подработать|на\s+съёмку|для\s+съёмки|на\s+съемку|для\s+съемки)"
    return bool(
        re.search(rf"\b{request}\s+{child}(?:\s+{work_context})?\b", normalized)
        or re.search(rf"\b{request}\s+{child}\s+{work_context}\b", normalized)
        or re.search(rf"\b{child}\s+{work_context}\b", normalized)
    )


async def store_command(message: Message) -> None:
    if in_target_chat(message):
        await save_message(message, message.text or message.caption or "")


@router.message(CommandStart())
async def start_command(message: Message) -> None:
    await store_command(message)
    await message.answer("✅ BK AntiSpam работает.")


@router.message(Command("chat_id"))
async def chat_id_command(message: Message) -> None:
    await store_command(message)
    await message.answer(f"CHAT_ID: {message.chat.id}")


@router.message(Command("ping"))
async def ping_command(message: Message) -> None:
    await store_command(message)
    await message.answer("🏓 pong")


@router.message()
async def moderate(message: Message, bot: Bot) -> None:
    if not in_target_chat(message):
        return

    text = message.text or message.caption or ""

    await save_message(message, text)

    classification_text = profanity_variants(text)

    if has_any_link(message, text):
        reason = "link"
    else:
        reason = classify(classification_text)
        if reason is None and direct_gender_job_fallback(classification_text):
            reason = "job_spam"
            logging.info(
                "Gender-job fallback matched chat=%s message=%s text=%r",
                message.chat.id,
                message.message_id,
                text,
            )
        elif reason is None and direct_child_job_fallback(classification_text):
            reason = "job_spam"
            logging.info(
                "Child-job fallback matched chat=%s message=%s text=%r",
                message.chat.id,
                message.message_id,
                text,
            )
        elif reason is None and spaced_job_fallback(classification_text):
            reason = "job_spam"
            logging.info("Spaced-job fallback matched chat=%s message=%s", message.chat.id, message.message_id)

    logging.info(
        "CLASSIFY chat=%s message=%s reason=%s text=%r",
        message.chat.id,
        message.message_id,
        reason,
        text,
    )

    if reason is None and is_flood(message, text):
        reason = "flood"

    await mark_moderation(
        message,
        classification=reason,
        deleted=False,
        reason=REASONS.get(reason) if reason else None,
    )

    if not reason:
        return

    try:
        await bot.delete_message(
            chat_id=message.chat.id,
            message_id=message.message_id,
        )
        await mark_moderation(
            message,
            classification=reason,
            deleted=True,
            reason=REASONS.get(reason, reason),
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
    await init_db()
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
