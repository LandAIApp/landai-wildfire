"""Request/response models for POST /api/v1/exposure/analyze and GET /api/v1/config."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .wildfire import PolygonGeometry


class HazardGeometry(BaseModel):
    """External hazard polygon (separate, clearly identified mode; NOT the validated wildfire workflow)."""

    type: Literal['Polygon', 'MultiPolygon']
    coordinates: list[Any] = Field(min_length=1, max_length=2000)


class ExposureRequest(BaseModel):
    # Mode 1 (default): reference issued by the backend with a wildfire analysis.
    analysis_ref: str | None = Field(None, min_length=20, max_length=20000)
    # Mode 2: external hazard polygon + the study area it belongs to.
    hazard_geometry: HazardGeometry | None = None
    aoi_geometry: PolygonGeometry | None = None
    hazard_type: Literal['wildfire'] = 'wildfire'
    threshold: float = Field(0.72, ge=0.0, le=1.0)
    buffer_m: float | None = Field(None, ge=0)
    include_population: bool = True
    include_sensitivity: bool = True

    @model_validator(mode='after')
    def _one_mode(self) -> 'ExposureRequest':
        if bool(self.analysis_ref) == (self.hazard_geometry is not None):
            raise ValueError('send either analysis_ref or hazard_geometry (with aoi_geometry), not both/none')
        if self.hazard_geometry is not None and self.aoi_geometry is None:
            raise ValueError('aoi_geometry is required together with hazard_geometry')
        if self.analysis_ref and self.aoi_geometry is not None:
            raise ValueError('aoi_geometry is only accepted together with hazard_geometry')
        return self


class SourceStatus(BaseModel):
    status: Literal['success', 'error', 'skipped']
    details: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None


class ExposureWarning(BaseModel):
    code: str
    message: str = ''
    params: dict[str, Any] = Field(default_factory=dict)


class ExposureResponse(BaseModel):
    status: Literal['success', 'partial']
    hazard_type: Literal['wildfire']
    mode: Literal['wildfire_analysis', 'external_polygon']
    analysis: dict[str, Any]
    metrics: dict[str, Any]
    details: dict[str, Any]
    sensitivity: list[dict[str, Any]] = []
    sources: dict[str, SourceStatus]
    warnings: list[ExposureWarning] = []
    layers: dict[str, Any]
    exports: dict[str, Any]
    notice: dict[str, str]
