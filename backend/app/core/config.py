"""Application settings (environment variables / .env)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=('.env', str(BACKEND_DIR / '.env'), str(REPO_ROOT / '.env')),
        extra='ignore',
    )

    ee_project: str = Field('', validation_alias=AliasChoices('EE_PROJECT', 'EE_PROJECT_ID'))
    ee_service_account: str = Field('', validation_alias='EE_SERVICE_ACCOUNT')
    ee_private_key_path: str = Field('', validation_alias='EE_PRIVATE_KEY_PATH')
    cors_origins: str = Field('http://localhost:5173,http://127.0.0.1:5173',
                              validation_alias='CORS_ORIGINS')
    municipalities_asset: str = Field('users/maikolzaraza07/mpios',
                                      validation_alias='MUNICIPALITIES_ASSET')

    # Application-layer guards (NOT part of V7.6 science)
    max_aoi_hectares: float = Field(500_000, validation_alias='MAX_AOI_HECTARES')
    warn_aoi_hectares: float = Field(100_000, validation_alias='WARN_AOI_HECTARES')
    min_fire_date: str = Field('2018-08-01', validation_alias='MIN_FIRE_DATE')

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(',') if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
