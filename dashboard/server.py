"""BK AntiSpam dashboard.

Read-only web UI over public.messages. Deployed separately from the bot, so it
supports two data sources:

* DATABASE_URL      - connect to PostgreSQL directly (read-only queries).
* UPSTREAM_API_URL  - proxy the bot's own dashboard API (api.py) instead, for
                      setups where the database is not reachable from the VM
                      that hosts this dashboard.

The dashboard never writes to the database.
"""

import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("dashboard")

STATIC_DIR = Path(__file__).parent / "static"

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
UPSTREAM_API_URL = os.getenv("UPSTREAM_API_URL", "").strip().rstrip("/")
UPSTREAM_API_KEY = os.getenv("UPSTREAM_API_KEY", "").strip()

DASHBOARD_USER = os.getenv("DASHBOARD_USER", "").strip()
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
ALLOW_ANONYMOUS = os.getenv("DASHBOARD_ALLOW_ANONYMOUS", "").strip().lower() in {"1", "true", "yes"}

# Public link to the moderated chat, used to build t.me deep links in the UI.
# For a private supergroup Telegram uses https://t.me/c/<chat_id without -100>/<message_id>.
CHAT_USERNAME = os.getenv("CHAT_USERNAME", "").strip().lstrip("@")

MAX_USER_SUMMARY_ROWS = 1000

security = HTTPBasic(auto_error=False)


# --------------------------------------------------------------------------- auth


def require_auth(credentials: Optional[HTTPBasicCredentials] = Depends(security)) -> None:
    if ALLOW_ANONYMOUS:
        return
    if not DASHBOARD_USER or not DASHBOARD_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Dashboard auth is not configured. Set DASHBOARD_USER and "
                "DASHBOARD_PASSWORD, or set DASHBOARD_ALLOW_ANONYMOUS=1 to run without auth."
            ),
        )
    ok_user = credentials is not None and secrets.compare_digest(credentials.username, DASHBOARD_USER)
    ok_password = credentials is not None and secrets.compare_digest(credentials.password, DASHBOARD_PASSWORD)
    if not (ok_user and ok_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": 'Basic realm="BK AntiSpam dashboard"'},
        )


# --------------------------------------------------------------------------- sources


class Source:
    """Data source interface. Both implementations are read-only."""

    name = "none"

    async def open(self) -> None: ...

    async def close(self) -> None: ...

    async def stats(self, days: Optional[int]) -> dict: ...

    async def classifications(self, days: Optional[int]) -> list: ...

    async def daily(self, days: int) -> list: ...

    async def top_users(self, limit: int, days: Optional[int]) -> list: ...

    async def messages(self, **filters) -> dict: ...

    async def user_summary(self, user_id: int) -> dict: ...


# Messages are stored with classification NULL when the bot found nothing wrong.
# The UI shows that bucket as "clean", so translate it back here.
CLEAN = "clean"

# message_date comes from Telegram and may be missing; created_at always exists.
TS = "COALESCE(message_date, created_at)"

MESSAGE_COLUMNS = """
    id, chat_id, message_id, user_id, username, first_name, last_name,
    text, message_date, reply_to_message_id, classification, deleted,
    delete_reason, created_at
"""


class DatabaseSource(Source):
    name = "database"

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.pool = None

    async def open(self) -> None:
        from psycopg_pool import AsyncConnectionPool

        self.pool = AsyncConnectionPool(self.dsn, min_size=1, max_size=5, open=False)
        await self.pool.open(wait=True, timeout=15)

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()

    async def _fetch(self, sql: str, params: tuple = ()) -> list:
        from psycopg.rows import dict_row

        if self.pool is None:
            raise HTTPException(status_code=503, detail="Database pool is not ready")
        try:
            async with self.pool.connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(sql, params)
                    return await cur.fetchall()
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Query failed")
            raise HTTPException(status_code=502, detail="Database query failed") from exc

    @staticmethod
    def _window(days: Optional[int], params: list) -> str:
        if not days:
            return ""
        params.append(days)
        return f" WHERE {TS} >= NOW() - (%s * INTERVAL '1 day')"

    async def stats(self, days: Optional[int]) -> dict:
        params: list = []
        where = self._window(days, params)
        rows = await self._fetch(f"""
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
        return rows[0] if rows else {}

    async def classifications(self, days: Optional[int]) -> list:
        params: list = []
        where = self._window(days, params)
        return await self._fetch(f"""
            SELECT COALESCE(classification, '{CLEAN}') AS classification,
                   COUNT(*)::bigint AS count,
                   COUNT(*) FILTER (WHERE deleted)::bigint AS deleted_count
            FROM public.messages
            {where}
            GROUP BY COALESCE(classification, '{CLEAN}')
            ORDER BY count DESC
        """, tuple(params))

    async def daily(self, days: int) -> list:
        return await self._fetch(f"""
            SELECT ({TS} AT TIME ZONE 'UTC')::date AS date,
                   COUNT(*)::bigint AS messages,
                   COUNT(*) FILTER (WHERE deleted)::bigint AS deleted_messages
            FROM public.messages
            WHERE {TS} >= NOW() - (%s * INTERVAL '1 day')
            GROUP BY 1
            ORDER BY 1
        """, (days,))

    async def top_users(self, limit: int, days: Optional[int]) -> list:
        params: list = []
        where = self._window(days, params)
        clause = f"{where} AND user_id IS NOT NULL" if where else " WHERE user_id IS NOT NULL"
        params.append(limit)
        return await self._fetch(f"""
            SELECT user_id, username, first_name, last_name,
                   COUNT(*)::bigint AS messages,
                   COUNT(*) FILTER (WHERE deleted)::bigint AS deleted_messages
            FROM public.messages
            {clause}
            GROUP BY user_id, username, first_name, last_name
            ORDER BY deleted_messages DESC, messages DESC
            LIMIT %s
        """, tuple(params))

    @staticmethod
    def _filters(classification, deleted, user_id, q, days) -> tuple[str, list]:
        conditions: list[str] = []
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
        return where, params

    async def messages(self, limit, offset, classification, deleted, user_id, q, days) -> dict:
        where, params = self._filters(classification, deleted, user_id, q, days)
        total_rows = await self._fetch(
            f"SELECT COUNT(*)::bigint AS total FROM public.messages {where}", tuple(params)
        )
        rows = await self._fetch(f"""
            SELECT {MESSAGE_COLUMNS}
            FROM public.messages
            {where}
            ORDER BY {TS} DESC, id DESC
            LIMIT %s OFFSET %s
        """, tuple(params + [limit, offset]))
        return {
            "items": rows,
            "total": total_rows[0]["total"] if total_rows else 0,
            "limit": limit,
            "offset": offset,
        }

    async def user_summary(self, user_id: int) -> dict:
        rows = await self._fetch(f"""
            SELECT COUNT(*)::bigint AS messages,
                   COUNT(*) FILTER (WHERE deleted)::bigint AS deleted_messages,
                   MIN({TS}) AS first_seen,
                   MAX({TS}) AS last_seen
            FROM public.messages
            WHERE user_id = %s
        """, (user_id,))
        return rows[0] if rows else {}


class UpstreamSource(Source):
    """Proxy the bot's api.py. Used when the database is not reachable here."""

    name = "upstream"

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.client = None

    async def open(self) -> None:
        import httpx

        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=20.0,
            headers={"X-API-Key": self.api_key} if self.api_key else {},
        )

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> Any:
        if self.client is None:
            raise HTTPException(status_code=503, detail="Upstream client is not ready")
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            response = await self.client.get(path, params=clean)
        except Exception as exc:
            logger.exception("Upstream request failed: %s", path)
            raise HTTPException(status_code=502, detail="Upstream API is unreachable") from exc
        if response.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"Upstream API returned {response.status_code}",
            )
        return response.json()

    async def stats(self, days: Optional[int]) -> dict:
        return await self._get("/api/stats", {"days": days})

    async def classifications(self, days: Optional[int]) -> list:
        return await self._get("/api/classifications", {"days": days})

    async def daily(self, days: int) -> list:
        return await self._get("/api/daily", {"days": days})

    async def top_users(self, limit: int, days: Optional[int]) -> list:
        return await self._get("/api/top-users", {"limit": limit, "days": days})

    async def messages(self, limit, offset, classification, deleted, user_id, q, days) -> dict:
        payload = await self._get("/api/messages", {
            "limit": limit, "offset": offset, "classification": classification,
            "deleted": deleted, "user_id": user_id, "q": q, "days": days,
        })
        payload.setdefault("limit", limit)
        payload.setdefault("offset", offset)
        # Older bot deployments do not report a total; the UI falls back to
        # "next page exists if the page came back full".
        payload.setdefault("total", None)
        return payload

    async def user_summary(self, user_id: int) -> dict:
        payload = await self.messages(
            limit=MAX_USER_SUMMARY_ROWS, offset=0, classification=None,
            deleted=None, user_id=user_id, q=None, days=None,
        )
        items = payload.get("items") or []
        dates = [i.get("message_date") or i.get("created_at") for i in items]
        dates = sorted(d for d in dates if d)
        return {
            "messages": payload.get("total") or len(items),
            "deleted_messages": sum(1 for i in items if i.get("deleted")),
            "first_seen": dates[0] if dates else None,
            "last_seen": dates[-1] if dates else None,
            "truncated": len(items) >= MAX_USER_SUMMARY_ROWS,
        }


def build_source() -> Source:
    if DATABASE_URL:
        return DatabaseSource(DATABASE_URL)
    if UPSTREAM_API_URL:
        return UpstreamSource(UPSTREAM_API_URL, UPSTREAM_API_KEY)
    raise RuntimeError("Set DATABASE_URL (direct mode) or UPSTREAM_API_URL (proxy mode)")


# --------------------------------------------------------------------------- app


source: Source = build_source()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await source.open()
    logger.info("Dashboard source: %s", source.name)
    if ALLOW_ANONYMOUS:
        logger.warning("DASHBOARD_ALLOW_ANONYMOUS is on: the dashboard is served without a password")
    try:
        yield
    finally:
        await source.close()


app = FastAPI(title="BK AntiSpam Dashboard", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "source": source.name,
        "auth": "anonymous" if ALLOW_ANONYMOUS else ("configured" if DASHBOARD_USER else "missing"),
    }


@app.get("/api/config", dependencies=[Depends(require_auth)])
async def config() -> dict:
    return {"source": source.name, "chat_username": CHAT_USERNAME}


@app.get("/api/stats", dependencies=[Depends(require_auth)])
async def stats(days: Optional[int] = Query(default=None, ge=1, le=3650)) -> dict:
    return await source.stats(days)


@app.get("/api/classifications", dependencies=[Depends(require_auth)])
async def classifications(days: Optional[int] = Query(default=None, ge=1, le=3650)) -> list:
    return await source.classifications(days)


@app.get("/api/daily", dependencies=[Depends(require_auth)])
async def daily(days: int = Query(default=30, ge=1, le=365)) -> list:
    return await source.daily(days)


@app.get("/api/top-users", dependencies=[Depends(require_auth)])
async def top_users(
    limit: int = Query(default=10, ge=1, le=100),
    days: Optional[int] = Query(default=None, ge=1, le=3650),
) -> list:
    return await source.top_users(limit, days)


@app.get("/api/messages", dependencies=[Depends(require_auth)])
async def messages(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    classification: Optional[str] = Query(default=None, max_length=50),
    deleted: Optional[bool] = None,
    user_id: Optional[int] = None,
    q: Optional[str] = Query(default=None, max_length=500),
    days: Optional[int] = Query(default=None, ge=1, le=3650),
) -> dict:
    return await source.messages(
        limit=limit, offset=offset, classification=classification,
        deleted=deleted, user_id=user_id, q=q, days=days,
    )


@app.get("/api/user-summary", dependencies=[Depends(require_auth)])
async def user_summary(user_id: int) -> dict:
    return await source.user_summary(user_id)


@app.get("/", dependencies=[Depends(require_auth)])
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    uvicorn.run(
        app,
        host=os.getenv("DASHBOARD_HOST", "127.0.0.1"),
        port=int(os.getenv("DASHBOARD_PORT", "8080")),
    )
