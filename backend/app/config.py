from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    data_dir: Path = BACKEND_DIR / "data"
    max_upload_mb: int = 25
    max_reference_mb: int = 10

    # Server-side only; pass explicitly to SDK clients (pydantic-settings does not export to os.environ)
    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    # Figma personal access token (scope file_content:read) for importing frames by link.
    figma_token: SecretStr | None = None

    max_concurrent_generations: int = 2
    preview_long_edge: int = 1200

    @field_validator("anthropic_api_key", "gemini_api_key", "figma_token", mode="before")
    @classmethod
    def _blank_is_unset(cls, v):
        """An empty KEY= line means "not configured", not an empty credential."""
        return None if v is None or (isinstance(v, str) and not v.strip()) else v

    @property
    def db_path(self) -> Path:
        return self.data_dir / "dieline.db"

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"


@lru_cache
def get_settings() -> Settings:
    return Settings()
