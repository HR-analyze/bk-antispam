"""Схлопывание повторяющихся строк лога.

Когда токен держит другой процесс, aiogram ретраит getUpdates вечно и пишет
две строки каждые ~5 секунд (max_delay бэкоффа), то есть около 17 тысяч строк
в сутки. Настоящие ошибки в таком потоке не видно, а на аварию это не похоже:
процесс жив и «просто работает».

Фильтр пропускает первую строку сразу, дальше не чаще раза в окно, и в
пропущенной строке дописывает, сколько повторов было проглочено.
"""

import logging
import time
from collections.abc import Mapping
from typing import Callable, Optional, Tuple

DEFAULT_WINDOW_SECONDS = 300.0

# Логгер, который ведёт цикл поллинга aiogram: и «Failed to fetch updates»,
# и «Sleep for ... and try again» приходят отсюда.
POLLING_LOGGER = "aiogram.dispatcher"

_Key = Tuple[str, int, str, Optional[str]]


def _record_key(record: logging.LogRecord) -> _Key:
    """Ключ схлопывания — шаблон сообщения, а не готовый текст.

    Аргументы у ретраев меняются каждый раз (задержка, номер попытки), так что
    по отформатированному тексту одинаковых строк не бывает вовсе. Зато первый
    строковый аргумент у aiogram несёт тип ошибки — его в ключ включаем, иначе
    смена TelegramConflictError на сетевую ошибку осталась бы незамеченной.
    """
    args = record.args
    first = None
    if isinstance(args, tuple) and args and isinstance(args[0], str):
        first = args[0]
    return (record.name, record.levelno, str(record.msg), first)


def _annotate(record: logging.LogRecord, suppressed: int, elapsed: float) -> None:
    """Дописывает, сколько повторов проглочено за паузу.

    Без этого подавление неотличимо от пропажи: по логу не понять, конфликт
    кончился или фильтр съел строки.
    """
    if not isinstance(record.msg, str) or isinstance(record.args, Mapping):
        # %(name)s-форматирование ломается от дописанных позиционных полей.
        return
    record.msg = record.msg + " [подавлено повторов: %d за %.0f c]"
    record.args = tuple(record.args or ()) + (suppressed, elapsed)


class RepeatThrottleFilter(logging.Filter):
    """Пропускает одинаковые записи не чаще раза в окно.

    Ключ строится по шаблону сообщения, поэтому фильтр не завязан на точные
    формулировки aiogram и переживает её обновление: незнакомая строка просто
    получит свой ключ и пройдёт.
    """

    def __init__(
        self,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self._window = window_seconds
        self._clock = clock
        # Ключей ровно столько, сколько разных шаблонов, — расти неоткуда.
        self._seen: dict[_Key, Tuple[float, int]] = {}

    def filter(self, record: logging.LogRecord) -> bool:
        if self._window <= 0:
            return True
        key = _record_key(record)
        now = self._clock()
        seen = self._seen.get(key)
        if seen is not None:
            last, suppressed = seen
            if now - last < self._window:
                self._seen[key] = (last, suppressed + 1)
                return False
            if suppressed:
                _annotate(record, suppressed, now - last)
        self._seen[key] = (now, 0)
        return True


def install(
    logger_name: str = POLLING_LOGGER,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
) -> RepeatThrottleFilter:
    """Вешает фильтр на конкретный логгер.

    Именно на логгер, а не на handler: фильтры логгера применяются только к его
    собственным записям, так что глушится ровно цикл поллинга, а не весь вывод.
    """
    throttle = RepeatThrottleFilter(window_seconds)
    logging.getLogger(logger_name).addFilter(throttle)
    return throttle
