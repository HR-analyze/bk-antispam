# Дашборд BK AntiSpam

Веб-интерфейс к таблице `public.messages`: сколько сообщений пришло, как их
классифицировал бот, что удалено — и раскрытие любого сообщения с полной
детализацией.

**Дашборд работает только на чтение — никаких `INSERT`/`UPDATE`/`DELETE`, схема БД не меняется.**

## Что показывает

- **Плитки**: всего сообщений, удалено (и доля), «пропущено с меткой»
  (классифицировано, но осталось в чате), уникальных авторов, активность за 24 часа.
- **Сообщения по дням** — столбики «оставлено / удалено», с подсказкой при
  наведении и переключателем в таблицу.
- **Классификация** — сколько сообщений в каждой категории (`clean`, `link`,
  `profanity`, `negative`, `spam`, `job_spam`, `flood`) и сколько из них удалено.
  Чистые по умолчанию скрыты (их ~70%, они сплющивают шкалу) — кнопка «показать чистые».
- **Авторы с удалёнными сообщениями** — топ-10 с кнопкой «фильтр».
- **Таблица сообщений** — фильтры по периоду, классификации, статусу и тексту;
  клик по строке раскрывает детализацию: полный текст, `message_id` / `chat_id` /
  `user_id`, время в Telegram и время записи в БД, причина удаления, статистика
  автора, ссылка «открыть в Telegram», копирование JSON.

Фильтры общие: меняешь период — пересчитываются все карточки.

## Два режима подключения

Выбери один, в зависимости от того, видна ли база с твоей ВМ (виртуальной машины).

### A. Прямое подключение к PostgreSQL (по умолчанию)

```env
DATABASE_URL=postgresql://user:password@host:5432/dbname
```

Подходит, если БД принимает подключения снаружи. Лучше завести отдельного
read-only пользователя:

```sql
CREATE USER dashboard_ro WITH PASSWORD 'ЗАМЕНИ';
GRANT CONNECT ON DATABASE ИМЯ_БД TO dashboard_ro;
GRANT USAGE ON SCHEMA public TO dashboard_ro;
GRANT SELECT ON public.messages TO dashboard_ro;
```

### B. Через API бота (`api.py`)

Если база наружу не смотрит, дашборд ходит в HTTP-API бота:

```env
UPSTREAM_API_URL=https://бот.example.ru
UPSTREAM_API_KEY=тот_же_ключ_что_DASHBOARD_API_KEY_у_бота
```

`DATABASE_URL` при этом должен быть пустым. На стороне бота нужен
`DASHBOARD_API_KEY` и обновлённый `api.py` из этого же репозитория — старая
версия игнорирует параметр `days`, и цифры в дашборде поедут.

Оба режима отдают одинаковые данные — запросы синхронизированы.

## Доступ к дашборду

Дашборд показывает переписку, поэтому пароль обязателен:

```env
DASHBOARD_USER=admin
DASHBOARD_PASSWORD=длинный_пароль
```

Без них любой запрос вернёт `503`. Для локальной отладки можно поставить
`DASHBOARD_ALLOW_ANONYMOUS=1` — на публичной ВМ так делать не надо.

## Запуск

### Docker Compose (рекомендуется)

```bash
cd dashboard
cp .env.example .env
nano .env          # заполнить DATABASE_URL и пароль
docker compose up -d --build
curl -s http://127.0.0.1:8080/health
```

Контейнер слушает только `127.0.0.1:8080`. Наружу выставляй через nginx с TLS
(HTTPS-сертификатом), например:

```nginx
server {
    listen 443 ssl;
    server_name dash.example.ru;

    # ssl_certificate / ssl_certificate_key — от certbot

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

### Без Docker

```bash
cd dashboard
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
set -a && source .env && set +a
uvicorn server:app --host 127.0.0.1 --port 8080
```

Systemd-юнит (сервис автозапуска) — `/etc/systemd/system/bk-dashboard.service`:

```ini
[Unit]
Description=BK AntiSpam dashboard
After=network.target

[Service]
WorkingDirectory=/opt/bk-antispam/dashboard
EnvironmentFile=/opt/bk-antispam/dashboard/.env
ExecStart=/opt/bk-antispam/dashboard/.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8080
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now bk-dashboard
journalctl -u bk-dashboard -f     # логи
```

## Переменные окружения

| Переменная | Обязательна | Назначение |
|---|---|---|
| `DATABASE_URL` | режим A | строка подключения к PostgreSQL |
| `UPSTREAM_API_URL` | режим B | базовый URL API бота |
| `UPSTREAM_API_KEY` | режим B | ключ `X-API-Key` для API бота |
| `DASHBOARD_USER` / `DASHBOARD_PASSWORD` | да | Basic-авторизация дашборда |
| `DASHBOARD_ALLOW_ANONYMOUS` | нет | `1` — запуск без пароля (только локально) |
| `DASHBOARD_HOST` / `DASHBOARD_PORT` | нет | адрес и порт (по умолчанию `127.0.0.1:8080`) |
| `CHAT_USERNAME` | нет | публичный `@username` чата для ссылок в Telegram |

## HTTP-эндпоинты

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/` | сам дашборд |
| `GET` | `/health` | проверка живости (без авторизации) |
| `GET` | `/api/stats?days=` | сводные счётчики |
| `GET` | `/api/classifications?days=` | разбивка по классификации |
| `GET` | `/api/daily?days=` | сообщения по дням |
| `GET` | `/api/top-users?limit=&days=` | авторы с удалёнными сообщениями |
| `GET` | `/api/messages?limit=&offset=&classification=&deleted=&user_id=&q=&days=` | список сообщений |
| `GET` | `/api/user-summary?user_id=` | статистика автора |

`classification=clean` возвращает сообщения, где в БД `classification IS NULL`.

## Диагностика

| Симптом | Причина | Что делать |
|---|---|---|
| `503 Dashboard auth is not configured` | не заданы `DASHBOARD_USER`/`DASHBOARD_PASSWORD` | заполнить `.env` и перезапустить |
| `502 Database query failed` | нет доступа к БД или нет прав на `public.messages` | проверить `DATABASE_URL`, firewall, `GRANT SELECT` |
| `502 Upstream API is unreachable` | недоступен API бота | `curl $UPSTREAM_API_URL/health` с ВМ |
| Пустые графики, но сообщения есть | все записи старше выбранного периода | поставить период «Всё время» |
| Цифры расходятся с ботом (режим B) | у бота старый `api.py` | обновить бота из этого репозитория |

Логи: `docker compose logs -f dashboard` или `journalctl -u bk-dashboard -f`.
