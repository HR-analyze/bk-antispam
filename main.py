import asyncio
import os

import uvicorn

from api import app
from bot import main as bot_main


async def run_api() -> None:
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
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
