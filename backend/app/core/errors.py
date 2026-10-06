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
