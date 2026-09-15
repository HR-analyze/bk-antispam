"""Исключения модерации: разрешённые ссылки и сообщения администрации.

Исключение — самое опасное место в антиспаме: одна неаккуратная проверка
превращает его в щель, через которую проходит всё. Поэтому здесь столько же
тестов на обход, сколько на сам проход.
"""

import asyncio
from datetime import datetime, timezone

import pytest
from aiogram.types import Chat, ChatMemberAdministrator, ChatMemberMember, Message, MessageEntity, User

import bot as bot_module
import moderation as m

ALLOWED = "https://t.me/karavaeviru?direct"


def msg(text="", entities=None, **kwargs):
    return Message(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=Chat(id=-100123, type="supergroup"),
        text=text or None,
        entities=entities,
        **kwargs,
    )


# --- разрешённая ссылка проходит ------------------------------------------

def test_the_requested_link_passes_clean():
    assert m.decide(ALLOWED) == (None, None)


@pytest.mark.parametrize("url", [
    "https://t.me/karavaeviru?direct",
    "https://t.me/karavaeviru",
    "http://t.me/karavaeviru",
    "t.me/karavaeviru",
    "www.t.me/karavaeviru",
    "HTTPS://T.ME/KaravaevIru",
    "https://t.me/karavaeviru/",
    "https://t.me/karavaeviru/128",
    "https://telegram.me/karavaeviru",
])
def test_link_variants_pass(url):
    assert m.decide(url) == (None, None), url


def test_link_with_trailing_punctuation_passes():
    """«Пишите на t.me/karavaeviru.» — точка часть предложения, не адреса."""
    assert m.decide("Пишите нам https://t.me/karavaeviru?direct.") == (None, None)


def test_allowed_link_inside_a_normal_sentence_passes():
    assert m.decide(f"Все вопросы сюда {ALLOWED} спасибо") == (None, None)


# --- обходы не проходят ----------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://t.me/karavaeviruspam",       # приклеенный хвост к имени
    "https://t.me/karavaeviru_fake",
    "https://t.me/spam",                  # другой канал того же домена
    "https://t.me/joinchat/xxxx",
    "https://t.me@evil.com/karavaeviru",  # настоящий хост — evil.com
    "https://evil.com/t.me/karavaeviru",  # имя канала в пути чужого домена
    "https://t.me.evil.com/karavaeviru",  # поддомен-подделка
    "https://karavaeviru.ru",             # тот же бренд, другой домен
])
def test_lookalike_links_are_still_blocked(url):
    assert m.decide(url) == ("link", "link"), url


def test_allowed_link_does_not_smuggle_a_second_link():
    text = f"{ALLOWED} и ещё https://t.me/spamshop"
    assert m.decide(text) == ("link", "link")


def test_allowed_link_does_not_smuggle_spam_text():
    """Главное: исключение снимает вердикт про ссылку, а не всю модерацию."""
    reason, rule = m.decide(f"нужна девочка на выходные {ALLOWED}")
    assert reason == "job_spam"


def test_allowed_link_does_not_smuggle_profanity():
    reason, _ = m.decide(f"{ALLOWED} бляدь")
    assert reason is not None


def test_link_without_an_extractable_address_is_blocked():
    """Так выглядит text_link: в тексте адреса нет, он только в сущности."""
    assert m.decide("смотрите тут", has_link=True) == ("link", "link")


# --- адреса из сущностей Telegram -----------------------------------------

def test_hidden_link_is_taken_from_the_entity():
    """Подпись может быть разрешённой ссылкой, а адрес — чужим."""
    text = "https://t.me/karavaeviru"
    message = msg(text, entities=[
        MessageEntity(type="text_link", offset=0, length=len(text), url="https://evil.com/pay"),
    ])
    links = bot_module.message_links(message, text)
    assert "https://evil.com/pay" in links
    assert m.decide(text, links=links) == ("link", "link")


def test_entity_pointing_at_the_allowed_channel_passes():
    text = "наш канал"
    message = msg(text, entities=[
        MessageEntity(type="text_link", offset=0, length=len(text), url=ALLOWED),
    ])
    links = bot_module.message_links(message, text)
    assert m.decide(text, has_link=True, links=links) == (None, None)


def test_url_entity_address_is_collected():
    text = f"пишите {ALLOWED}"
    message = msg(text, entities=[
        MessageEntity(type="url", offset=8, length=len(ALLOWED)),
    ])
    assert ALLOWED in bot_module.message_links(message, text)


# --- список исключений -----------------------------------------------------

def test_env_adds_to_the_builtin_list(monkeypatch):
    monkeypatch.setenv("ALLOWED_LINKS", "t.me/hr_bk, https://karavaevi.ru/vacancies")
    allowed = m._load_allowed_links()
    assert "t.me/karavaeviru" in allowed          # встроенное не теряется
    assert "t.me/hr_bk" in allowed
    assert "karavaevi.ru/vacancies" in allowed


def test_empty_env_keeps_the_builtin_list(monkeypatch):
    monkeypatch.setenv("ALLOWED_LINKS", "   ")
    assert m._load_allowed_links() == ("t.me/karavaeviru",)


def test_telegram_me_is_the_same_channel():
    """Алиас приводится к одному виду в обе стороны."""
    assert m.normalize_link("https://telegram.me/karavaeviru") == "t.me/karavaeviru"
    assert m.link_is_allowed("https://telegram.me/karavaeviru/7") is True
    # Алиас не открывает других каналов.
    assert m.link_is_allowed("https://telegram.me/spam") is False


def test_bare_domain_in_the_list_does_not_open_everything(monkeypatch):
    """Если в исключения попадёт сам домен — это осознанное решение, не случайное."""
    monkeypatch.setenv("ALLOWED_LINKS", "")
    assert all("/" in item for item in m._load_allowed_links())


# --- сообщения администрации ----------------------------------------------

class FakeBot:
    def __init__(self, status):
        self.status = status

    async def get_chat_member(self, chat_id, user_id):
        if self.status == "admin":
            return ChatMemberAdministrator(
                user=User(id=user_id, is_bot=False, first_name="a"),
                can_be_edited=False, is_anonymous=False, can_manage_chat=True,
                can_delete_messages=True, can_manage_video_chats=True,
                can_restrict_members=True, can_promote_members=False,
                can_change_info=True, can_invite_users=True,
                can_post_stories=False, can_edit_stories=False,
                can_delete_stories=False,
            )
        return ChatMemberMember(user=User(id=user_id, is_bot=False, first_name="u"))


def exempt(message, status="member"):
    return asyncio.run(bot_module.is_exempt_sender(FakeBot(status), message))


def test_admin_is_exempt():
    message = msg("нужна девочка", from_user=User(id=7, is_bot=False, first_name="admin"))
    assert exempt(message, status="admin") is True


def test_regular_member_is_not_exempt():
    message = msg("нужна девочка", from_user=User(id=7, is_bot=False, first_name="user"))
    assert exempt(message, status="member") is False


def test_channel_autoforward_is_exempt():
    """Пост из привязанного канала приходит как автопересылка."""
    message = msg(
        "нужна девочка",
        sender_chat=Chat(id=-100999, type="channel"),
        is_automatic_forward=True,
    )
    assert exempt(message) is True


def test_anonymous_admin_is_exempt():
    """Анонимный админ пишет от имени самой группы."""
    message = msg("нужна девочка", sender_chat=Chat(id=-100123, type="supergroup"))
    assert exempt(message) is True


def test_arbitrary_channel_is_not_exempt():
    """От имени своего канала может писать любой участник — это не администрация."""
    message = msg("нужна девочка", sender_chat=Chat(id=-100777, type="channel"))
    assert exempt(message) is False


def test_message_without_an_author_is_not_exempt():
    assert exempt(msg("нужна девочка")) is False
