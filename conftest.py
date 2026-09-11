"""Пустой conftest в корне добавляет корень проекта в sys.path,
иначе `pytest` не находит moderation.py при вызове без `python -m`.
"""

import os

# bot.py падает на импорте без токена, а его чистые функции надо тестировать.
os.environ.setdefault("BOT_TOKEN", "test-token")
