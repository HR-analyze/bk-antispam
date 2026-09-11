import asyncio
import logging
import os

import uvicorn

from api import app
from bot import main as bot_main


def web_port() -> int:
    """Порт веб-части.

    Платформы называют переменную по-разному (PORT, WEB_PORT), а промах по
    порту выглядит как «домен не отвечает».
    """
    for name in ("PORT", "WEB_PORT", "APP_PORT"):
        value = os.getenv(name, "").strip()
        if value.isdigit():
            return int(value)
    return 8000


async def run_api() -> None:
    port = web_port()
    logging.info("Веб-часть слушает 0.0.0.0:%s", port)
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    await asyncio.gather(
        bot_main(),
        run_api(),
    )


if __name__ == "__main__":
    asyncio.run(main())
