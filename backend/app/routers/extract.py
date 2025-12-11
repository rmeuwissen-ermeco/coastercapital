from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models
from ..extractors.manufacturer_extractor import ManufacturerExtractor
from ..extractors.park_extractor import ParkExtractor


router = APIRouter(prefix="/extract", tags=["extract"])


@router.post("/manufacturer/{manufacturer_id}")
def extract_manufacturer(manufacturer_id: str, db: Session = Depends(get_db)):
    """
    Wrapper om de ManufacturerExtractor te draaien.
    De extractor verzorgt:
    - het ophalen van de officiële site
    - het opslaan van SourcePages (official + Wikipedia + RCDB)
    - AI-call 1 (feiten & kernwoorden)
    - AI-call 2 (multi-source samenvatting)
    - het aanmaken van een DataSuggestion
    """
    manufacturer = (
        db.query(models.Manufacturer)
        .filter(models.Manufacturer.id == manufacturer_id)
        .first()
    )

    if not manufacturer:
        raise HTTPException(status_code=404, detail="Manufacturer niet gevonden")

    if not manufacturer.website_url:
        raise HTTPException(
            status_code=400,
            detail="Geen website_url bekend voor deze manufacturer.",
        )

    extractor = ManufacturerExtractor(db=db, manufacturer=manufacturer)

    try:
        result = extractor.run()
    except ValueError as e:
        # Bijvoorbeeld: geen website_url of andere valideer-fout
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extractie-fout: {e}")

    return result


@router.post("/park/{park_id}")
def extract_park(park_id: str, db: Session = Depends(get_db)):
    """
    Wrapper om de ParkExtractor te draaien.
    AI-samenvatting is standaard, heuristiek is backup.
    Resultaat wordt vastgelegd als DataSuggestion.
    """
    park = (
        db.query(models.Park)
        .filter(models.Park.id == park_id)
        .first()
    )

    if not park:
        raise HTTPException(status_code=404, detail="Park niet gevonden")

    if not park.website_url:
        raise HTTPException(
            status_code=400,
            detail="Geen website_url bekend voor dit park."
        )

    extractor = ParkExtractor(db, park)

    try:
        result = extractor.run()
    except ValueError as e:
        # Bijvoorbeeld: geen website_url
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extractie-fout: {e}")

    return result
