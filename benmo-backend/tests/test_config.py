import pytest
from pydantic import ValidationError

from benmo_backend.config import Settings


def test_production_rejects_development_secrets() -> None:
    with pytest.raises(ValidationError, match="non-default secrets"):
        Settings(environment="production")


def test_database_components_are_encoded_and_url_takes_precedence() -> None:
    settings = Settings(
        environment="production",
        admin_api_key="secure-admin",
        backend_internal_token="secure-worker",
        database_host="db.internal",
        database_user="user@example",
        database_password="a/b c",
        database_name="causal data",
    )
    assert settings.database_url == (
        "postgresql+asyncpg://user%40example:a%2Fb+c@db.internal:5432/causal+data"
    )

    explicit = Settings(
        environment="production",
        admin_api_key="secure-admin",
        backend_internal_token="secure-worker",
        database_url="postgresql://explicit:secret@db/benmo",
        database_host="ignored",
        database_user="ignored",
        database_password="ignored",
    )
    assert explicit.database_url.startswith("postgresql+asyncpg://explicit")
