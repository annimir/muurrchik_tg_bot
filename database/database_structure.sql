CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    tg_id BIGINT NOT NULL UNIQUE,
    tag TEXT
);

CREATE TABLE IF NOT EXISTS character (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE IF NOT EXISTS subscriptions (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, character_id)
);

CREATE TABLE IF NOT EXISTS birthdays (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chat_id    BIGINT NOT NULL,
    day        SMALLINT NOT NULL CHECK (day BETWEEN 1 AND 31),
    month      SMALLINT NOT NULL CHECK (month BETWEEN 1 AND 12),
    year       SMALLINT,
    PRIMARY KEY (user_id, chat_id)
);

CREATE TABLE IF NOT EXISTS chats (
    chat_id   BIGINT PRIMARY KEY,
    title     TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS language VARCHAR(2) NOT NULL DEFAULT 'RU';

-- расширяем character
ALTER TABLE character ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE character ADD COLUMN IF NOT EXISTS affiliation TEXT;
ALTER TABLE character ADD COLUMN IF NOT EXISTS position TEXT;
ALTER TABLE character ADD COLUMN IF NOT EXISTS photo_file_id TEXT;      -- фото, загруженное через бота
ALTER TABLE character ADD COLUMN IF NOT EXISTS photo_url TEXT;          -- фото из таблицы (внешняя ссылка)
ALTER TABLE character ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'bot';  -- 'bot' | 'sheet'
ALTER TABLE character ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE character ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- привязка персонажа к пользователю (админ назначает/отменяет), максимум 3 на пользователя
CREATE TABLE IF NOT EXISTS user_characters (
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
    assigned_by  BIGINT,           -- tg_id админа, который назначил
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, character_id)
);

-- заявки на создание персонажа
CREATE TABLE IF NOT EXISTS character_requests (
    id             SERIAL PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chat_id        BIGINT NOT NULL,          -- групповой чат, куда придёт итог
    name           TEXT NOT NULL,
    description    TEXT,
    affiliation    TEXT,
    position       TEXT,
    photo_file_id  TEXT,
    status         TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    admin_comment  TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at    TIMESTAMPTZ
);

-- если персонаж в таблице привязан к юзернейму, который ещё не писал боту —
-- сохраняем "отложенную" привязку, довяжем при первом /start этого пользователя
CREATE TABLE IF NOT EXISTS pending_owner_links (
    tg_username    TEXT NOT NULL,
    character_id   INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
    PRIMARY KEY (tg_username, character_id)
);

CREATE TABLE IF NOT EXISTS character_aliases (
    id            SERIAL PRIMARY KEY,
    character_id  INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
    alias         TEXT NOT NULL UNIQUE
);