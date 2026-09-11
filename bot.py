import asyncio
import hashlib
import logging
import os
import time
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message
from dotenv import load_dotenv

from database import init_db, mark_moderation, save_message
from moderation import REASONS, contains_link, decide, explain_message, ruleset_summary

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


@router.message(Command("version"))
async def version_command(message: Message) -> None:
    """Показывает, какие правила реально запущены.

    Отвечает на вопрос «доехал ли деплой?» без доступа к серверу: хеш меняется
    при любой правке словарей модерации.
    """
    await store_command(message)
    rules = ruleset_summary()
    build = os.getenv("BUILD_SHA", "").strip()
    lines = [
        f"правила: {rules['fingerprint']}",
        f"фраз о работе: {rules['job_phrases']} (+{rules['weak_job_phrases']} слабых)",
        f"шаблонов мата: {rules['profanity_patterns']}",
        f"категорий: {rules['categories']}",
    ]
    if build:
        lines.append(f"сборка: {build}")
    await message.answer("🔧 " + "\n".join(lines))


# Нормализованный текст может быть длиной почти во всё сообщение, а ответ
# Telegram обязан уместиться в 4096 символов.
CHECK_ECHO_LIMIT = 200

ADMIN_STATUSES = {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR}


async def is_chat_admin(bot: Bot, message: Message) -> bool:
    user = message.from_user
    if user is None:
        return False
    try:
        member = await bot.get_chat_member(message.chat.id, user.id)
    except Exception:
        logging.exception("get_chat_member failed chat=%s", message.chat.id)
        return False
    return member.status in ADMIN_STATUSES


def format_check_reply(result: dict, fingerprint: str) -> str:
    """Ответ /check.

    Заблокированный текст обратно НЕ печатаем: сообщения бота модерацию не
    проходят, поэтому эхо превратило бы диагностику в способ опубликовать
    через бота то, что бот и должен удалять.
    """
    if result["reason"]:
        lines = [
            f"🗑 УДАЛИЛ БЫ — {result['label']}",
            f"правило: {result['rule']}",
            "текст не повторяю: он попадает под удаление",
        ]
    else:
        normalized = result["normalized"] or "(пусто)"
        if len(normalized) > CHECK_ECHO_LIMIT:
            normalized = normalized[:CHECK_ECHO_LIMIT] + "…"
        lines = ["✅ оставил бы", f"после нормализации: {normalized}"]
    lines.append(f"версия правил: {fingerprint}")
    return "\n".join(lines)


@router.message(Command("check"))
async def check_command(message: Message, command: CommandObject, bot: Bot) -> None:
    """Спросить у ЗАПУЩЕННОГО бота, что он сделает с текстом.

    Отвечает на «почему это не удалилось» без логов и доступа к серверу:
    вердикт приходит от того самого кода, который сейчас работает.

    В группе доступно только администраторам — иначе командой можно шуметь в
    клиентском чате. В личке с ботом работает у всех.
    """
    await store_command(message)

    if message.chat.type != ChatType.PRIVATE and not await is_chat_admin(bot, message):
        return

    probe = (command.args or "").strip()
    if not probe:
        await message.answer("Напиши текст после команды: /check нужна девочка")
        return

    # Ссылка может жить в entity, а не в тексте. Боевой путь её видит, поэтому
    # и диагностика обязана — иначе она даст противоположный вердикт.
    result = explain_message(probe, has_link=has_any_link(message, probe))
    await message.answer(format_check_reply(result, ruleset_summary()["fingerprint"]))


@router.message(Command("ping"))
async def ping_command(message: Message) -> None:
    await store_command(message)
    await message.answer("🏓 pong")


# Правки сообщений — отдельный тип апдейта. Без этого обработчика спамер
# постит безобидный текст, а затем правит его на спам, и бот этого не видит.
@router.message()
@router.edited_message()
async def moderate(message: Message, bot: Bot) -> None:
    # Пишется ДО проверки чата: если сюда ничего не приходит — бот не видит
    # апдейтов; если приходит, а CLASSIFY ниже нет — не совпал CHAT_ID.
    logging.info(
        "MODERATION INPUT chat=%s message=%s type=%s text=%r",
        message.chat.id,
        message.message_id,
        message.content_type,
        message.text or message.caption or "",
    )

    if not in_target_chat(message):
        logging.info(
            "SKIPPED: chat=%s не совпал с CHAT_ID=%s", message.chat.id, CHAT_ID
        )
        return

    text = message.text or message.caption or ""
    edited = message.edit_date is not None

    await save_message(message, text)

    # Падение здесь раньше уносило весь обработчик: mark_moderation не
    # вызывался, сообщение оставалось в чате, а в дашборде выглядело «чистым».
    # Теперь сбой виден и в логах, и в дашборде.
    try:
        reason, rule = decide(text, has_link=has_any_link(message, text))
    except Exception:
        logging.exception(
            "CLASSIFY FAILED chat=%s message=%s text=%r",
            message.chat.id,
            message.message_id,
            text,
        )
        await mark_moderation(
            message, classification="error", deleted=False, reason=REASONS["error"]
        )
        return

    # Правка — не флуд: считать её повтором нельзя, иначе автор, поправивший
    # опечатку, получает метку флуда.
    if reason is None and not edited and is_flood(message, text):
        reason, rule = "flood", "flood"

    logging.info(
        "CLASSIFY chat=%s message=%s edited=%s reason=%s rule=%s text=%r",
        message.chat.id,
        message.message_id,
        edited,
        reason,
        rule,
        text,
    )

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
    # Версия правил печатается при каждом старте: `docker logs <контейнер> | head`
    # сразу показывает, какая сборка поднялась, без захода в чат за /version.
    rules = ruleset_summary()
    build = os.getenv("BUILD_SHA", "").strip()
    logging.info(
        "Правила модерации: %s | фраз о работе %s (+%s слабых) | шаблонов мата %s | категорий %s%s",
        rules["fingerprint"],
        rules["job_phrases"],
        rules["weak_job_phrases"],
        rules["profanity_patterns"],
        rules["categories"],
        f" | сборка {build}" if build else "",
    )
    logging.info("Bot started: @%s (%s) CHAT_ID=%s", me.username, me.id, CHAT_ID)
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
    )


if __name__ == "__main__":
    asyncio.run(main())
