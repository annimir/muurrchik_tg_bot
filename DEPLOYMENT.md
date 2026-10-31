# План развёртывания P.A.I.M.O.N. на удалённом сервере

Документ описывает развёртывание текущего проекта с Docker Compose, PostgreSQL,
приватным GitHub-репозиторием, CI и публикацией образов в GHCR. Цель — постоянная
работа бота, контролируемые авторелизы, резервное копирование и возможность отката.

## 1. Целевая архитектура

На сервере работают два контейнера:

- `bot` — образ из `ghcr.io/annimir/muurrchik_tg_bot`;
- `postgres` — PostgreSQL 16 с постоянным Docker volume.

Telegram-бот использует polling, поэтому:

- входящие подключения к боту не нужны;
- порты `80` и `443` открывать не требуется;
- PostgreSQL не должен быть доступен из интернета;
- боту нужны только исходящие HTTPS-подключения к Telegram API.

Для администрирования используется SSH, желательно через Tailscale или с
ограничением по IP.

## 2. Выбор сервера

Рекомендуемая минимальная конфигурация:

- Ubuntu Server 24.04 LTS;
- 1–2 vCPU;
- 2 GB RAM;
- 40 GB SSD;
- KVM-виртуализация;
- постоянный публичный IP;
- резервное копирование диска у провайдера — желательно, но не вместо отдельных
  backup PostgreSQL.

Для текущего бота этого достаточно с запасом. На первом этапе не использовать
сервер для других production-проектов.

## 3. Базовая настройка ОС

После создания сервера:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y ca-certificates curl gnupg ufw fail2ban unattended-upgrades
```

Настроить:

- автоматические security-обновления;
- корректный часовой пояс и синхронизацию времени;
- Fail2ban для SSH;
- firewall;
- отключение ненужных сервисов.

Для бота задать `Europe/Moscow`, поскольку фоновые задачи используют московское
время:

```bash
sudo timedatectl set-timezone Europe/Moscow
```

## 4. Удалённое подключение администратора

### Пользователи

Не работать постоянно под `root`.

Создать две учётные записи:

- `ops` — администратор с `sudo`;
- `deploy` — отдельная учётная запись для GitHub Actions и публикации релизов.

```bash
sudo adduser ops
sudo usermod -aG sudo ops
sudo adduser deploy
```

У `deploy` не должно быть неограниченного `sudo`.

### SSH-ключи

На компьютере администратора создать отдельный ключ:

```bash
ssh-keygen -t ed25519 -a 100
```

Публичный ключ добавить в:

```text
/home/ops/.ssh/authorized_keys
```

Приватный ключ никуда не отправлять.

Для `deploy` создать отдельный ключ: его приватная часть будет храниться в
GitHub Secrets.

Проверить вход под `ops` в новом терминале и только после этого отключить
парольный вход:

```text
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
```

Перед перезапуском SSH оставить открытой текущую рабочую сессию, чтобы не
потерять доступ.

### Firewall

Если у администратора постоянный IP:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from ADMIN_IP to any port 22 proto tcp
sudo ufw enable
```

Если IP динамический, предпочтительнее Tailscale:

- установить Tailscale на сервер и устройства администратора;
- разрешить SSH только через Tailscale;
- не открывать публичный SSH или ограничить его отдельными доверенными адресами.

Не публиковать `5432`, `80`, `443` и другие порты без необходимости.

## 5. Установка Docker

Установить Docker Engine и Compose Plugin по официальной инструкции Docker для
Ubuntu.

Затем:

```bash
sudo systemctl enable --now docker
sudo usermod -aG docker deploy
```

Группа `docker` фактически даёт права уровня root. Поэтому:

- ключ `deploy` используется только для релизов;
- личный `ops` и CI-ключ должны быть разными;
- нельзя передавать CI-ключ посторонним;
- при компрометации ключа его нужно сразу удалить с сервера и из GitHub Secrets.

Проверка:

```bash
docker version
docker compose version
```

## 6. Структура проекта и секреты

Разместить production-файлы в:

```text
/opt/paimon/
├── compose.prod.yml
├── .env
├── config.prod.yml
├── logs/
└── backups/
```

`config.prod.yml` создаётся на основе `config/config.example.yml` и содержит:

- Telegram bot token;
- параметры PostgreSQL;
- Telegram ID первого администратора.

В `.env` вынести:

```text
POSTGRES_DB=bot_db
POSTGRES_USER=bot_user
POSTGRES_PASSWORD=сильный_уникальный_пароль
IMAGE=ghcr.io/annimir/muurrchik_tg_bot
IMAGE_TAG=...
```

Права:

```bash
sudo chmod 600 /opt/paimon/.env /opt/paimon/config.prod.yml
```

Не добавлять эти файлы в Git. При доступе к BotFather старый Telegram-токен
рекомендуется перевыпустить перед запуском на новом сервере.

## 7. Production Compose

На сервере не должно быть `build: .`: используется готовый образ из GHCR.

Пример `compose.prod.yml` без реальных секретов:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    env_file: .env
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 10
    logging:
      options:
        max-size: "20m"
        max-file: "5"

  bot:
    image: ${IMAGE}:${IMAGE_TAG}
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      APP_ENV: prod
      TZ: Europe/Moscow
    volumes:
      - ./config.prod.yml:/app/config.prod.yml:ro
      - ./logs:/app/logs
    logging:
      options:
        max-size: "20m"
        max-file: "5"

volumes:
  pgdata:
```

Важно:

- у PostgreSQL полностью отсутствует секция `ports`;
- volume `pgdata` нельзя удалять;
- `down -v` в production запрещён;
- контейнеры автоматически поднимаются после перезагрузки через
  `restart: unless-stopped` и автозапуск Docker.

Дополнительно добавить healthcheck для bot-контейнера: проверку соединения с
PostgreSQL и работоспособности процесса.

## 8. Перенос текущей базы на сервер

Существующая PostgreSQL-база находится в локальном Docker volume и сама на
сервер не перенесётся.

Порядок:

1. Остановить bot-контейнер на текущей машине.
2. Сделать `pg_dump`.
3. Передать dump по SCP/SFTP на сервер.
4. Поднять на сервере только PostgreSQL.
5. Восстановить dump.
6. Сверить количество пользователей, тегов и подписок.
7. Запустить бота на сервере.
8. Проверить команды.
9. Только после этого окончательно остановить старое окружение.

После успешного восстановления временные dump-файлы на сервере удалить или
переместить в защищённое backup-хранилище.

## 9. Доступ сервера к GHCR

Поскольку репозиторий приватный, настроить на сервере `docker login ghcr.io`.

Использовать отдельный GitHub token только с правом чтения пакетов:

- не использовать основной пароль GitHub;
- не давать токену права на запись в репозиторий;
- хранить Docker credentials только на сервере с ограниченными правами.

Проверка:

```bash
docker pull ghcr.io/annimir/muurrchik_tg_bot:latest
```

## 10. Резервное копирование

Настроить ежедневный backup PostgreSQL через `systemd timer`.

Политика хранения:

- 7 ежедневных копий;
- 4 еженедельные;
- 6 ежемесячных.

Копии должны находиться не только на сервере:

- S3-совместимое хранилище;
- отдельный backup-сервер;
- Restic/Borg с шифрованием — предпочтительный вариант.

Также сохранять:

- `config.prod.yml`;
- `.env`;
- `compose.prod.yml`.

Эти файлы содержат секреты, поэтому backup должен шифроваться и не должен
попадать в GitHub.

Раз в месяц выполнять тестовое восстановление в отдельную PostgreSQL. Backup без
проверки восстановления нельзя считать полностью надёжным.

## 11. Авторелизы

Текущий процесс:

1. Pull request запускает CI.
2. Выполняются тесты на PostgreSQL.
3. Проверяется Docker-сборка.
4. После успешного CI в `master` CD публикует образ в GHCR.

Следующий шаг — добавить deployment-job после публикации.

Рекомендуемая последовательность:

1. CI успешно завершён.
2. Образ опубликован.
3. Deployment-job получает точный digest образа.
4. По SSH подключается как `deploy`.
5. Сохраняет предыдущий digest для отката.
6. Выполняет `docker compose pull`.
7. Запускает `docker compose up -d --remove-orphans`.
8. Проверяет healthcheck и логи.
9. При ошибке возвращает предыдущий образ.

Для production использовать digest `@sha256:...`, а не только `latest`. Это
гарантирует, что на сервер попадёт именно протестированная версия.

В GitHub Secrets добавить:

- `DEPLOY_HOST`;
- `DEPLOY_USER`;
- `DEPLOY_SSH_KEY`;
- `DEPLOY_PORT`;
- `DEPLOY_KNOWN_HOSTS`.

Добавить `concurrency` для production, чтобы два merge не разворачивались
одновременно.

Пока защита `master` недоступна из-за тарифа, рекомендуется ручное подтверждение
production deployment. После перехода на GitHub Pro включить обязательные PR,
review и status checks.

## 12. Миграции и откат

Перед каждым релизом с изменением схемы:

- автоматически создавать новый `pg_dump`;
- применять миграции отдельным контролируемым шагом;
- не выполнять разрушающие миграции вместе с запуском нового кода.

Откат приложения:

- вернуть предыдущий digest образа;
- выполнить `docker compose up -d`;
- проверить healthcheck.

Откат базы — отдельная операция. Не восстанавливать старый dump автоматически
после любого failed deployment: это может удалить новые данные. Предпочтительны
обратно совместимые expand/contract-миграции.

## 13. Мониторинг и уведомления

Настроить:

- heartbeat-проверку раз в 1–5 минут;
- уведомление в Telegram или на почту, если бот/PostgreSQL недоступны;
- контроль свободного места;
- контроль ошибок в `errors.log`;
- контроль успешности backup;
- уведомление о failed deployment.

Проверка должна учитывать не только состояние `Up`, но и:

- доступность PostgreSQL;
- успешный `getMe` к Telegram;
- отсутствие повторяющихся `Conflict: terminated by other getUpdates request`.

## 14. Порядок запуска

1. Купить сервер и настроить Ubuntu.
2. Настроить `ops`, SSH-ключи, firewall и Fail2ban.
3. Установить Docker.
4. Подготовить `compose.prod.yml` и секреты.
5. Настроить доступ к GHCR.
6. Перенести PostgreSQL.
7. Запустить бота вручную и проверить команды.
8. Настроить backup и проверить восстановление.
9. Настроить мониторинг.
10. Добавить deployment в GitHub Actions.
11. Проверить авторелиз на безопасном изменении.
12. Проверить откат на предыдущий digest.
13. Перезагрузить сервер и убедиться, что всё поднимается автоматически.

Критерий готовности: после перезагрузки бот сам возвращается в работу,
PostgreSQL недоступен извне, релизы проходят через CI, есть актуальные внешние
backup и проверенный откат.
