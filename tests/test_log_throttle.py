"""Проверка схлопывания повторов в логе.

Смысл фильтра — не «меньше строк», а «настоящие ошибки видно». Поэтому тесты
следят и за тем, что глушится поток ретраев, и за тем, что смена причины
ошибки или восстановление связи проходят наружу сразу.
"""

import logging

import pytest

import log_throttle


class Clock:
    """Управляемое время: тест не должен ждать реальные секунды."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def record(msg: str, *args, level: int = logging.ERROR, name: str = "aiogram.dispatcher"):
    return logging.LogRecord(name, level, __file__, 1, msg, args or None, None)


# Настоящие шаблоны из цикла поллинга aiogram: первый несёт тип ошибки,
# второй — задержку и номер попытки, которые меняются на каждой итерации.
FETCH_FAILED = "Failed to fetch updates - %s: %s"
SLEEP_AND_RETRY = "Sleep for %f seconds and try again... (tryings = %d, bot id = %d)"


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def throttle(clock):
    return log_throttle.RepeatThrottleFilter(window_seconds=300.0, clock=clock)


def test_first_record_passes(throttle):
    assert throttle.filter(record(FETCH_FAILED, "TelegramConflictError", "Conflict"))


def test_repeat_inside_window_is_dropped(throttle):
    args = ("TelegramConflictError", "Conflict: terminated by other getUpdates request")
    assert throttle.filter(record(FETCH_FAILED, *args))
    assert not throttle.filter(record(FETCH_FAILED, *args))


def test_changing_arguments_do_not_defeat_the_filter(throttle, clock):
    """Задержка и счётчик попыток меняются каждый раз — ключ на них не смотрит."""
    passed = 0
    for i in range(1, 61):
        clock.advance(5.0)
        if throttle.filter(record(SLEEP_AND_RETRY, 5.0 + i / 100, i, 8809610306, level=logging.WARNING)):
            passed += 1
    # 60 попыток по 5 секунд — это 300 секунд, ровно одно окно.
    assert passed == 1


def test_record_after_window_passes_and_reports_the_gap(throttle, clock):
    args = ("TelegramConflictError", "Conflict")
    throttle.filter(record(FETCH_FAILED, *args))
    for _ in range(41):
        clock.advance(5.0)
        throttle.filter(record(FETCH_FAILED, *args))

    clock.advance(300.0)
    passed = record(FETCH_FAILED, *args)
    assert throttle.filter(passed)
    text = passed.getMessage()
    assert "TelegramConflictError" in text
    assert "подавлено повторов: 41" in text


def test_other_error_type_is_not_swallowed(throttle):
    """Конфликт сменился сетевой ошибкой — это новость, её надо показать."""
    assert throttle.filter(record(FETCH_FAILED, "TelegramConflictError", "Conflict"))
    assert throttle.filter(record(FETCH_FAILED, "TelegramNetworkError", "timeout"))


def test_recovery_message_passes_immediately(throttle):
    """«Connection established» приходит после сотен ретраев и не должен ждать окна."""
    for _ in range(10):
        throttle.filter(record(FETCH_FAILED, "TelegramConflictError", "Conflict"))
    established = record(
        "Connection established (tryings = %d, bot id = %d)",
        42,
        8809610306,
        level=logging.INFO,
    )
    assert throttle.filter(established)


def test_zero_window_disables_throttling(clock):
    off = log_throttle.RepeatThrottleFilter(window_seconds=0, clock=clock)
    args = ("TelegramConflictError", "Conflict")
    assert all(off.filter(record(FETCH_FAILED, *args)) for _ in range(5))


def test_mapping_args_are_not_corrupted(throttle, clock):
    """У %(name)s-форматирования нет позиционных полей — дописывать в него нельзя."""
    def mapping_record():
        return logging.LogRecord(
            "aiogram.dispatcher", logging.ERROR, __file__, 1,
            # logging разворачивает одиночный словарь в args сам.
            "failed for %(bot)s", ({"bot": 8809610306},), None,
        )

    assert throttle.filter(mapping_record())
    assert not throttle.filter(mapping_record())
    clock.advance(301.0)
    passed = mapping_record()
    assert throttle.filter(passed)
    assert passed.getMessage() == "failed for 8809610306"


def test_install_only_touches_the_named_logger(clock):
    """Фильтр вешается на логгер поллинга, остальной вывод не трогает."""
    log_throttle.install("test.throttle.scope", window_seconds=300.0)
    target = logging.getLogger("test.throttle.scope")
    other = logging.getLogger("test.throttle.other")
    try:
        args = ("TelegramConflictError", "Conflict")
        assert target.filter(record(FETCH_FAILED, *args, name="test.throttle.scope"))
        assert not target.filter(record(FETCH_FAILED, *args, name="test.throttle.scope"))
        # Соседний логгер фильтра не знает и пропускает всё.
        assert other.filter(record(FETCH_FAILED, *args, name="test.throttle.other"))
        assert other.filter(record(FETCH_FAILED, *args, name="test.throttle.other"))
    finally:
        target.filters.clear()


def test_polling_logger_name_matches_aiogram():
    """Если aiogram переедет на другой логгер, фильтр молча перестанет работать."""
    from aiogram import loggers

    assert loggers.dispatcher.name == log_throttle.POLLING_LOGGER
