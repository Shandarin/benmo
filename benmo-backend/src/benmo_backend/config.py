from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BENMO_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Benmo Causal Platform API"
    environment: Literal["local", "test", "staging", "production"] = "local"
    database_url: str = ""
    database_host: str | None = None
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = "benmo"
    database_user: str | None = None
    database_password: str | None = None
    queue_backend: Literal["memory", "database", "sqs"] = "database"
    aws_region: str = "us-east-1"
    sqs_analysis_queue_url: str | None = None
    ecs_cluster: str | None = None
    research_worker_task_definition: str | None = None
    worker_subnet_ids: str = ""
    worker_security_group_ids: str = ""
    admin_api_key: str = "local-development-key"
    backend_internal_token: str = "local-worker-token"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    log_level: str = "INFO"
    auto_create_schema: bool = False
    sse_poll_interval_seconds: float = Field(default=1.0, gt=0, le=30)
    sse_heartbeat_seconds: float = Field(default=15.0, gt=0, le=120)

    @field_validator("database_url")
    @classmethod
    def normalize_database_driver(cls, value: str) -> str:
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if value.startswith("sqlite:///") and not value.startswith("sqlite+aiosqlite:///"):
            return value.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        return value

    @model_validator(mode="after")
    def assemble_database_url(self) -> Settings:
        if self.database_url:
            return self
        supplied = [self.database_host, self.database_user, self.database_password]
        if any(supplied):
            if not all(supplied):
                raise ValueError(
                    "database_host, database_user, and database_password must be supplied together"
                )
            user = quote_plus(self.database_user or "")
            password = quote_plus(self.database_password or "")
            database = quote_plus(self.database_name)
            self.database_url = (
                f"postgresql+asyncpg://{user}:{password}@{self.database_host}:"
                f"{self.database_port}/{database}"
            )
        else:
            self.database_url = "sqlite+aiosqlite:///./benmo.db"
        return self

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def reject_development_secrets_outside_local(self) -> Settings:
        if self.environment in {"staging", "production"}:
            insecure = {
                "admin_api_key": (self.admin_api_key, "local-development-key"),
                "backend_internal_token": (self.backend_internal_token, "local-worker-token"),
            }
            invalid = [
                name
                for name, (value, development_default) in insecure.items()
                if not value or value == development_default
            ]
            if invalid:
                raise ValueError(
                    "staging/production require non-default secrets: " + ", ".join(invalid)
                )
        return self

    @property
    def resolved_worker_subnet_ids(self) -> list[str]:
        return [value.strip() for value in self.worker_subnet_ids.split(",") if value.strip()]

    @property
    def resolved_worker_security_group_ids(self) -> list[str]:
        return [
            value.strip() for value in self.worker_security_group_ids.split(",") if value.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
