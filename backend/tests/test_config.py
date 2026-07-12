import pytest
from pydantic import ValidationError

from app.config import Settings


def test_production_mode_fails_closed_without_authentication_design():
    with pytest.raises(ValidationError, match="Production mode is disabled"):
        Settings(app_env="production")


def test_development_mode_is_available_for_local_and_test_workflows():
    assert Settings(app_env="development").app_env == "development"


def test_openai_mode_requires_api_key():
    with pytest.raises(ValidationError, match="OPENAI_API_KEY is required"):
        Settings(ai_generation_mode="openai")


def test_api_key_is_redacted_from_settings_representation():
    settings = Settings(ai_generation_mode="openai", openai_api_key="super-secret-value")

    assert "super-secret-value" not in repr(settings)
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "super-secret-value"


def test_database_credentials_are_redacted_from_settings_representation():
    settings = Settings(database_url="postgresql+psycopg://user:secret@example.com/database")

    assert "secret" not in repr(settings)
    assert settings.database_url.endswith("/database")


@pytest.mark.parametrize(
    "origin",
    ["*", "file:///tmp", "https://user:password@example.com", "https://example.com/path"],
)
def test_invalid_cors_origins_are_rejected(origin):
    with pytest.raises(ValidationError, match="Invalid CORS origin"):
        Settings(cors_origins=origin)


def test_matching_countries_are_normalized_and_validated():
    settings = Settings(matching_permitted_countries=" pt,ES,pt ")
    assert settings.matching_permitted_countries == "PT,ES"
    assert settings.permitted_countries == {"PT", "ES"}

    with pytest.raises(ValidationError, match="two-letter codes"):
        Settings(matching_permitted_countries="PT,123")
