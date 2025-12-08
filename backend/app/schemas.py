from typing import Optional
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
    height_m: Optional[int] = Field(
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
    height_m: Optional[int] = Field(None, ge=0, le=200)
    speed_kmh: Optional[int] = Field(None, ge=0, le=250)
    status: Optional[str] = None
    notes: Optional[str] = None


class CoasterRead(CoasterBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
