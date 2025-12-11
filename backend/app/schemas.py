from typing import Optional, Any, Dict, Literal
from datetime import datetime

from pydantic import BaseModel, Field


# ---------- Manufacturers ----------


class ManufacturerBase(BaseModel):
    # Minimaal 1 teken, zodat een tikfout minder snel tot 422 leidt
    name: str = Field(..., min_length=1, max_length=200)
    country_code: Optional[str] = Field(
        None, min_length=2, max_length=2, description="ISO 3166-1 alpha-2, bv. NL"
    )
    website_url: Optional[str] = None
    notes: Optional[str] = None


class ManufacturerCreate(ManufacturerBase):
    pass


class ManufacturerUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    country_code: Optional[str] = Field(None, min_length=2, max_length=2)
    website_url: Optional[str] = None
    notes: Optional[str] = None


class ManufacturerRead(ManufacturerBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------- Parks ----------


class ParkBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    country_code: Optional[str] = Field(
        None, min_length=2, max_length=2, description="ISO 3166-1 alpha-2, bv. NL"
    )
    website_url: Optional[str] = None
    opening_year: int | None = None
    opening_month: int | None = None
    opening_day: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    notes: Optional[str] = None


class ParkCreate(ParkBase):
    pass


class ParkUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    country_code: Optional[str] = Field(None, min_length=2, max_length=2)
    website_url: Optional[str] = None
    notes: Optional[str] = None


class ParkRead(ParkBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------- Coasters ----------


class CoasterBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    park_id: str = Field(..., min_length=1)
    manufacturer_id: Optional[str] = None
    opening_year: Optional[int] = Field(
        None, ge=1800, le=2100, description="Jaar van opening"
    )
    height_m: Optional[float] = Field(
    None, ge=0, le=200, description="Hoogte in meters"
)
    speed_kmh: Optional[int] = Field(
        None, ge=0, le=250, description="Snelheid in km/h"
    )
    status: Optional[str] = None
    notes: Optional[str] = None


class CoasterCreate(CoasterBase):
    pass


class CoasterUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    park_id: Optional[str] = Field(None, min_length=1)
    manufacturer_id: Optional[str] = None
    opening_year: Optional[int] = Field(None, ge=1800, le=2100)
    height_m: Optional[float] = Field(None, ge=0, le=200)
    speed_kmh: Optional[int] = Field(None, ge=0, le=250)
    status: Optional[str] = None
    notes: Optional[str] = None


class CoasterRead(CoasterBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------- DataSuggestions ----------


class DataSuggestionBase(BaseModel):
    entity_type: Literal["manufacturer", "park", "coaster"]
    entity_id: Optional[str] = Field(
        None, description="ID van bestaande entiteit; None voor nieuwe entiteit"
    )
    source_url: Optional[str] = None

    # Vrije JSON-payload met voorgestelde waarden (generiek / toekomstbestendig)
    suggested_data: Dict[str, Any]
    current_data: Optional[Dict[str, Any]] = None


class DataSuggestionCreate(DataSuggestionBase):
    """
    Wordt gebruikt door crawler/AI of test tools om een nieuw voorstel te registreren.
    Status is impliciet 'pending'.
    """

    pass


class DataSuggestionRead(DataSuggestionBase):
    id: str
    status: str
    review_note: Optional[str] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DataSuggestionReview(BaseModel):
    """
    Body voor accept/reject-acties in de API.
    """

    action: Literal["accept", "reject"]
    review_note: Optional[str] = None


# ---------- Source Page Read ----------


class SourcePageRead(BaseModel):
    id: str
    entity_type: str
    entity_id: str | None
    url: str
    status_code: str | None
    raw_html: str | None
    clean_text: str | None
    fetched_at: datetime

    class Config:
        from_attributes = True
