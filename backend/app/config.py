from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite+aiosqlite:///./data/name.db"
    redis_url: str = "redis://localhost:6379/0"
    admin_api_key: str = "change-me-admin-key"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    wechat_app_id: str = ""
    wechat_app_secret: SecretStr = SecretStr("")
    wechat_mch_id: str = ""
    wechat_mch_key: SecretStr = SecretStr("")
    wechat_mch_serial_no: str = ""
    wechat_mch_private_key_path: str = ""
    wechat_pay_notify_url: str = ""

    llm_mock: bool = True
    llm_provider: Literal["deepseek", "openai", "dashscope", "custom"] = "deepseek"
    llm_api_base: str = "https://api.deepseek.com/v1"
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = "deepseek-v4-flash"
    llm_model_fate: str | None = None
    llm_model_compose: str | None = None
    llm_model_qa: str | None = None
    llm_model_curator: str | None = None
    llm_model_wuxing: str | None = None
    llm_timeout_seconds: int = 300
    llm_max_retries: int = 2
    llm_temperature: float = 0.3

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
