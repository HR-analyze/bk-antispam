"""Состояние бота, которое показывает /health.

Нужно, чтобы отличить «бот не запущен» от «правила неверны». Отдельный модуль,
а не переменная окружения: состояние богаче булева и живёт в том же процессе,
где работает и API.
"""

import os
import socket

NOT_STARTED = "not_started"   # процесс поднял только веб-часть
STARTING = "starting"         # поллинг запущен, ни одного успешного getUpdates
POLLING = "polling"           # апдейты реально забираются
CONFLICT = "conflict"         # токен держит другой процесс (409)
UNREACHABLE = "unreachable"   # getUpdates не проходит по другой причине
STOPPED = "stopped"           # поллинг завершился

_state = NOT_STARTED


def set_bot_state(value: str) -> None:
    global _state
    _state = value


def bot_state() -> str:
    return _state


def bot_is_polling() -> bool:
    """True только когда getUpdates действительно отработал.

    Сам факт запуска main.py доказательством не является: при конфликте токена
    aiogram бесконечно ретраит getUpdates, ничего не пробрасывая наружу.
    """
    return _state == POLLING


def instance_id() -> str:
    """Кто именно отвечает: hostname процесса и PID.

    В Docker hostname по умолчанию — короткий id контейнера. Поэтому разные
    instance в ответах /health и /version означают, что Telegram обслуживает
    один процесс, а веб-часть отдаёт другой, то есть с одним токеном живут
    два контейнера. Ровно этот случай выглядит как «бот работает, но в логах
    бесконечный 409», и вычислять его иначе приходится по косвенным признакам.
    """
    return f"{socket.gethostname()}/{os.getpid()}"
