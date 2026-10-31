# P.A.I.M.O.N. — Telegram-бот
 
Бот для группового чата: система тегов/подписок на фото- и видео-публикации,
ролевые карточки персонажей, профиль пользователя, дни рождения, автоочистка
неактивных участников. Архитектура следует документу **"P.A.I.M.O.N. — Единый
документ бизнес-требований и моделей"** (BRD), составленному вместе с
администратором чата.
 
Разработка велась поэтапно; полная история решений и обоснований — в
`PROGRESS.md` (первый раунд: базовый функционал) и `PROGRESS_V2.md`
(второй раунд: выравнивание под BRD). Этот README — снимок текущего
состояния, а не журнал разработки.
 
## Стек
 
- Python 3.12, [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
- PostgreSQL (через `psycopg2`, без ORM — прямой SQL в `database/queries.py`)
- Docker / docker-compose для развёртывания
- `rapidfuzz` — нечёткое сравнение имён тегов
## Быстрый старт
 
```bash
cp config/config.example.yml config/config.dev.yml  # затем заполнить конфигурацию
docker compose up -d --build
```

Не используйте `docker compose down -v` на окружении с нужными данными: флаг `-v`
удаляет volume PostgreSQL.
 
`database/database_structure.sql` применяется автоматически при старте бота
(`db.execute_file(...)` в `database/queries.py`) — вручную накатывать схему
не нужно.
 
### Конфигурация

Скопируйте пример и заполните его локально:

```bash
cp config/config.example.yml config/config.dev.yml
```

`config/config.dev.yml` и `config/config.prod.yml` содержат секреты, игнорируются
Git и не копируются в Docker-образ. В контейнер конфигурация попадает через mount
из `docker-compose.yml`; окружение переключается через `APP_ENV`.

```yaml
telegram:
  bot_token: "REPLACE_WITH_TELEGRAM_BOT_TOKEN"

postgres:
  host: "postgres"
  port: 5432
  dbname: "bot_db"
  user: "bot_user"
  password: "REPLACE_WITH_POSTGRES_PASSWORD"

admin:
  user_id: 123456789  # tg_id первого администратора — используется только
                       # для начального заполнения таблицы admins, если она
                       # пуста; дальше администраторов добавляют командой
```

PostgreSQL доступен с хоста только через `127.0.0.1:5432`; из других машин по
сети подключиться к нему нельзя.
 
## Архитектура
 
### Слои
 
- **`handlers/`** — по одному файлу на функциональную область, каждый хендлер
  тонкий: валидация ввода → вызов `database/queries.py` → локализованный ответ.
- **`database/queries.py`** — единственное место, где есть SQL. Все функции
  принимают `tg_id` (Telegram ID), а не внутренний `users.id`, кроме случаев,
  где `user_id` уже явно из другого запроса (например, работа с персонажами).
- **`services/`** — переиспользуемая логика без прямого доступа к Telegram API:
  `tag_storage.py` (нечёткий поиск тегов), `admin.py` (`is_admin`),
  `flavor_roles.py`, `games.py`, `request_broadcast.py` (рассылка заявок
  нескольким админам и синхронизация копий уведомлений).
- **`message/`** — вся текстовая логика вынесена из кода: `keys.py` (константы
  ключей), `loader.py` (`message(lang, key, section, *args)`),
  `translations/messages_{ru,en}.properties`.
### Данные
 
- **`TAG`** — сущность подписки/упоминания на фото и видео. Жизненный цикл
  `ACTIVE → DELETED/BLOCKED → ACTIVE` (восстановление разрешено). Публикация
  поддерживает несколько тегов в одном сообщении — уведомляются подписчики
  каждого найденного тега.
- **`CHARACTER`** — ролевая персона, `owner_user_id`, до 3 на пользователя
  (1 основной + 2 доп.), имя глобально уникально и неизменяемо после
  создания. Создаётся **только** через заявку (`/newcharacter`), не
  администратором напрямую.
- **`SUBSCRIPTION`** — soft-delete через `active`-флаг, а не удаление строки:
  история подписок сохраняется, повторная подписка реактивирует запись.
- **`USER_CARD`** — публичный профиль (пока одно поле — `bio`), меняется
  через заявку. Фото карточки — всегда фото основного персонажа, отдельного
  поля нет.
- **Заявки** (`character_requests`, `card_requests`) — упрощённая модель
  (без пофайлового `NEEDS_EDIT`): `pending → approved/rejected`, админ либо
  принимает, либо правит поля сам и принимает, либо отклоняет.
### Мульти-админы и очередь заявок
 
Администраторы хранятся в таблице `admins`, управляются командами
(`/add_admin`, `/remove_admin`, `/list_admins`), а не в конфиге. Новая заявка
рассылается **всем** администраторам одновременно; любой может взять её в
работу (`🖐 Взять в работу`) — после этого approve/edit/reject доступны
только взявшему, у остальных копия уведомления сворачивается в короткую
сводку. `/pendingrequests` и `/myclaimedrequests` — единая очередь для обоих
типов заявок.
 
## Команды
 
### Пользователь (группа)
`/sub <тег>`, `/unsub <тег>`, `/unsuball`, `/mysub`, `/addtag <имя> <алиас>`,
`/tag <теги>`, `/tagstats <тег>`, `/updateme`, `/setbirthday ДД.ММ`,
`/mybirthday`, `/deletebirthday`, `/mygames`, `/setprimary`, `/all`, `/rename`
 
### Пользователь (группа или личка)
`/newcharacter`, `/editcharacter`, `/mycharrequests`, `/card [@nickname]`,
`/editcard`, `/mycardrequest`, `/language <RU|EN>`
 
### Администратор (личка)
`/delete_tag`, `/block_tag`, `/restore_tag`, `/add_role`, `/remove_role`,
`/list_roles`, `/reroll_role`, `/backfill_cards`, `/set_primary_character`,
`/add_admin`, `/remove_admin`, `/list_admins`, `/pendingrequests`,
`/myclaimedrequests`, `/admin_birthdays`
 
Заявки на персонажей и карточки рассматриваются кнопками под уведомлением,
а не отдельными командами.
 
## Известные ограничения и техдолг

- **Автоочистка неактивных (6 мес.)**: пользователи, вступившие до внедрения
  трекинга членства, не имеют записи в `user_chat_memberships` — могут ложно
  попасть под отсчёт при выходе из чата. Само-исправляется по мере активности.
- **`view_characters.py`** (просмотр карточки конкретного персонажа отдельно
  от `/card`) не переписан после Этапа A архитектурного выравнивания — не
  подключён к боту.
- **"Пересказ" (SUM-01 из BRD)** — сводка обсуждений топика за 24 часа —
  сознательно не реализован в этом раунде. Требует отключения Telegram
  Privacy Mode, лога сообщений чата и интеграции с LLM — отдельный раунд.

## Разработка

- Каждое новое пользовательское сообщение — через `message/`, не хардкодить
  текст в хендлерах.
- Логирование — `logging`, не `print`; `logger.info` на значимые действия
  пользователей и админов, `logger.warning`/`error` на аномалии и сбои.
- Перед изменением схемы сделайте резервную копию и добавьте миграцию. Не
  пересоздавайте volume PostgreSQL с рабочими данными.

### Тесты

```bash
python -m unittest discover -s tests -v
```

Без `TEST_POSTGRES_DSN` выполняются unit-тесты, а интеграционные пропускаются.
Для полного набора укажите DSN отдельной тестовой PostgreSQL:

```bash
export TEST_POSTGRES_DSN='host=localhost port=5432 dbname=test_bot user=test_user password=test_password'
python -m unittest discover -s tests -v
```

Тесты очищают указанную базу перед каждым сценарием, поэтому нельзя использовать
рабочую PostgreSQL.

### CI/CD

- `.github/workflows/ci.yml` запускает все тесты на PostgreSQL и Docker-сборку
  для pull request и push в `master`/`main`.
- `.github/workflows/cd.yml` после успешного CI публикует образ в GHCR с тегами
  `latest` и `sha-<commit>`; ручной запуск доступен через **Run workflow**.
- В настройках ветки `master` на GitHub включите защиту через pull request и
  обязательные проверки **Unit and integration tests** и **Docker build**.

Автоматического развёртывания на сервер нет: CD формирует версионированный
образ, который можно безопасно забрать из GHCR и развернуть штатным способом.