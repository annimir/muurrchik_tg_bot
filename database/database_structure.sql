-- =============================================================
-- P.A.I.M.O.N. — консолидированная схема БД
-- =============================================================

-- ---------- РОЛИ ----------
CREATE TABLE IF NOT EXISTS flavor_roles (
    id   SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);


INSERT INTO flavor_roles (name) VALUES
    ('Хиличурл'),
    ('Застрельщик Фатуи'),
    ('Стражник Мондштадта'),
    ('Рыцарь Ордо Фавониус'),
    ('Искатель сокровищ'),
    ('Странствующий торговец')
ON CONFLICT (name) DO NOTHING;

-- ---------- USERS ----------
CREATE TABLE IF NOT EXISTS users (
    id                   SERIAL PRIMARY KEY,
    tg_id                BIGINT NOT NULL UNIQUE,
    tag                  TEXT,
    language             VARCHAR(2) NOT NULL DEFAULT 'RU',
    left_at              TIMESTAMPTZ,
    deletion_warned_at   TIMESTAMPTZ,
    flavor_role_id       INTEGER
        REFERENCES flavor_roles(id)
        ON DELETE SET NULL
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



-- ---------- ИГРЫ ПОЛЬЗОВАТЕЛЯ (Этап 5) ----------
CREATE TABLE IF NOT EXISTS user_games (
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    game_code TEXT NOT NULL,
    PRIMARY KEY (user_id, game_code)
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

CREATE TABLE IF NOT EXISTS character_requests (
    id             SERIAL PRIMARY KEY,
    request_type   TEXT NOT NULL DEFAULT 'create',   -- 'create' | 'edit'
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    character_id   INTEGER REFERENCES character(id) ON DELETE CASCADE,  -- NULL для 'create', заполнено для 'edit'
    chat_id        BIGINT NOT NULL,
    name           TEXT,             -- используется только для 'create' — имя неизменяемо после создания (CHAR-04)
    birth_date     DATE,
    description    TEXT,
    photo_file_id  TEXT,
    status         TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS birthdays (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    day     SMALLINT NOT NULL CHECK (day BETWEEN 1 AND 31),
    month   SMALLINT NOT NULL CHECK (month BETWEEN 1 AND 12),
    year    SMALLINT
);

CREATE TABLE IF NOT EXISTS user_card (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    bio     TEXT
);

CREATE TABLE IF NOT EXISTS card_requests (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chat_id     BIGINT NOT NULL,
    bio         TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS admins (
    tg_id BIGINT PRIMARY KEY
);

ALTER TABLE character_requests ADD COLUMN IF NOT EXISTS claimed_by BIGINT;
ALTER TABLE character_requests ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;
ALTER TABLE character_requests ADD COLUMN IF NOT EXISTS requester_display_name TEXT;
ALTER TABLE character_requests ADD COLUMN IF NOT EXISTS requester_username TEXT;

ALTER TABLE card_requests ADD COLUMN IF NOT EXISTS claimed_by BIGINT;
ALTER TABLE card_requests ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;
ALTER TABLE card_requests ADD COLUMN IF NOT EXISTS requester_display_name TEXT;
ALTER TABLE card_requests ADD COLUMN IF NOT EXISTS requester_username TEXT;

CREATE TABLE IF NOT EXISTS request_notifications (
    id           SERIAL PRIMARY KEY,
    request_type TEXT NOT NULL,   -- 'character' | 'card'
    request_id   INTEGER NOT NULL,
    admin_tg_id  BIGINT NOT NULL,
    message_id   BIGINT NOT NULL,
    UNIQUE (request_type, request_id, admin_tg_id)
);

CREATE TABLE IF NOT EXISTS games (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

INSERT INTO games (code, name) VALUES
    ('genshin', 'Genshin Impact'),
    ('hsr', 'Honkai: Star Rail'),
    ('zzz', 'Zenless Zone Zero'),
    ('endfield', 'Arknights: Endfield'),
    ('hi3', 'Honkai Impact 3rd')
ON CONFLICT (code) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_user_games_game_code'
          AND conrelid = 'user_games'::regclass
    ) THEN
        ALTER TABLE user_games
            ADD CONSTRAINT fk_user_games_game_code
            FOREIGN KEY (game_code)
            REFERENCES games(code)
            ON DELETE CASCADE;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS positions (
    id   SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

ALTER TABLE character ADD COLUMN IF NOT EXISTS position_id INTEGER REFERENCES positions(id) ON DELETE SET NULL;

-- гарантия "один держатель на должность одновременно" — та же техника,
-- что и с is_primary в Этапе D (частичный уникальный индекс)
CREATE UNIQUE INDEX IF NOT EXISTS one_holder_per_position
    ON character (position_id) WHERE position_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS affiliations (
    id        SERIAL PRIMARY KEY,
    parent_id INTEGER REFERENCES affiliations(id) ON DELETE CASCADE,
    name      TEXT NOT NULL
);

-- уникальность имени в рамках одного уровня дерева, а не глобально —
-- Postgres не считает NULL равным NULL в обычном UNIQUE, поэтому для
-- корневых узлов (parent_id IS NULL) нужен отдельный частичный индекс
CREATE UNIQUE INDEX IF NOT EXISTS affiliations_unique_root ON affiliations (name) WHERE parent_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS affiliations_unique_child ON affiliations (parent_id, name) WHERE parent_id IS NOT NULL;

ALTER TABLE character ADD COLUMN IF NOT EXISTS affiliation_id INTEGER REFERENCES affiliations(id) ON DELETE SET NULL;

ALTER TABLE flavor_roles ADD COLUMN IF NOT EXISTS photo_file_id TEXT;
ALTER TABLE flavor_roles ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE flavor_roles ADD COLUMN IF NOT EXISTS wiki_url TEXT;

CREATE TABLE IF NOT EXISTS youtube_publications (
    id                  SERIAL PRIMARY KEY,
    video_id            TEXT NOT NULL UNIQUE,
    kind                TEXT NOT NULL CHECK (kind IN ('video', 'shorts')),
    title               TEXT,
    url                 TEXT NOT NULL,
    published_at        TIMESTAMPTZ,
    chat_id             BIGINT NOT NULL,
    telegram_message_id BIGINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_youtube_publications_published_at
    ON youtube_publications (published_at DESC);

CREATE TABLE IF NOT EXISTS youtube_api_usage (
    id          SERIAL PRIMARY KEY,
    operation   TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_youtube_api_usage_created_at
    ON youtube_api_usage (created_at);

ALTER TABLE tag_usage ADD COLUMN IF NOT EXISTS chat_id BIGINT;
ALTER TABLE tag_usage ADD COLUMN IF NOT EXISTS message_thread_id BIGINT;
ALTER TABLE tag_usage ADD COLUMN IF NOT EXISTS media_file_id TEXT;
ALTER TABLE tag_usage ADD COLUMN IF NOT EXISTS media_file_unique_id TEXT;
ALTER TABLE tag_usage ADD COLUMN IF NOT EXISTS media_url TEXT;
ALTER TABLE tag_usage ADD COLUMN IF NOT EXISTS caption TEXT;
ALTER TABLE tag_usage ADD COLUMN IF NOT EXISTS is_public BOOLEAN NOT NULL DEFAULT TRUE;

CREATE INDEX IF NOT EXISTS idx_tag_usage_used_at ON tag_usage (used_at DESC);
CREATE INDEX IF NOT EXISTS idx_tag_usage_public_media
    ON tag_usage (used_at DESC) WHERE is_public = TRUE;

CREATE TABLE IF NOT EXISTS admin_audit_log (
    id          SERIAL PRIMARY KEY,
    admin_tg_id BIGINT NOT NULL,
    action      TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id   TEXT,
    details     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_log_created_at
    ON admin_audit_log (created_at DESC);