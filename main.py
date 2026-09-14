import asyncio
import logging
import os

import uvicorn

from api import app

# Веб-инстанс (RUN_BOT=0) не импортирует bot, а настройку логов до сих пор
# делал именно он. Формат тот же, так что для обычного запуска ничего не
# меняется: повторный basicConfig ничего не переопределяет.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


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


def bot_enabled() -> bool:
    """Поднимать ли поллер в этом процессе (флаг RUN_BOT).

    Поллинг-бот обязан жить в одном экземпляре: два процесса с одним токеном
    дают вечный 409 у проигравшего, и со стороны это выглядит как работающий
    бот. Если платформе понадобится второй инстанс ради веб-части, ему ставят
    RUN_BOT=0, и поллер поднимает только первый.
    """
    value = os.getenv("RUN_BOT", "").strip().lower()
    return value not in {"0", "false", "no", "off"}


async def main() -> None:
    if not bot_enabled():
        # Веб-инстансу токен не нужен, поэтому bot импортируется только здесь:
        # его модуль падает на импорте без BOT_TOKEN.
        logging.warning(
            "RUN_BOT=%s: поллинг выключен, поднимается только веб-часть",
            os.getenv("RUN_BOT", "").strip(),
        )
        await run_api()
        return

    from bot import main as bot_main

    await asyncio.gather(
        bot_main(),
        run_api(),
    )


if __name__ == "__main__":
    asyncio.run(main())
