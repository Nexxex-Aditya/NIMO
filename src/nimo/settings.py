from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    searxng_base_url: str
    log_level: str = "INFO"
    # Only the KEY lives here (`04` §9); endpoint/model/api_version are
    # non-secret and live in `config/models.yaml`. Optional at import so the
    # off-network modes keep working; `--adjudicate` asserts it at startup.
    cis_llm_api_key: str | None = None
    # The Brave Search API key (`config/retrieval.yaml` `search_backend`).
    # Optional: without it the pipeline uses SearxNG.
    brave_api_key: str | None = None
    # Use the operating system's certificate store for HTTPS (`truststore`).
    # For a corporate network whose proxy re-signs TLS with a company CA that
    # Python's bundled certificates do not know. Off by default.
    nimo_system_certs: bool = False


settings = Settings()  # raises at import time if a required var is absent
