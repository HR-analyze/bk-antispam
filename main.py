import asyncio
import logging
import os
import signal
from contextlib import suppress

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


class Server(uvicorn.Server):
    """uvicorn, который не трогает сигналы.

    asyncio держит ровно один обработчик на сигнал: add_signal_handler затирает
    предыдущий. Пока uvicorn и aiogram ставили свои наперегонки, SIGTERM доходил
    только до того, кто зарегистрировался последним, а второй компонент о
    завершении не узнавал вовсе. Побеждала aiogram (её start_polling стартует
    после init_db и get_me, то есть позже), поэтому поллинг останавливался, а
    веб-часть продолжала слушать порт и процесс висел до SIGKILL. Сигналами в
    этом процессе распоряжается только main().
    """

    def install_signal_handlers(self) -> None:
        return None


def build_server() -> Server:
    port = web_port()
    logging.info("Веб-часть слушает 0.0.0.0:%s", port)
    return Server(uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info"))


def bot_enabled() -> bool:
    """Поднимать ли поллер в этом процессе (флаг RUN_BOT).

    Поллинг-бот обязан жить в одном экземпляре: два процесса с одним токеном
    дают вечный 409 у проигравшего, и со стороны это выглядит как работающий
    бот. Если платформе понадобится второй инстанс ради веб-части, ему ставят
    RUN_BOT=0, и поллер поднимает только первый.
    """
    value = os.getenv("RUN_BOT", "").strip().lower()
    return value not in {"0", "false", "no", "off"}


async def run_bot() -> None:
    """Поллинг без собственной обработки сигналов — её ведёт main()."""
    # Веб-инстансу токен не нужен, поэтому bot импортируется только здесь:
    # его модуль падает на импорте без BOT_TOKEN.
    from bot import main as bot_main

    try:
        await bot_main(handle_signals=False)
    except asyncio.CancelledError:
        # Отмена — это штатная остановка по сигналу, а не сбой.
        logging.info("Поллинг остановлен")


def install_shutdown(server: Server, tasks: list[asyncio.Task]) -> None:
    """Единственный обработчик SIGTERM/SIGINT в процессе.

    Гасит обе половины сразу: веб-часть выходит штатно через should_exit,
    поллинг снимается отменой задачи. Контейнер, который не выходит по SIGTERM,
    доживает до SIGKILL и всё это время держит соединения с БД, а на платформе
    выглядит как затянувшийся деплой.
    """
    loop = asyncio.get_running_loop()
    # Платформы шлют SIGTERM, а через таймаут добивают SIGKILL; бывает и повтор
    # сигнала. Останавливаемся один раз, чтобы в логе не двоилось.
    stopping = False

    def shutdown(sig: signal.Signals) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        logging.info("Получен %s, останавливаюсь", sig.name)
        server.should_exit = True
        for task in tasks:
            if task.get_name() == "bot":
                task.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        # На Windows add_signal_handler не поддерживается.
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, shutdown, sig)


async def main() -> None:
    server = build_server()
    tasks = [asyncio.create_task(server.serve(), name="api")]

    if bot_enabled():
        tasks.append(asyncio.create_task(run_bot(), name="bot"))
    else:
        logging.warning(
            "RUN_BOT=%s: поллинг выключен, поднимается только веб-часть",
            os.getenv("RUN_BOT", "").strip(),
        )

    install_shutdown(server, tasks)
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
