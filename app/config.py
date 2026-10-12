from functools import lru_cache
from urllib.parse import quote

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str
    postgres_password: SecretStr
    postgres_db: str

    redis_url: str = "redis://redis:6379/0"

    rabbitmq_host: str = "rabbitmq"
    rabbitmq_port: int = 5672
    rabbitmq_default_user: str
    rabbitmq_default_pass: SecretStr

    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    jwt_ttl_minutes: int = 60
    search_ttl_seconds: int = 900
    search_cache_ttl_seconds: int = 300

    provider_delay_min_seconds: float = 1.0
    provider_delay_max_seconds: float = 3.0
    provider_timeout_seconds: float = 5.0
    provider_failure_rate: float = 0.0
    provider_timeout_rate: float = 0.0

    order_ttl_minutes: int = 30

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @property
    def rabbitmq_url(self) -> str:
        user = quote(self.rabbitmq_default_user, safe="")
        password = quote(self.rabbitmq_default_pass.get_secret_value(), safe="")
        return f"amqp://{user}:{password}@{self.rabbitmq_host}:{self.rabbitmq_port}/"


@lru_cache
def get_settings() -> Settings:
    return Settings()
