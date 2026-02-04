from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str
    database_url: str

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
