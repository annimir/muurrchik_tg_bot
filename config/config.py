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

        # google_sheets.* — УБРАНО (Этап A, Google Sheets-интеграция удалена)


def load_config() -> Config:
    env = os.getenv("APP_ENV", "dev")
    config_path = Path(__file__).parent / f"config.{env}.yml"
    return Config(config_path)


config = load_config()