from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import requests
from bs4 import BeautifulSoup

from ..db import get_db
from .. import models
from .utils import create_suggestion_diff
from ..extractors.manufacturer_extractor import ManufacturerExtractor
from ..extractors.park_extractor import ParkExtractor


router = APIRouter(prefix="/extract", tags=["extract"])


@router.post("/manufacturer/{manufacturer_id}")
def extract_manufacturer(manufacturer_id: str, db: Session = Depends(get_db)):
    # 1) Manufacturer ophalen
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

    url = manufacturer.website_url

    # 2) HTML ophalen
    try:
        response = requests.get(url, timeout=10)
        status_code = str(response.status_code)
        raw_html = response.text
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fout bij ophalen URL: {e}")

    # 3) Clean text maken
    soup = BeautifulSoup(raw_html, "html.parser")
    clean_text = soup.get_text(separator="\n").strip()

    # 4) SourcePage loggen
    source_page = models.SourcePage(
        entity_type="manufacturer",
        entity_id=manufacturer.id,
        url=url,
        status_code=status_code,
        raw_html=raw_html[:10000],  # limiteren zodat de DB niet ontploft
        clean_text=clean_text[:10000],
    )
    db.add(source_page)
    db.commit()
    db.refresh(source_page)

    # 5) Huidige data + extractor draaien
    current_data = {
        "name": manufacturer.name,
        "country_code": manufacturer.country_code,
        "website_url": manufacturer.website_url,
        "notes": manufacturer.notes,
    }

    extractor = ManufacturerExtractor()
    extracted = extractor.extract(soup, clean_text)

    # Alleen velden meenemen die echt veranderen
    suggested = create_suggestion_diff(current_data, extracted)

    if not suggested:
        return {
            "message": "Geen nieuwe informatie gevonden in deze URL.",
            "source_page_id": source_page.id,
        }

    # 6) Suggestion aanmaken
    suggestion = models.DataSuggestion(
        entity_type="manufacturer",
        entity_id=manufacturer.id,
        current_data=current_data,
        suggested_data=suggested,
        source_url=url,
    )

    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)

    return {
        "message": "Extractie voltooid",
        "suggestion_id": suggestion.id,
        "source_page_id": source_page.id,
        "suggested_data": suggested,
    }

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
