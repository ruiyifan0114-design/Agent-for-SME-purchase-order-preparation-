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
    deepseek_model: str = "deepseek-flash"
    deepseek_fallback_model: str = ""
    agent_timeout_seconds: int = 70
    agent_model_attempts: int = 2
    agent_circuit_failure_threshold: int = 3
    agent_circuit_cooldown_seconds: int = 60
    agent_max_tool_calls: int = 8
    agent_token_budget: int = 20000
    agent_cost_budget_usd: float = 0.25
    deepseek_input_cost_per_million: float = 0.0
    deepseek_output_cost_per_million: float = 0.0
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    supabase_url: str = ""
    supabase_audience: str = "authenticated"
    allow_api_keys: bool = False
    metrics_enabled: bool = True


@lru_cache
def settings() -> Settings:
    return Settings()
