-- =============================================================
-- P.A.I.M.O.N. — консолидированная схема БД
-- =============================================================

-- ---------- USERS ----------
CREATE TABLE IF NOT EXISTS users (
    id                   SERIAL PRIMARY KEY,
    tg_id                BIGINT NOT NULL UNIQUE,
    tag                  TEXT,
    language             VARCHAR(2) NOT NULL DEFAULT 'RU',
    left_at              TIMESTAMPTZ,
    deletion_warned_at   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS user_titles (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS user_titles_unique_name
    ON user_titles (user_id, lower(name));

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

CREATE INDEX IF NOT EXISTS tag_active_name_lower_prefix_idx
    ON tag (lower(name) text_pattern_ops)
    WHERE status = 'ACTIVE';

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
    ('hi3', 'Honkai Impact 3rd'),
    ('wuthering_waves', 'Wuthering Waves')
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

DROP INDEX IF EXISTS one_holder_per_position;

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
ALTER TABLE character ADD COLUMN IF NOT EXISTS wiki_url TEXT;

CREATE TABLE IF NOT EXISTS character_affiliation (
    character_id   INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
    affiliation_id INTEGER NOT NULL REFERENCES affiliations(id) ON DELETE CASCADE,
    PRIMARY KEY (character_id, affiliation_id)
);

CREATE INDEX IF NOT EXISTS idx_character_affiliation_affiliation
    ON character_affiliation (affiliation_id);

INSERT INTO character_affiliation (character_id, affiliation_id)
SELECT id, affiliation_id FROM character WHERE affiliation_id IS NOT NULL
ON CONFLICT (character_id, affiliation_id) DO NOTHING;

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

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS idx_users_tag_trgm ON users USING gin (tag gin_trgm_ops);

ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_file_id TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_updated_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS chat_position TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS lock_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE character ADD COLUMN IF NOT EXISTS lock_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE users ADD COLUMN IF NOT EXISTS titles TEXT;

INSERT INTO user_titles (user_id, name)
SELECT u.id, trim(title)
FROM users u
CROSS JOIN LATERAL regexp_split_to_table(u.titles, E'\\n|,') AS title
WHERE u.titles IS NOT NULL AND trim(title) <> ''
ON CONFLICT DO NOTHING;

ALTER TABLE users DROP COLUMN IF EXISTS titles;
ALTER TABLE users DROP COLUMN IF EXISTS flavor_role_id;
DROP TABLE IF EXISTS flavor_roles;

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

CREATE TABLE IF NOT EXISTS game_modes (
    id          SERIAL PRIMARY KEY,
    game_code   TEXT NOT NULL REFERENCES games(code) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (game_code, name)
);

CREATE TABLE IF NOT EXISTS helper_profiles (
    user_id      INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    is_paused    BOOLEAN NOT NULL DEFAULT FALSE,
    dm_available BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS helper_modes (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mode_id     INTEGER NOT NULL REFERENCES game_modes(id) ON DELETE CASCADE,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, mode_id)
);

CREATE TABLE IF NOT EXISTS help_requests (
    id                  SERIAL PRIMARY KEY,
    requester_user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mode_id             INTEGER NOT NULL REFERENCES game_modes(id),
    chat_id             BIGINT NOT NULL,
    message_thread_id   BIGINT,
    status              TEXT NOT NULL DEFAULT 'OPEN',
    assigned_helper_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    scheduled_for       TIMESTAMPTZ,
    request_message_id  BIGINT,
    expires_at          TIMESTAMPTZ,
    lock_version        INTEGER NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at        TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS help_request_offers (
    id                  SERIAL PRIMARY KEY,
    request_id          INTEGER NOT NULL REFERENCES help_requests(id) ON DELETE CASCADE,
    helper_user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status              TEXT NOT NULL DEFAULT 'PENDING',
    telegram_message_id BIGINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    responded_at        TIMESTAMPTZ,
    UNIQUE (request_id, helper_user_id)
);

CREATE INDEX IF NOT EXISTS idx_helper_modes_mode_active
    ON helper_modes (mode_id) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_help_requests_status_created
    ON help_requests (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_help_requests_requester_status
    ON help_requests (requester_user_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_help_request_per_mode
    ON help_requests (requester_user_id, mode_id)
    WHERE status IN ('OPEN', 'SCHEDULING', 'CONFIRMING', 'ASSIGNED');
CREATE INDEX IF NOT EXISTS idx_help_request_offers_helper_status
    ON help_request_offers (helper_user_id, status);

INSERT INTO game_modes (game_code, name) VALUES
    ('genshin', 'Театр воображариума'),
    ('genshin', 'Витая бездна'),
    ('genshin', 'Мрачный натиск')
ON CONFLICT (game_code, name) DO NOTHING;

CREATE TABLE IF NOT EXISTS wish_events (
    id              SERIAL PRIMARY KEY,
    period          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'ACTIVE',
    pull_allowance  INTEGER NOT NULL DEFAULT 300,
    reset_from_id   INTEGER REFERENCES wish_events(id) ON DELETE SET NULL,
    created_by      BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_wish_event
    ON wish_events (status) WHERE status = 'ACTIVE';

CREATE TABLE IF NOT EXISTS wish_banners (
    id          SERIAL PRIMARY KEY,
    event_id    INTEGER NOT NULL REFERENCES wish_events(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (event_id, name)
);

CREATE TABLE IF NOT EXISTS wish_items (
    id          SERIAL PRIMARY KEY,
    banner_id   INTEGER NOT NULL REFERENCES wish_banners(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    rarity      SMALLINT NOT NULL CHECK (rarity IN (3, 4, 5)),
    item_type   TEXT NOT NULL CHECK (item_type IN ('character', 'weapon')),
    featured    BOOLEAN NOT NULL DEFAULT FALSE,
    image_url   TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (banner_id, name)
);

CREATE TABLE IF NOT EXISTS wish_participants (
    event_id                INTEGER NOT NULL REFERENCES wish_events(id) ON DELETE CASCADE,
    user_id                 INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    remaining               INTEGER NOT NULL,
    pity5                   INTEGER NOT NULL DEFAULT 0,
    pity4                   INTEGER NOT NULL DEFAULT 0,
    featured5_guaranteed    BOOLEAN NOT NULL DEFAULT FALSE,
    featured4_guaranteed    BOOLEAN NOT NULL DEFAULT FALSE,
    radiance_streak         INTEGER NOT NULL DEFAULT 0,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id, user_id)
);

CREATE TABLE IF NOT EXISTS wish_drops (
    id              BIGSERIAL PRIMARY KEY,
    event_id        INTEGER NOT NULL REFERENCES wish_events(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    banner_id       INTEGER REFERENCES wish_banners(id) ON DELETE SET NULL,
    item_name       TEXT NOT NULL,
    rarity          SMALLINT NOT NULL,
    item_type       TEXT NOT NULL,
    featured        BOOLEAN NOT NULL DEFAULT FALSE,
    radiant         BOOLEAN NOT NULL DEFAULT FALSE,
    pull_number     INTEGER NOT NULL,
    pity5_at        INTEGER NOT NULL,
    pity4_at        INTEGER NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (event_id, user_id, pull_number)
);

CREATE INDEX IF NOT EXISTS idx_wish_drops_event_user ON wish_drops (event_id, user_id, id);

CREATE TABLE IF NOT EXISTS wish_winners (
    event_id    INTEGER NOT NULL REFERENCES wish_events(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('LUCKIEST', 'UNLUCKIEST')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id, kind)
);