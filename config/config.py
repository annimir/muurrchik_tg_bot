from pathlib import Path
import os
import yaml


class Config:
    def __init__(self, path: str | Path):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        self.bot_token: str = data["telegram"]["bot_token"]

        pg = data["postgres"]
        self.pg_dsn: str = (
            f"host={pg['host']} port={pg['port']} "
            f"dbname={pg['dbname']} user={pg['user']} password={pg['password']}"
        )

        # ДОБАВЛЕНО: раньше config.admin_user_id использовался в коде
        # (is_admin, admin_lang и т.д.), но нигде явно не объявлялся здесь.
        self.admin_user_id: int = data["admin"]["user_id"]

        youtube = data.get("youtube", {})
        self.youtube_enabled: bool = youtube.get("enabled", False)
        self.youtube_api_key: str | None = youtube.get("api_key")
        self.youtube_channel_handle: str = youtube.get("channel_handle", "@muuurrchik")
        self.youtube_target_chat_id: int | None = youtube.get("target_chat_id")
        self.youtube_check_interval_seconds: int = youtube.get("check_interval_seconds", 4 * 60 * 60)

        web = data.get("web", {})
        self.web_secret_key: str | None = web.get("secret_key")
        self.web_session_ttl_seconds: int = web.get("session_ttl_seconds", 8 * 60 * 60)
        self.web_media_cache_dir: str = web.get("media_cache_dir", "data/media")
        self.web_public_base_url: str = web.get("public_base_url", "http://localhost:8000")
        self.web_telegram_bot_username: str = web.get("telegram_bot_username", "")
        self.web_secure_cookies: bool = web.get("secure_cookies", False)


def load_config() -> Config:
    env = os.getenv("APP_ENV", "dev")
    config_path = Path.cwd() / f"config.{env}.yml"
    return Config(config_path)


config = load_config()