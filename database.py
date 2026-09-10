import logging
import os

import psycopg

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

CREATE_TABLE_SQL = """
CREATE SCHEMA IF NOT EXISTS public;

CREATE TABLE IF NOT EXISTS public.messages (
    id BIGSERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    user_id BIGINT,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    text TEXT NOT NULL DEFAULT '',
    message_date TIMESTAMPTZ,
    reply_to_message_id BIGINT,
    classification TEXT,
    deleted BOOLEAN NOT NULL DEFAULT FALSE,
    delete_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (chat_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_date
    ON public.messages (chat_id, message_date DESC);
CREATE INDEX IF NOT EXISTS idx_messages_user_date
    ON public.messages (user_id, message_date DESC);
CREATE INDEX IF NOT EXISTS idx_messages_classification
    ON public.messages (classification);
"""


async def init_db() -> None:
    if not DATABASE_URL:
        logger.warning("DATABASE_URL is not set; PostgreSQL logging is disabled")
        return

    try:
        async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
            await conn.execute(CREATE_TABLE_SQL)
            await conn.commit()
            async with conn.cursor() as cur:
                await cur.execute("SELECT to_regclass('public.messages')")
                row = await cur.fetchone()
            if row and row[0] == "messages":
                logger.info("PostgreSQL initialized: public.messages exists")
            else:
                logger.error("PostgreSQL connected, but public.messages was not created")
    except Exception:
        logger.exception("PostgreSQL initialization failed")


async def save_message(message, text: str) -> bool:
    if not DATABASE_URL:
        return False

    user = message.from_user
    reply = message.reply_to_message

    sql = """
    INSERT INTO public.messages (
        chat_id, message_id, user_id, username, first_name, last_name,
        text, message_date, reply_to_message_id
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (chat_id, message_id) DO UPDATE SET
        text = EXCLUDED.text,
        username = EXCLUDED.username,
        first_name = EXCLUDED.first_name,
        last_name = EXCLUDED.last_name
    """

    try:
        async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
            await conn.execute(sql, (
                message.chat.id,
                message.message_id,
                user.id if user else None,
                user.username if user else None,
                user.first_name if user else None,
                user.last_name if user else None,
                text or "",
                message.date,
                reply.message_id if reply else None,
            ))
            await conn.commit()
        return True
    except Exception:
        logger.exception("Failed to save message %s", message.message_id)
        return False


async def mark_moderation(message, classification: str | None, deleted: bool, reason: str | None) -> None:
    if not DATABASE_URL:
        return

    try:
        async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
            await conn.execute(
                """
                UPDATE public.messages
                SET classification = %s, deleted = %s, delete_reason = %s
                WHERE chat_id = %s AND message_id = %s
                """,
                (classification, deleted, reason, message.chat.id, message.message_id),
            )
            await conn.commit()
    except Exception:
        logger.exception("Failed to update moderation for message %s", message.message_id)
