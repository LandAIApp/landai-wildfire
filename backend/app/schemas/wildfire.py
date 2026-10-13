from __future__ import annotations

from datetime import date
from typing import Any, Literal

from typing import Annotated

from pydantic import BaseModel, Field, model_validator

Position = Annotated[list[float], Field(min_length=2, max_length=3)]
Ring = Annotated[list[Position], Field(max_length=2000)]


class PolygonGeometry(BaseModel):
    """GeoJSON Polygon (EPSG:4326, [lon, lat]). Only Polygon is supported: MultiPolygon has not
    been verified through the whole wildfire graph, so it is rejected by the schema."""

    type: Literal['Polygon']
    coordinates: Annotated[list[Ring], Field(min_length=1, max_length=5)]


class WildfireRequest(BaseModel):
    """Select the study area EITHER by municipality (original contract) OR by a drawn polygon."""

    department: str | None = Field(None, min_length=1, max_length=120)
    municipality: str | None = Field(None, min_length=1, max_length=120)
    geometry: PolygonGeometry | None = None
    fire_date: date
    analysis_end: date

    @model_validator(mode='after')
    def _check_order(self) -> 'WildfireRequest':
        if self.analysis_end < self.fire_date:
            raise ValueError('analysis_end must be on or after fire_date')
        return self

    @model_validator(mode='after')
    def _one_area_source(self) -> 'WildfireRequest':
        partial = bool(self.department) != bool(self.municipality)
        by_municipality = bool(self.department) and bool(self.municipality)
        by_geometry = self.geometry is not None
        if partial:
            raise ValueError('department and municipality must be provided together')
        if by_municipality and by_geometry:
            raise ValueError('conflicting area selection: send either department + municipality or geometry, not both')
        if not by_municipality and not by_geometry:
            raise ValueError('provide either department + municipality or a drawn geometry')
        return self

    @property
    def aoi_kind(self) -> str:
        return 'drawn' if self.geometry is not None else 'municipality'


class DateRange(BaseModel):
    start: str | None = None
    end: str | None = None


class DateWindows(BaseModel):
    pre: DateRange
    post: DateRange
    history: DateRange


class Issue(BaseModel):
    code: str
    message: str
    params: dict[str, Any] = Field(default_factory=dict)


class PreflightResponse(BaseModel):
    status: Literal['ok', 'blocked']
    valid: bool
    pre_count: int | None = None
    post_count: int | None = None
    history_count: int | None = None
    date_windows: DateWindows | None = None
    aoi_hectares: float | None = None
    aoi_kind: Literal['municipality', 'drawn'] | None = None
    warnings: list[Issue] = []
    blocking_errors: list[Issue] = []


class AreaEntry(BaseModel):
    threshold: float
    key: str
    label: str
    hectares: float


class LegendInfo(BaseModel):
    type: Literal['gradient', 'solid', 'rgb']
    min: float | None = None
    max: float | None = None
    colors: list[str] = []


class LayerInfo(BaseModel):
    id: str
    label: str
    group: str
    description: str
    tile_url: str
    visible_by_default: bool
    legend: LegendInfo | None = None


class TrainingInfo(BaseModel):
    positive_samples: int
    negative_samples: int
    note: str


class AnalyzeResponse(BaseModel):
    status: Literal['ok']
    metadata: dict[str, Any]
    image_counts: dict[str, int]
    date_windows: DateWindows
    training: TrainingInfo
    area_statistics: dict[str, float]
    area_hectares: list[AreaEntry]
    layers: list[LayerInfo]
    boundary: dict[str, Any]
    bounds: list[list[float]]
    warnings: list[Issue] = []
    # Added in v2 (optional, backwards compatible): signed reference to this analysis for the
    # Exposure module, and the kind/size of the study area.
    analysis_ref: str | None = None
    aoi: dict[str, Any] | None = None
