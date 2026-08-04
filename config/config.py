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
        self.google_sheets_credentials_path = data["google_sheets"]["credentials_path"]
        self.google_sheets_spreadsheet_id = data["google_sheets"]["spreadsheet_id"]
        self.google_sheets_sheet_name = data["google_sheets"]["sheet_name"]


def load_config() -> Config:
    env = os.getenv("APP_ENV", "dev")
    config_path = Path(__file__).parent / f"config.{env}.yml"
    return Config(config_path)


config = load_config()