-- =============================================================
-- P.A.I.M.O.N. — консолидированная схема БД
-- Актуально по состоянию после Этапа A (BRD-выравнивание)
-- Таблицы под заявки/карточки (Этапы D/E) сюда НЕ включены —
-- код, который их использует, пока отключён в main.py.
-- =============================================================

-- ---------- USERS ----------
CREATE TABLE IF NOT EXISTS users (
    id                   SERIAL PRIMARY KEY,
    tg_id                BIGINT NOT NULL UNIQUE,
    tag                  TEXT,
    language             VARCHAR(2) NOT NULL DEFAULT 'RU',
    left_at              TIMESTAMPTZ,
    deletion_warned_at   TIMESTAMPTZ,
    flavor_role_id       INTEGER  -- FK на flavor_roles ниже, добавляется после её создания
);

-- ---------- ЧАТЫ, ГДЕ СОСТОИТ БОТ ----------
CREATE TABLE IF NOT EXISTS chats (
    chat_id   BIGINT PRIMARY KEY,
    title     TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- ---------- ЧЛЕНСТВО ПОЛЬЗОВАТЕЛЕЙ В ЧАТАХ (для автоочистки, Этап 3) ----------
CREATE TABLE IF NOT EXISTS user_chat_memberships (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chat_id    BIGINT NOT NULL,
    is_member  BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, chat_id)
);

-- ---------- РОЛИ (Этап 4) ----------
CREATE TABLE IF NOT EXISTS flavor_roles (
    id   SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

ALTER TABLE users
    ADD CONSTRAINT fk_users_flavor_role
    FOREIGN KEY (flavor_role_id) REFERENCES flavor_roles(id) ON DELETE SET NULL;

INSERT INTO flavor_roles (name) VALUES
    ('Хиличурл'),
    ('Застрельщик Фатуи'),
    ('Стражник Мондштадта'),
    ('Рыцарь Ордо Фавониус'),
    ('Искатель сокровищ'),
    ('Странствующий торговец')
ON CONFLICT (name) DO NOTHING;

-- ---------- ИГРЫ ПОЛЬЗОВАТЕЛЯ (Этап 5) ----------
CREATE TABLE IF NOT EXISTS user_games (
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    game_code TEXT NOT NULL,
    PRIMARY KEY (user_id, game_code)
);

-- ---------- ДНИ РОЖДЕНИЯ ПОЛЬЗОВАТЕЛЕЙ (старая модель — упростится на Этапе D) ----------
CREATE TABLE IF NOT EXISTS birthdays (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chat_id    BIGINT NOT NULL,
    day        SMALLINT NOT NULL CHECK (day BETWEEN 1 AND 31),
    month      SMALLINT NOT NULL CHECK (month BETWEEN 1 AND 12),
    year       SMALLINT,
    PRIMARY KEY (user_id, chat_id)
);

-- =============================================================
-- TAG / CHARACTER, разделены по BRD
-- =============================================================

CREATE TABLE IF NOT EXISTS tag (
    id            SERIAL PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    status        TEXT NOT NULL DEFAULT 'ACTIVE',   -- ACTIVE | DELETED | BLOCKED
    created_by    BIGINT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS tag_alias (
    id     SERIAL PRIMARY KEY,
    tag_id INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
    alias  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS subscription (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tag_id     INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, tag_id)
);

CREATE TABLE IF NOT EXISTS character (
    id            SERIAL PRIMARY KEY,
    owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name          TEXT NOT NULL UNIQUE,
    birth_date    DATE,
    photo_file_id TEXT,
    description   TEXT,
    is_primary    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS one_primary_character_per_user
    ON character (owner_user_id) WHERE is_primary = TRUE;

CREATE TABLE IF NOT EXISTS tag_usage (
    id                   SERIAL PRIMARY KEY,
    tag_id               INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
    telegram_message_id  BIGINT,
    author_tg_id         BIGINT NOT NULL,
    media_type           TEXT,             -- 'photo' | 'video' | ...
    used_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tag_usage_tag_used_at ON tag_usage (tag_id, used_at);