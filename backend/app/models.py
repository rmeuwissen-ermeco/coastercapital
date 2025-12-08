import uuid
from sqlalchemy import Column, String, DateTime, Integer
from sqlalchemy.sql import func

from .db import Base


class Manufacturer(Base):
    __tablename__ = "manufacturers"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False, index=True)
    country_code = Column(String(2), nullable=True)  # bv. "NL"
    website_url = Column(String, nullable=True)
    notes = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

class Park(Base):
    __tablename__ = "parks"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False, index=True)
    country_code = Column(String(2), nullable=True)  # bv. "NL"
    website_url = Column(String, nullable=True)
    notes = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

class Coaster(Base):
    __tablename__ = "coasters"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False, index=True)

    # Relaties via ID's (bewust simpel gehouden)
    park_id = Column(String, nullable=False, index=True)
    manufacturer_id = Column(String, nullable=True, index=True)

    # Basis-kenmerken – optioneel, voor toekomstige uitbreiding
    opening_year = Column(Integer, nullable=True)
    height_m = Column(Integer, nullable=True)
    speed_kmh = Column(Integer, nullable=True)
    status = Column(String, nullable=True)  # bv. "Operating", "Closed"
    notes = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
