from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://procurement:procurement@localhost:5432/procurement"
    api_key: str = "local-service-change-me"
    reviewer_api_key: str = "local-reviewer-change-me"
    reviewer_name: str = "Demo Human Reviewer"
    finance_api_key: str = "local-finance-change-me"
    finance_reviewer_name: str = "Demo Finance Manager"
    deepseek_api_key: str = ""
    deepseek_key_file: str = "deepseek_api_key.txt"
    deepseek_model: str = "deepseek-flash"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    supabase_url: str = ""
    supabase_audience: str = "authenticated"
    allow_api_keys: bool = False


@lru_cache
def settings() -> Settings:
    return Settings()
