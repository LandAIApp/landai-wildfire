"""Public runtime configuration: the frontend never hard-codes limits, it reads them from here."""
from __future__ import annotations

from pydantic import BaseModel


class RateLimitInfo(BaseModel):
    count: int
    per: str


class PublicConfig(BaseModel):
    status: str = 'ok'
    version: str
    aoi: dict
    exposure: dict
    rate_limits: dict
    sources: dict
