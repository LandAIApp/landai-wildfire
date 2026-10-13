"""Application settings (environment variables / .env)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
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

    # --- Custom AOI (drawn polygons) -------------------------------------------------
    # Municipality mode keeps MAX_AOI_HECTARES / WARN_AOI_HECTARES (unchanged behavior).
    max_custom_aoi_hectares: float = Field(100_000, validation_alias='MAX_CUSTOM_AOI_HECTARES')
    warn_custom_aoi_hectares: float = Field(50_000, validation_alias='WARN_CUSTOM_AOI_HECTARES')
    min_custom_aoi_hectares: float = Field(10, validation_alias='MIN_CUSTOM_AOI_HECTARES')
    max_polygon_vertices: int = Field(300, validation_alias='MAX_POLYGON_VERTICES')

    # --- Rate limiting (SlowAPI, in memory) -------------------------------------------
    rate_limit_enabled: bool = Field(True, validation_alias='RATE_LIMIT_ENABLED')
    rate_limit_analyze: str = Field('5/hour;20/day', validation_alias='RATE_LIMIT_ANALYZE')
    rate_limit_exposure: str = Field('10/hour;40/day', validation_alias='RATE_LIMIT_EXPOSURE')
    trust_forwarded_for: bool = Field(False, validation_alias='TRUST_FORWARDED_FOR')
    trusted_proxy_hops: int = Field(1, validation_alias='TRUSTED_PROXY_HOPS')

    # --- Exposure & Impact module ------------------------------------------------------
    # Independent from the wildfire AOI limits: Overpass/WorldPop/footprint cost grows with area.
    max_exposure_aoi_hectares: float = Field(50_000, validation_alias='MAX_EXPOSURE_AOI_HECTARES')
    exposure_max_pixels: int = Field(3_000_000, validation_alias='EXPOSURE_MAX_PIXELS')
    exposure_default_buffer_m: float = Field(500, validation_alias='EXPOSURE_DEFAULT_BUFFER_M')
    exposure_max_buffer_m: float = Field(2000, validation_alias='EXPOSURE_MAX_BUFFER_M')
    exposure_download_timeout_s: float = Field(600, validation_alias='EXPOSURE_DOWNLOAD_TIMEOUT_S')
    # Earth Engine evaluates a download in memory: big areas are fetched as several tiles of at most this many
    # pixels per side (+ a 104 px margin), a few in parallel. Lower it if EE reports 'User memory limit exceeded'.
    exposure_tile_px: int = Field(640, validation_alias='EXPOSURE_TILE_PX')
    exposure_tile_workers: int = Field(3, validation_alias='EXPOSURE_TILE_WORKERS')
    # Time budget for the whole footprint download; no new tile is started after it (the client waits 20 min).
    exposure_max_seconds: int = Field(1000, validation_alias='EXPOSURE_MAX_SECONDS')
    exposure_max_concurrent: int = Field(1, validation_alias='EXPOSURE_MAX_CONCURRENT')
    exposure_max_layer_features: int = Field(5000, validation_alias='EXPOSURE_MAX_LAYER_FEATURES')
    exposure_max_display_vertices: int = Field(60_000, validation_alias='EXPOSURE_MAX_DISPLAY_VERTICES')
    exposure_max_hazard_vertices: int = Field(200_000, validation_alias='EXPOSURE_MAX_HAZARD_VERTICES')
    analysis_ref_ttl_seconds: int = Field(6 * 3600, validation_alias='ANALYSIS_REF_TTL_SECONDS')
    # Secret that signs backend-issued analysis references. Empty = random per process
    # (references then stop validating after a restart / scale-to-zero).
    analysis_ref_secret: str = Field('', validation_alias='ANALYSIS_REF_SECRET')

    # OpenStreetMap / Overpass
    overpass_endpoint: str = Field('https://overpass-api.de/api/interpreter',
                                   validation_alias='OVERPASS_ENDPOINT')
    # Tried once each, in order, when the main instance answers 429/5xx/timeout (public, shared servers).
    overpass_fallback_endpoints: str = Field(
        'https://overpass.kumi.systems/api/interpreter,https://overpass.private.coffee/api/interpreter',
        validation_alias='OVERPASS_FALLBACK_ENDPOINTS')
    overpass_fallback_pause_s: float = Field(2.0, validation_alias='OVERPASS_FALLBACK_PAUSE_S')
    overpass_user_agent: str = Field(
        'LandAI-Wildfire-Intelligence/2.0 (+https://github.com/LandAIApp/landai-wildfire)',
        validation_alias='OVERPASS_USER_AGENT')
    overpass_http_timeout_s: float = Field(60, validation_alias='OVERPASS_HTTP_TIMEOUT_S')
    overpass_query_timeout_s: int = Field(40, validation_alias='OVERPASS_QUERY_TIMEOUT_S')
    overpass_max_elements: int = Field(60_000, validation_alias='OVERPASS_MAX_ELEMENTS')
    overpass_max_response_bytes: int = Field(40_000_000, validation_alias='OVERPASS_MAX_RESPONSE_BYTES')
    overpass_max_concurrent: int = Field(1, validation_alias='OVERPASS_MAX_CONCURRENT')
    overpass_cache_ttl_seconds: int = Field(6 * 3600, validation_alias='OVERPASS_CACHE_TTL_SECONDS')

    # WorldPop (the optional key lives ONLY here, never in the frontend)
    worldpop_base_url: str = Field('https://api.worldpop.org', validation_alias='WORLDPOP_BASE_URL')
    worldpop_api_version: str = Field('v2', validation_alias='WORLDPOP_API_VERSION')  # v2 | v1
    worldpop_year: int = Field(2020, validation_alias='WORLDPOP_YEAR')
    worldpop_resolution: str = Field('100m', validation_alias='WORLDPOP_RESOLUTION')  # 100m | 1km
    worldpop_api_key: str = Field('', validation_alias='WORLDPOP_API_KEY')
    worldpop_http_timeout_s: float = Field(30, validation_alias='WORLDPOP_HTTP_TIMEOUT_S')
    worldpop_poll_interval_s: float = Field(3, validation_alias='WORLDPOP_POLL_INTERVAL_S')
    worldpop_max_wait_s: float = Field(90, validation_alias='WORLDPOP_MAX_WAIT_S')
    worldpop_max_vertices: int = Field(20_000, validation_alias='WORLDPOP_MAX_VERTICES')
    worldpop_simplify_tolerance_m: float = Field(5, validation_alias='WORLDPOP_SIMPLIFY_TOLERANCE_M')
    worldpop_cache_ttl_seconds: int = Field(24 * 3600, validation_alias='WORLDPOP_CACHE_TTL_SECONDS')

    log_level: str = Field('INFO', validation_alias='LOG_LEVEL')

    @model_validator(mode='after')
    def _check_limits(self) -> 'Settings':
        if self.warn_custom_aoi_hectares > self.max_custom_aoi_hectares:
            self.warn_custom_aoi_hectares = self.max_custom_aoi_hectares
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(',') if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
