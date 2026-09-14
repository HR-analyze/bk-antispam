"""Кто отвечает и кто поллит.

Бот, проигравший чужому процессу борьбу за токен, выглядит живым: он
отвечает на /health, пишет логи, не падает. Эти тесты закрывают признаки,
по которым дубль вообще можно заметить.
"""

import asyncio
import os
import sys

import pytest

import api
import main as main_module
import runtime


def test_instance_id_names_the_process():
    value = runtime.instance_id()
    host, _, pid = value.partition("/")
    assert host
    assert pid == str(os.getpid())


def test_health_reports_the_instance():
    payload = asyncio.run(api.health())
    assert payload["instance"] == runtime.instance_id()


def test_health_separates_running_from_reachable():
    """bot_running обязан идти от реального getUpdates, а не от факта запуска."""
    runtime.set_bot_state(runtime.CONFLICT)
    try:
        payload = asyncio.run(api.health())
        assert payload["bot_running"] is False
        assert payload["bot_state"] == "conflict"
        # Веб-часть при конфликте здорова, и healthcheck не должен её убивать:
        # иначе платформа устроит рестарт-луп вместо видимой проблемы.
        assert payload["status"] == "ok"
    finally:
        runtime.set_bot_state(runtime.NOT_STARTED)


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF", " 0 "])
def test_run_bot_can_be_switched_off(monkeypatch, value):
    monkeypatch.setenv("RUN_BOT", value)
    assert main_module.bot_enabled() is False


@pytest.mark.parametrize("value", ["", "1", "true", "yes", "anything"])
def test_bot_runs_by_default(monkeypatch, value):
    monkeypatch.setenv("RUN_BOT", value)
    assert main_module.bot_enabled() is True


def test_bot_runs_when_flag_is_absent(monkeypatch):
    monkeypatch.delenv("RUN_BOT", raising=False)
    assert main_module.bot_enabled() is True


def test_web_only_process_never_imports_the_bot(monkeypatch):
    """Смысл RUN_BOT=0 — поднять веб без токена, значит bot не должен импортироваться.

    Проверять отсутствием BOT_TOKEN нельзя: к этому моменту bot уже лежит в
    sys.modules после других тестов, и импорт прошёл бы молча. None в
    sys.modules превращает любой импорт модуля в ImportError, то есть ловит
    обращение, а не его последствия.
    """
    monkeypatch.setenv("RUN_BOT", "0")
    monkeypatch.setitem(sys.modules, "bot", None)

    served = asyncio.Event()

    class FakeServer:
        should_exit = False

        async def serve(self):
            served.set()

    monkeypatch.setattr(main_module, "build_server", FakeServer)
    asyncio.run(main_module.main())
    assert served.is_set()


def test_bot_half_starts_when_the_flag_is_on(monkeypatch):
    """Обратная сторона того же теста: при RUN_BOT=1 поллинг действительно поднимают."""
    monkeypatch.delenv("RUN_BOT", raising=False)
    started = asyncio.Event()

    class FakeServer:
        should_exit = False

        async def serve(self):
            await started.wait()

    async def fake_run_bot():
        started.set()

    monkeypatch.setattr(main_module, "build_server", FakeServer)
    monkeypatch.setattr(main_module, "run_bot", fake_run_bot)
    asyncio.run(main_module.main())
    assert started.is_set()


def test_the_guard_above_would_catch_an_import(monkeypatch):
    """Страховка от теста-пустышки: убеждаемся, что подмена sys.modules ловит импорт."""
    monkeypatch.setitem(sys.modules, "bot", None)
    with pytest.raises(ImportError):
        import bot  # noqa: F401
