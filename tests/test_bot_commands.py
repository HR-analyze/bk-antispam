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


def test_health_reports_whether_the_bot_is_running():
    """Веб-билдер платформы поднимает только ASGI-приложение.

    Бот тогда не стартует вовсе, а домен отвечает — отказ незаметен. /health
    обязан это показывать.
    """
    import asyncio
    import os

    import api

    os.environ.pop(api.BOT_RUNNING_ENV, None)
    assert asyncio.run(api.health())["bot_running"] is False

    os.environ[api.BOT_RUNNING_ENV] = "1"
    try:
        assert asyncio.run(api.health())["bot_running"] is True
    finally:
        os.environ.pop(api.BOT_RUNNING_ENV, None)


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
