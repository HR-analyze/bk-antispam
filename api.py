import os
from typing import Optional

import psycopg
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "").strip()

app = FastAPI(title="BK AntiSpam Dashboard API", version="1.1.0")

# Dashboard can be hosted separately. Restrict this later to the exact dashboard
# origin via DASHBOARD_CORS_ORIGINS; wildcard is only for initial setup.
origins = [x.strip() for x in os.getenv("DASHBOARD_CORS_ORIGINS", "*").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["X-API-Key", "Content-Type"],
)

# Messages carry classification NULL when the bot found nothing wrong; the
# dashboard shows that bucket as "clean" and may filter on it.
CLEAN = "clean"

# message_date comes from Telegram and can be missing; created_at always exists.
# Every endpoint buckets on the same expression so all numbers agree.
TS = "COALESCE(message_date, created_at)"


def require_api_key(x_api_key: Optional[str]) -> None:
    if not DASHBOARD_API_KEY:
        raise HTTPException(status_code=503, detail="DASHBOARD_API_KEY is not configured")
    if x_api_key != DASHBOARD_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


def window(days: Optional[int], params: list) -> str:
    """WHERE clause limiting rows to the last `days` days, or nothing."""
    if not days:
        return ""
    params.append(days)
    return f" WHERE {TS} >= NOW() - (%s * INTERVAL '1 day')"


async def fetch_all(query: str, params: tuple = ()):
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")
    try:
        async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(query, params)
                return await cur.fetchall()
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Database query failed") from exc


async def fetch_one(query: str, params: tuple = ()):
    rows = await fetch_all(query, params)
    return rows[0] if rows else None


@app.get("/health")
async def health():
    return {"status": "ok", "database_configured": bool(DATABASE_URL), "api_key_configured": bool(DASHBOARD_API_KEY)}


@app.get("/api/stats")
async def stats(
    x_api_key: Optional[str] = Header(default=None),
    days: Optional[int] = Query(default=None, ge=1, le=3650),
):
    require_api_key(x_api_key)
    params: list = []
    where = window(days, params)
    row = await fetch_one(f"""
        SELECT
            COUNT(*)::bigint AS total_messages,
            COUNT(*) FILTER (WHERE deleted)::bigint AS deleted_messages,
            COUNT(*) FILTER (WHERE NOT deleted AND classification IS NOT NULL)::bigint AS flagged_kept,
            COUNT(DISTINCT user_id)::bigint AS unique_users,
            COUNT(*) FILTER (WHERE {TS} >= NOW() - INTERVAL '24 hours')::bigint AS messages_24h,
            COUNT(*) FILTER (WHERE deleted AND {TS} >= NOW() - INTERVAL '24 hours')::bigint AS deleted_24h,
            MAX({TS}) AS last_message_at
        FROM public.messages
        {where}
    """, tuple(params))
    return row or {}


@app.get("/api/messages")
async def messages(
    x_api_key: Optional[str] = Header(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    classification: Optional[str] = Query(default=None, max_length=50),
    deleted: Optional[bool] = None,
    user_id: Optional[int] = None,
    q: Optional[str] = Query(default=None, max_length=500),
    days: Optional[int] = Query(default=None, ge=1, le=3650),
):
    require_api_key(x_api_key)
    conditions = []
    params: list = []
    if classification == CLEAN:
        conditions.append("classification IS NULL")
    elif classification:
        conditions.append("classification = %s")
        params.append(classification)
    if deleted is not None:
        conditions.append("deleted = %s")
        params.append(deleted)
    if user_id is not None:
        conditions.append("user_id = %s")
        params.append(user_id)
    if q:
        conditions.append("text ILIKE %s")
        params.append(f"%{q}%")
    if days:
        conditions.append(f"{TS} >= NOW() - (%s * INTERVAL '1 day')")
        params.append(days)

    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    total_row = await fetch_one(
        f"SELECT COUNT(*)::bigint AS total FROM public.messages {where}", tuple(params)
    )
    rows = await fetch_all(f"""
        SELECT id, chat_id, message_id, user_id, username, first_name, last_name,
               text, message_date, reply_to_message_id, classification, deleted,
               delete_reason, created_at
        FROM public.messages
        {where}
        ORDER BY {TS} DESC, id DESC
        LIMIT %s OFFSET %s
    """, tuple(params + [limit, offset]))
    return {
        "items": rows,
        "total": total_row["total"] if total_row else 0,
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/classifications")
async def classifications(
    x_api_key: Optional[str] = Header(default=None),
    days: Optional[int] = Query(default=None, ge=1, le=3650),
):
    require_api_key(x_api_key)
    params: list = []
    where = window(days, params)
    return await fetch_all(f"""
        SELECT COALESCE(classification, '{CLEAN}') AS classification,
               COUNT(*)::bigint AS count,
               COUNT(*) FILTER (WHERE deleted)::bigint AS deleted_count
        FROM public.messages
        {where}
        GROUP BY COALESCE(classification, '{CLEAN}')
        ORDER BY count DESC
    """, tuple(params))


@app.get("/api/top-users")
async def top_users(
    x_api_key: Optional[str] = Header(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    days: Optional[int] = Query(default=None, ge=1, le=3650),
):
    require_api_key(x_api_key)
    params: list = []
    where = window(days, params)
    clause = f"{where} AND user_id IS NOT NULL" if where else " WHERE user_id IS NOT NULL"
    params.append(limit)
    return await fetch_all(f"""
        SELECT user_id, username, first_name, last_name,
               COUNT(*)::bigint AS messages,
               COUNT(*) FILTER (WHERE deleted)::bigint AS deleted_messages
        FROM public.messages
        {clause}
        GROUP BY user_id, username, first_name, last_name
        ORDER BY deleted_messages DESC, messages DESC
        LIMIT %s
    """, tuple(params))


@app.get("/api/daily")
async def daily(
    x_api_key: Optional[str] = Header(default=None),
    days: int = Query(default=30, ge=1, le=365),
):
    require_api_key(x_api_key)
    return await fetch_all(f"""
        SELECT ({TS} AT TIME ZONE 'UTC')::date AS date,
               COUNT(*)::bigint AS messages,
               COUNT(*) FILTER (WHERE deleted)::bigint AS deleted_messages
        FROM public.messages
        WHERE {TS} >= NOW() - (%s * INTERVAL '1 day')
        GROUP BY 1
        ORDER BY 1
    """, (days,))
