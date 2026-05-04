from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    user_service_url: str = "http://user-service:8001"
    task_service_url: str = "http://task-service:8002"
    autoheal_engine_url: str = "http://autoheal-engine:8003"
    auth_service_url: str = "http://auth-service:8004"
    api_gateway_url: str = "http://api-gateway:8000"
    prometheus_url: str = "http://prometheus:9090"
    redis_url: str = "redis://redis:6379"
    cors_origins: str = ""
    docker_socket: str = "/var/run/docker.sock"
    jaeger_endpoint: str = "http://jaeger:4317"
    log_level: str = "info"
    service_name: str = "api-gateway"
    service_port: int = 8000
    auth_jwt_secret: str = "change-me-in-production-use-env-var"
    alertmanager_webhook_secret: str = ""
    allowed_origins: str = ""

    @property
    def cors_origins_list(self) -> List[str]:
        origins = self.allowed_origins or self.cors_origins
        return [o.strip() for o in origins.split(",") if o.strip()]

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
