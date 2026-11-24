"""Phase 1: data model for the IT portfolio.

Convention: a Relationship (source -> target) means "source DEPENDS ON target".
So the target must be separated/available before the source can cut over.
"""
from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class Owner(str, Enum):
    PARENT = "parent"
    CARVED_OUT = "carved_out"
    SHARED = "shared"


class AssetType(str, Enum):
    APPLICATION = "application"
    DATASTORE = "datastore"
    INFRASTRUCTURE = "infrastructure"


class RelType(str, Enum):
    CALLS = "CALLS"
    READS_FROM = "READS_FROM"
    WRITES_TO = "WRITES_TO"
    HOSTED_ON = "HOSTED_ON"
    AUTHENTICATES_VIA = "AUTHENTICATES_VIA"
    CONNECTS_VIA = "CONNECTS_VIA"


class Strategy(str, Enum):
    CLONE = "clone"
    MIGRATE = "migrate"
    REBUILD = "rebuild"
    RETIRE = "retire"
    RETAIN_UNDER_TSA = "retain_under_tsa"


class Asset(BaseModel):
    id: str
    name: str
    type: AssetType
    owner: Owner
    criticality: int = Field(ge=1, le=5, description="1 = low, 5 = business critical")
    users: int = Field(default=0, ge=0)
    function: str | None = None          # used to spot duplicates (e.g. two CRMs)
    hosting: str | None = None
    sensitive: bool = False              # personal / financial data
    effort_weeks: int = Field(default=2, ge=0)  # separation effort estimate
    licence_id: str | None = None
    tsa_id: str | None = None
    notes: str | None = None


class Relationship(BaseModel):
    source: str      # depends on ...
    target: str      # ... this
    type: RelType
    description: str | None = None


class Licence(BaseModel):
    id: str
    vendor: str
    product: str
    end_date: date
    transferable: bool
    annual_cost: float = Field(default=0, ge=0)
    notice_period_days: int = Field(default=0, ge=0)


class TSAService(BaseModel):
    id: str
    service: str
    provider: str = "Parent Group"
    start_date: date
    end_date: date
    monthly_cost: float = Field(ge=0)
    extendable: bool = False
    extension_months: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_dates(self) -> "TSAService":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        if not self.extendable and self.extension_months:
            raise ValueError("extension_months must be zero when TSA is not extendable")
        return self


class Planning(BaseModel):
    company: str
    carve_out_description: str
    day1: date                       # legal close / start of TSA
    cutover_start: date              # earliest date a wave may start
    target_tsa_exit: date
    max_assets_per_wave: int = 8
    weeks_per_wave_gap: int = 2      # stabilisation time between waves

    @model_validator(mode="after")
    def validate_dates(self) -> "Planning":
        if self.cutover_start < self.day1:
            raise ValueError("cutover_start cannot be before day1")
        if self.target_tsa_exit < self.cutover_start:
            raise ValueError("target_tsa_exit cannot be before cutover_start")
        return self


class Portfolio(BaseModel):
    planning: Planning
    assets: list[Asset]
    relationships: list[Relationship]
    licences: list[Licence] = Field(default_factory=list)
    tsa_services: list[TSAService] = Field(default_factory=list)
