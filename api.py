import os
from datetime import datetime
from typing import Optional

import psycopg
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "").strip()

app = FastAPI(title="BK AntiSpam Dashboard API", version="1.0.0")

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


def require_api_key(x_api_key: Optional[str]) -> None:
    if not DASHBOARD_API_KEY:
        raise HTTPException(status_code=503, detail="DASHBOARD_API_KEY is not configured")
    if x_api_key != DASHBOARD_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


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
async def stats(x_api_key: Optional[str] = Header(default=None)):
    require_api_key(x_api_key)
    row = await fetch_one("""
        SELECT
            COUNT(*)::bigint AS total_messages,
            COUNT(*) FILTER (WHERE deleted)::bigint AS deleted_messages,
            COUNT(*) FILTER (WHERE NOT deleted AND classification IS NOT NULL)::bigint AS flagged_messages,
            COUNT(DISTINCT user_id)::bigint AS unique_users,
            COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours')::bigint AS messages_24h,
            COUNT(*) FILTER (WHERE deleted AND created_at >= NOW() - INTERVAL '24 hours')::bigint AS deleted_24h
        FROM public.messages
    """)
    return row or {}


@app.get("/api/messages")
async def messages(
    x_api_key: Optional[str] = Header(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    classification: Optional[str] = None,
    deleted: Optional[bool] = None,
    user_id: Optional[int] = None,
    q: Optional[str] = Query(default=None, max_length=500),
):
    require_api_key(x_api_key)
    conditions = []
    params = []
    if classification:
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

    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    params.extend([limit, offset])
    rows = await fetch_all(f"""
        SELECT id, chat_id, message_id, user_id, username, first_name, last_name,
               text, message_date, reply_to_message_id, classification, deleted,
               delete_reason, created_at
        FROM public.messages
        {where}
        ORDER BY message_date DESC NULLS LAST, id DESC
        LIMIT %s OFFSET %s
    """, tuple(params))
    return {"items": rows, "limit": limit, "offset": offset}


@app.get("/api/classifications")
async def classifications(x_api_key: Optional[str] = Header(default=None)):
    require_api_key(x_api_key)
    rows = await fetch_all("""
        SELECT COALESCE(classification, 'clean') AS classification, COUNT(*)::bigint AS count
        FROM public.messages
        GROUP BY COALESCE(classification, 'clean')
        ORDER BY count DESC
    """)
    return rows


@app.get("/api/top-users")
async def top_users(
    x_api_key: Optional[str] = Header(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    require_api_key(x_api_key)
    rows = await fetch_all("""
        SELECT user_id, username, first_name, last_name,
               COUNT(*)::bigint AS messages,
               COUNT(*) FILTER (WHERE deleted)::bigint AS deleted_messages
        FROM public.messages
        WHERE user_id IS NOT NULL
        GROUP BY user_id, username, first_name, last_name
        ORDER BY messages DESC
        LIMIT %s
    """, (limit,))
    return rows


@app.get("/api/daily")
async def daily(
    x_api_key: Optional[str] = Header(default=None),
    days: int = Query(default=30, ge=1, le=365),
):
    require_api_key(x_api_key)
    rows = await fetch_all("""
        SELECT DATE(message_date) AS date,
               COUNT(*)::bigint AS messages,
               COUNT(*) FILTER (WHERE deleted)::bigint AS deleted_messages
        FROM public.messages
        WHERE message_date >= CURRENT_DATE - (%s * INTERVAL '1 day')
        GROUP BY DATE(message_date)
        ORDER BY date
    """, (days,))
    return rows
