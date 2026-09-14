"""Завершение процесса по сигналу.

asyncio держит один обработчик на сигнал: add_signal_handler затирает
предыдущий. uvicorn и aiogram ставят свои независимо, поэтому без владельца
сигналов SIGTERM доходит только до одного из них — вторая половина продолжает
работать, и контейнер висит до SIGKILL. На платформе это выглядит как
затянувшийся деплой, а старый процесс всё это время держит соединения с БД.
"""

import asyncio
import signal

import pytest

import main as main_module


class FakeServer:
    def __init__(self):
        self.should_exit = False


def capture_handlers(monkeypatch, server, tasks):
    """Ставит обработчики и возвращает то, что реально зарегистрировано в loop."""
    registered = {}

    async def run():
        loop = asyncio.get_running_loop()
        real = loop.add_signal_handler

        def spy(sig, callback, *args):
            registered[sig] = (callback, args)
            return real(sig, callback, *args)

        monkeypatch.setattr(loop, "add_signal_handler", spy)
        main_module.install_shutdown(server, tasks)

    asyncio.run(run())
    return registered


def test_shutdown_is_installed_for_both_signals(monkeypatch):
    registered = capture_handlers(monkeypatch, FakeServer(), [])
    assert set(registered) == {signal.SIGTERM, signal.SIGINT}


def test_signal_stops_the_web_half_too(monkeypatch):
    """Без этого uvicorn не узнаёт о SIGTERM и процесс не выходит."""
    server = FakeServer()
    registered = capture_handlers(monkeypatch, server, [])

    callback, args = registered[signal.SIGTERM]
    callback(*args)
    assert server.should_exit is True


def test_signal_cancels_the_polling_task(monkeypatch):
    cancelled = []

    class FakeTask:
        def __init__(self, name):
            self._name = name

        def get_name(self):
            return self._name

        def cancel(self):
            cancelled.append(self._name)

    tasks = [FakeTask("api"), FakeTask("bot")]
    registered = capture_handlers(monkeypatch, FakeServer(), tasks)

    callback, args = registered[signal.SIGTERM]
    callback(*args)
    # Веб-часть выходит штатно через should_exit, отменяют только поллинг.
    assert cancelled == ["bot"]


def test_repeated_signal_stops_once(monkeypatch, caplog):
    """SIGTERM может прийти дважды, а следом SIGKILL — в логе это не должно двоиться."""
    registered = capture_handlers(monkeypatch, FakeServer(), [])
    callback, args = registered[signal.SIGTERM]

    with caplog.at_level("INFO"):
        callback(*args)
        callback(*args)
    assert sum("останавливаюсь" in r.message for r in caplog.records) == 1


def test_uvicorn_subclass_does_not_touch_signals():
    """Вся суть: сигналами распоряжается main(), а не uvicorn."""
    server = main_module.Server.__new__(main_module.Server)
    assert server.install_signal_handlers() is None


def test_server_still_is_a_uvicorn_server():
    import uvicorn

    assert issubclass(main_module.Server, uvicorn.Server)


def test_cancelled_polling_is_not_an_error(monkeypatch):
    """Отмена поллинга — штатная остановка, наружу она подниматься не должна."""
    async def cancelled_bot(handle_signals=True):
        raise asyncio.CancelledError

    import types
    fake = types.ModuleType("bot")
    fake.main = cancelled_bot
    monkeypatch.setitem(__import__("sys").modules, "bot", fake)

    asyncio.run(main_module.run_bot())


@pytest.mark.parametrize("raw,expected", [("", 0.0), ("5", 5.0), ("2.5", 2.5), ("-3", 0.0), ("ой", 0.0)])
def test_start_delay_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("BOT_START_DELAY", raw)
    import bot as bot_module

    assert bot_module.start_delay_seconds() == expected
