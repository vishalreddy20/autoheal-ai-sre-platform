from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    supabase_db_url: str
    supabase_db_url_replica: str = ""
    supabase_pooler_region: str = "ap-south-1"
    cors_origins: str = ""
    jaeger_endpoint: str = "http://jaeger:4317"
    log_level: str = "info"
    service_name: str = "user-service"
    service_port: int = 8001

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def replica_url(self) -> str:
        return self.supabase_db_url_replica or self.supabase_db_url

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
