import uuid
from sqlalchemy import Column, String, DateTime, Integer, Float, JSON, Text
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
    height_m = Column(Float, nullable=True)
    speed_kmh = Column(Integer, nullable=True)
    status = Column(String, nullable=True)  # bv. "Operating", "Closed"
    notes = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

class DataSuggestion(Base):
    """
    Bufferlaag voor AI/crawler-voorstellen.
    Bevat alleen 'voorstellen', de echte data staat in Manufacturer/Park/Coaster.
    """

    __tablename__ = "data_suggestions"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))

    # Voor welk type entity dit geldt
    # bv. "manufacturer", "park" of "coaster"
    entity_type = Column(String, nullable=False)

    # Optioneel: bestaande entity waar dit voorstel bij hoort
    # Bij nieuwe entiteiten kan dit None zijn (later uitbouwen)
    entity_id = Column(String, nullable=True, index=True)

    # Waar komt dit voorstel vandaan? (bv. website park/manufacturer, RCDB, etc.)
    source_url = Column(String, nullable=True)

    # Vrije set voorgestelde velden (nu weinig, later meer)
    suggested_data = Column(JSON, nullable=False)

    # Optioneel: snapshot van huidige waarden (voor vergelijking)
    current_data = Column(JSON, nullable=True)

    # Workflow-status
    # "pending"  = moet nog beoordeeld worden
    # "accepted" = toegepast op de echte tabel
    # "rejected" = bewust afgewezen
    status = Column(String, nullable=False, default="pending")

    review_note = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

class SourcePage(Base):
    __tablename__ = "source_pages"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    entity_type = Column(String, nullable=False)  # manufacturer / park / coaster
    entity_id = Column(String, nullable=True)     # mag null zijn bij nieuwe suggestions
    url = Column(String, nullable=False)

    status_code = Column(String, nullable=True)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
    raw_html = Column(String, nullable=True)
    clean_text = Column(String, nullable=True)
