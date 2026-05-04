from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    supabase_db_url: str
    auth_jwt_secret: str = "change-me-in-production-use-env-var"
    auth_jwt_algorithm: str = "HS256"
    auth_jwt_expire_minutes: int = 60
    redis_url: str = "redis://redis:6379"
    cors_origins: str = ""
    jaeger_endpoint: str = "http://jaeger:4317"
    service_name: str = "auth-service"
    service_port: int = 8004
    supabase_pooler_region: str = "ap-south-1"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
