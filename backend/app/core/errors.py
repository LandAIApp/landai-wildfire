"""Structured application errors returned as JSON by the API."""
from __future__ import annotations

from typing import Any


class WildfireError(Exception):
    status_code = 400
    code = 'wildfire_error'

    def __init__(self, message: str, *, details: Any = None):
        super().__init__(message)
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        return {'status': 'error', 'code': self.code, 'message': self.message,
                'details': self.details}


class InvalidRequestError(WildfireError):
    status_code, code = 422, 'invalid_request'


class DepartmentNotFoundError(WildfireError):
    status_code, code = 404, 'department_not_found'


class MunicipalityNotFoundError(WildfireError):
    status_code, code = 404, 'municipality_not_found'


class PreflightFailedError(WildfireError):
    status_code, code = 422, 'preflight_failed'


class NoTrainingSamplesError(WildfireError):
    status_code, code = 422, 'no_training_samples'


class EarthEngineAuthError(WildfireError):
    status_code, code = 503, 'earth_engine_not_available'


class EarthEngineServiceError(WildfireError):
    status_code, code = 502, 'earth_engine_error'


class EarthEngineTimeoutError(WildfireError):
    status_code, code = 504, 'earth_engine_timeout'


class EarthEngineLimitError(WildfireError):
    status_code, code = 422, 'earth_engine_computation_limit'


class EarthEngineQuotaError(WildfireError):
    status_code, code = 429, 'earth_engine_quota'


class TileGenerationError(WildfireError):
    status_code, code = 502, 'tile_generation_failed'


class RateLimitError(WildfireError):
    status_code, code = 429, 'rate_limit_exceeded'


class ServerBusyError(WildfireError):
    status_code, code = 503, 'server_busy'


class ServicePausedError(WildfireError):
    status_code, code = 503, 'service_paused'


class InvalidAnalysisRefError(WildfireError):
    status_code, code = 422, 'invalid_analysis_ref'


class ExposureAreaTooLargeError(WildfireError):
    status_code, code = 422, 'exposure_aoi_too_large'


class FootprintError(WildfireError):
    status_code, code = 502, 'footprint_extraction_failed'


class NoAffectedAreaError(WildfireError):
    status_code, code = 422, 'no_affected_area'


class ExternalSourceError(WildfireError):
    """An external open-data source (Overpass, WorldPop) failed. The exposure endpoint turns this into a
    per-source status instead of failing the whole request."""

    def __init__(self, message: str, *, code: str, status_code: int = 502, details=None):
        super().__init__(message, details=details)
        self.code = code
        self.status_code = status_code
