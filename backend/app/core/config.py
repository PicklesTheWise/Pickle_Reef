from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR.parent / "data" / "pickle_reef.db"
DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    """Runtime configuration values sourced from env vars or .env."""

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    database_url: str = f"sqlite+aiosqlite:///{DEFAULT_DB_PATH.as_posix()}"
    telemetry_retention_days: int = 30

    mqtt_host: str = "mqtt"
    mqtt_port: int = 1883
    mqtt_topic_prefix: str = "pickle-reef"
    ws_trace: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="allow")


settings = Settings()
