from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    searxng_base_url: str
    log_level: str = "INFO"


settings = Settings()  # raises at import time if a required var is absent
