"""Проверка проводки команд через настоящий диспетчер aiogram.

Тесты правил проверяют, что классификатор думает. Здесь проверяется, что
команда вообще доходит до обработчика и что он отвечает: живой бот может
отвечать на /start и молчать на /check, и это уже не про правила.
"""

import asyncio
from datetime import datetime, timezone

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.types import Chat, ChatMemberMember, Message, Update, User

import bot as bot_module


class RecordingSession(BaseSession):
    """Сессия, которая ничего не шлёт в Telegram, но запоминает вызовы."""

    def __init__(self):
        super().__init__()
        self.calls = []

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        name = type(method).__name__
        self.calls.append((name, getattr(method, "text", None)))
        if name == "GetChatMember":
            return ChatMemberMember(user=User(id=1, is_bot=False, first_name="u"))
        return Message(
            message_id=1,
            date=datetime.now(timezone.utc),
            chat=Chat(id=1, type="private"),
        )

    async def stream_content(self, *args, **kwargs):
        yield b""


def make_update(text: str, chat_type: str = "private") -> Update:
    return Update(
        update_id=1,
        message=Message(
            message_id=100,
            date=datetime.now(timezone.utc),
            chat=Chat(id=777, type=chat_type),
            from_user=User(id=451042054, is_bot=False, first_name="Ilya"),
            text=text,
            entities=[
                {"type": "bot_command", "offset": 0, "length": len(text.split()[0])}
            ],
        ),
    )


# Router прикрепляется к Dispatcher ровно один раз за процесс, поэтому
# диспетчер общий для всех тестов файла.
_DISPATCHER = Dispatcher()
_DISPATCHER.include_router(bot_module.router)


def feed(text: str, chat_type: str = "private") -> RecordingSession:
    async def run():
        session = RecordingSession()
        telegram_bot = Bot("123:AAA", session=session)
        await _DISPATCHER.feed_update(telegram_bot, make_update(text, chat_type))
        return session

    return asyncio.run(run())


def replies(session: RecordingSession) -> list[str]:
    return [text or "" for name, text in session.calls if name == "SendMessage"]


def test_start_answers():
    assert replies(feed("/start")), "/start остался без ответа"


def test_check_answers_in_private_with_the_verdict():
    """Если живой бот отвечает на /start и молчит на /check — код старее этой версии."""
    answers = replies(feed("/check нужна девочка"))
    assert len(answers) == 1
    assert "УДАЛИЛ БЫ" in answers[0]
    assert "gender_fallback" in answers[0]


def test_check_without_arguments_explains_usage():
    answers = replies(feed("/check"))
    assert answers and "/check" in answers[0]


def test_check_is_silent_for_a_non_admin_in_a_group():
    """В клиентском чате командой не должен пользоваться кто попало."""
    session = feed("/check нужна девочка", chat_type="supergroup")
    assert replies(session) == []
    assert any(name == "GetChatMember" for name, _ in session.calls)


@pytest.mark.parametrize("command", ["/start", "/ping", "/chat_id", "/version"])
def test_every_documented_command_answers(command):
    assert replies(feed(command)), f"{command} остался без ответа"


def test_health_reports_whether_the_bot_is_polling():
    """Веб-билдер платформы поднимает только ASGI-приложение.

    Бот тогда не стартует вовсе, а домен отвечает — отказ незаметен. /health
    обязан это показывать.
    """
    import asyncio

    import api
    import runtime

    previous = runtime.bot_state()
    try:
        runtime.set_bot_state(runtime.NOT_STARTED)
        health = asyncio.run(api.health())
        assert health["bot_running"] is False
        assert health["bot_state"] == "not_started"

        runtime.set_bot_state(runtime.POLLING)
        assert asyncio.run(api.health())["bot_running"] is True
    finally:
        runtime.set_bot_state(previous)


@pytest.mark.parametrize(
    "state,running",
    [("not_started", False), ("starting", False), ("polling", True),
     ("conflict", False), ("unreachable", False), ("stopped", False)],
)
def test_only_successful_polling_counts_as_running(state, running):
    """Запуск процесса — не доказательство работы.

    При конфликте токена aiogram ретраит getUpdates бесконечно и наружу ничего
    не пробрасывает, поэтому «entrypoint вызван» означать «бот работает» не может.
    """
    import runtime

    previous = runtime.bot_state()
    try:
        runtime.set_bot_state(state)
        assert runtime.bot_is_polling() is running
    finally:
        runtime.set_bot_state(previous)


def test_polling_state_follows_getupdates_outcomes():
    """Состояние ведётся от самих вызовов getUpdates, а не от факта старта."""
    import asyncio

    from aiogram.exceptions import TelegramConflictError
    from aiogram.methods import GetMe, GetUpdates

    import bot as bot_module
    import runtime

    class Outcome(BaseSession):
        def __init__(self, error=None):
            super().__init__()
            self.error = error

        async def close(self):
            pass

        async def make_request(self, bot, method, timeout=None):
            if self.error and isinstance(method, GetUpdates):
                raise self.error
            if isinstance(method, GetUpdates):
                return []
            return User(id=1, is_bot=True, first_name="b", username="b")

        async def stream_content(self, *args, **kwargs):
            yield b""

    async def run(session):
        telegram_bot = Bot("1:AAA", session=session)
        bot_module.track_polling(telegram_bot)
        await telegram_bot(GetMe())          # не должен трогать состояние
        state_after_getme = runtime.bot_state()
        try:
            await telegram_bot(GetUpdates(timeout=0))
        except Exception:
            pass
        return state_after_getme, runtime.bot_state()

    previous = runtime.bot_state()
    try:
        runtime.set_bot_state(runtime.STARTING)
        after_getme, after = asyncio.run(run(Outcome()))
        assert after_getme == "starting", "getMe не должен объявлять бота рабочим"
        assert after == "polling"

        runtime.set_bot_state(runtime.POLLING)
        _, after = asyncio.run(run(Outcome(
            TelegramConflictError(method=GetUpdates(), message="terminated by other")
        )))
        assert after == "conflict", "конфликт токена обязан сбрасывать bot_running"

        runtime.set_bot_state(runtime.POLLING)
        _, after = asyncio.run(run(Outcome(RuntimeError("network"))))
        assert after == "unreachable"
    finally:
        runtime.set_bot_state(previous)


@pytest.mark.parametrize(
    "env,expected",
    [({}, 8000), ({"PORT": "8080"}, 8080), ({"WEB_PORT": "3000"}, 3000),
     ({"PORT": "не число"}, 8000)],
)
def test_web_port_reads_the_usual_platform_variables(env, expected, monkeypatch):
    import main

    for name in ("PORT", "WEB_PORT", "APP_PORT"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert main.web_port() == expected
