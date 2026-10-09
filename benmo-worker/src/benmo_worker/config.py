from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from benmo_worker.errors import ConfigurationError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BENMO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: Literal["local", "test", "staging", "production"] = "local"
    provider_mode: Literal["stub", "live"] = "stub"
    log_level: str = "INFO"
    log_json: bool = True

    backend_base_url: AnyHttpUrl | None = None
    backend_internal_token: SecretStr | None = None
    backend_timeout_seconds: float = Field(default=30.0, gt=0, le=300)

    object_store: Literal["local", "s3"] = "local"
    local_object_path: Path = Path(".benmo/objects")
    local_state_path: Path = Path(".benmo/worker-state.sqlite3")
    s3_bucket: str | None = None
    s3_prefix: str = "worker"
    aws_region: str = Field(default="us-east-1", validation_alias=AliasChoices("BENMO_AWS_REGION", "AWS_REGION"))

    research_queue_url: str | None = None
    document_queue_url: str | None = None
    document_queue_urls: str | None = None
    verification_queue_url: str | None = None
    source_fetch_queue_url: str | None = None
    filing_processing_queue_url: str | None = None
    manual_review_queue_url: str | None = None
    sqs_endpoint_url: str | None = None
    sqs_wait_seconds: int = Field(default=20, ge=0, le=20)
    sqs_visibility_timeout: int = Field(default=900, ge=30, le=43200)
    sqs_max_messages: int = Field(default=1, ge=1, le=10)

    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("BENMO_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    openai_model: str = "gpt-5.6"
    openai_entailment_model: str | None = None
    openai_timeout_seconds: float = Field(default=120.0, gt=0, le=600)

    finnhub_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("BENMO_FINNHUB_API_KEY", "FINNHUB_API_KEY"),
    )
    alpha_vantage_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("BENMO_ALPHA_VANTAGE_API_KEY", "ALPHA_VANTAGE_API_KEY"),
    )
    fred_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("BENMO_FRED_API_KEY", "FRED_API_KEY"),
    )
    bls_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("BENMO_BLS_API_KEY", "BLS_API_KEY"),
    )
    eia_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("BENMO_EIA_API_KEY", "EIA_API_KEY"),
    )
    bea_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("BENMO_BEA_API_KEY", "BEA_API_KEY"),
    )
    sec_user_agent: str = "Benmo Research contact@example.invalid"
    outbound_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_document_bytes: int = Field(default=10_000_000, ge=1_024, le=100_000_000)
    workflow_version: str = "analysis-v1"
    prompt_version: str = "candidate-edge-v1"
    stage_input: str | None = None
    stage_output: str | None = None

    @model_validator(mode="after")
    def validate_live_configuration(self) -> Settings:
        if self.provider_mode == "live" and self.openai_api_key is None:
            raise ConfigurationError("BENMO_OPENAI_API_KEY is required in live provider mode")
        if self.object_store == "s3" and not self.s3_bucket:
            raise ConfigurationError("BENMO_S3_BUCKET is required for the s3 object store")
        if self.env == "production" and self.backend_base_url is None:
            raise ConfigurationError("BENMO_BACKEND_BASE_URL is required in production")
        if self.env == "production" and self.backend_internal_token is None:
            raise ConfigurationError("BENMO_BACKEND_INTERNAL_TOKEN is required in production")
        if self.env == "production" and (
            "@" not in self.sec_user_agent or ".invalid" in self.sec_user_agent.casefold()
        ):
            raise ConfigurationError("production SEC user agent must contain a real contact email")
        return self

    @property
    def resolved_document_queue_urls(self) -> list[str]:
        values: list[str] = []
        for raw in (self.document_queue_urls, self.document_queue_url):
            if raw:
                values.extend(part.strip() for part in raw.split(",") if part.strip())
        return list(dict.fromkeys(values))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
