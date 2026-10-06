from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class WildfireRequest(BaseModel):
    department: str = Field(..., min_length=1, max_length=120)
    municipality: str = Field(..., min_length=1, max_length=120)
    fire_date: date
    analysis_end: date

    @model_validator(mode='after')
    def _check_order(self) -> 'WildfireRequest':
        if self.analysis_end < self.fire_date:
            raise ValueError('analysis_end must be on or after fire_date')
        return self


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


class PreflightResponse(BaseModel):
    status: Literal['ok', 'blocked']
    valid: bool
    pre_count: int | None = None
    post_count: int | None = None
    history_count: int | None = None
    date_windows: DateWindows | None = None
    aoi_hectares: float | None = None
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
