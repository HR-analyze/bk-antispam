#!/usr/bin/env python3
"""Диагностика Telegram-стороны бота.

Классификатор покрыт тестами (python -m pytest), поэтому если правильные
сообщения не удаляются, причина почти всегда здесь: бот не видит чат, не имеет
права удалять, смотрит не в тот чат или вообще не получает апдейты.

Запуск на сервере, там где лежит .env:

    python tools/diagnose.py

Только чтение: ничего не удаляет, не пишет и не забирает апдейты у
работающего бота.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID_RAW = os.getenv("CHAT_ID", "").strip()

OK, BAD, WARN, INFO = "  ОК   ", " ПРОБЛЕМА", " ВНИМАНИЕ", "  инфо "
problems: list[str] = []


def say(mark: str, text: str) -> None:
    print(f"[{mark}] {text}")


def fail(text: str, fix: str) -> None:
    say(BAD, text)
    problems.append(fix)


# Переопределяется для локального Bot API сервера и для тестов.
API_BASE = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")


def api(method: str, **params):
    url = f"{API_BASE}/bot{TOKEN}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            return json.load(exc)
        except Exception:
            return {"ok": False, "description": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "description": str(exc)}


def summary() -> int:
    print()
    print("=" * 72)
    if problems:
        print(f"Нашлось проблем: {len(problems)}\n")
        for i, fix in enumerate(problems, 1):
            print(f"  {i}. {fix}")
        print("\nЕсли всё это исправлено, а сообщения всё равно остаются — смотри логи:")
    else:
        print("Telegram-сторона настроена верно.\n")
        print("Значит дело в самом процессе. Смотри логи бота:")
    print('  docker logs <контейнер> 2>&1 | grep -E "MODERATION INPUT|CLASSIFY|SKIPPED|Failed to delete"')
    print()
    print("  нет строк вообще        -> бот не получает апдейты (или запущен старый образ)")
    print("  есть INPUT, нет CLASSIFY -> сообщение отсечено по CHAT_ID (смотри строку SKIPPED)")
    print("  CLASSIFY ... reason=None -> дырка в правилах, добавь кейс в tests/test_moderation.py")
    print("  Failed to delete         -> нет прав, либо автор сам админ (админов бот удалять не может)")
    print("=" * 72)
    return 1 if problems else 0


def main() -> int:
    print("=" * 72)
    print("Диагностика BK AntiSpam")
    print("=" * 72)

    if not TOKEN:
        say(BAD, "BOT_TOKEN не задан — проверять нечего")
        return 1

    # 1. Токен живой?
    me = api("getMe")
    if not me.get("ok"):
        fail(f"getMe не отвечает: {me.get('description')}",
             "Проверь BOT_TOKEN — он неверный или отозван в @BotFather")
        return summary()
    bot = me["result"]
    say(OK, f"бот @{bot.get('username')} (id {bot['id']})")

    # 2. Вебхук отбирает апдейты у long polling.
    hook = api("getWebhookInfo")
    if hook.get("ok"):
        info = hook["result"]
        if info.get("url"):
            fail(f"установлен вебхук {info['url']} — long polling НЕ получает апдейты",
                 "Сними вебхук: curl -s \"https://api.telegram.org/bot<TOKEN>/deleteWebhook\"")
        else:
            say(OK, "вебхук не установлен, long polling свободен")
        pending = info.get("pending_update_count", 0)
        if pending:
            say(WARN, f"в очереди {pending} необработанных апдейтов — похоже, бот не читает их")
        if info.get("last_error_message"):
            say(WARN, f"последняя ошибка доставки: {info['last_error_message']}")

    # 3. CHAT_ID задан?
    if not CHAT_ID_RAW:
        say(WARN, "CHAT_ID пуст — бот модерирует ЛЮБОЙ чат, куда его добавили")
        problems.append("Укажи CHAT_ID группы обсуждений: добавь бота в группу и вызови /chat_id")
        return summary()
    try:
        chat_id = int(CHAT_ID_RAW)
    except ValueError:
        fail(f"CHAT_ID={CHAT_ID_RAW!r} — не число",
             "CHAT_ID должен быть целым, например -1001234567890")
        return summary()
    say(INFO, f"CHAT_ID={chat_id}")

    # 4. Тот ли это чат?
    chat = api("getChat", chat_id=chat_id)
    if not chat.get("ok"):
        fail(f"getChat не отвечает: {chat.get('description')}",
             "Бот не состоит в этом чате или CHAT_ID неверный. "
             "Добавь бота в группу обсуждений и возьми id из команды /chat_id")
        return summary()
    target = chat["result"]
    kind = target.get("type")
    say(OK, f"чат найден: {target.get('title')!r}, тип {kind}")

    if kind == "channel":
        linked = target.get("linked_chat_id")
        fail("CHAT_ID указывает на КАНАЛ, а комментарии живут в группе обсуждений",
             f"Поставь CHAT_ID={linked}" if linked
             else "Найди id группы обсуждений: добавь бота туда и вызови /chat_id")
    elif kind not in {"group", "supergroup"}:
        say(WARN, f"неожиданный тип чата {kind} — ожидалась группа обсуждений")

    # 5. Права на удаление.
    member = api("getChatMember", chat_id=chat_id, user_id=bot["id"])
    if not member.get("ok"):
        fail(f"getChatMember не отвечает: {member.get('description')}",
             "Бот не участник чата — добавь его в группу обсуждений")
    else:
        status = member["result"].get("status")
        if status != "administrator":
            fail(f"бот в чате со статусом {status!r}, а не администратор",
                 "Выдай боту права администратора: без них он не видит все "
                 "сообщения и не может их удалять")
        else:
            say(OK, "бот — администратор")
            if member["result"].get("can_delete_messages"):
                say(OK, "право can_delete_messages выдано")
            else:
                fail("у бота НЕТ права can_delete_messages",
                     "Включи «Удаление сообщений» в правах администратора бота")

    return summary()


if __name__ == "__main__":
    sys.exit(main())
