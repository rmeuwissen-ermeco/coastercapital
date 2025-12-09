from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import requests
from bs4 import BeautifulSoup

from ..db import get_db
from .. import models
from .utils import create_suggestion_diff

router = APIRouter(prefix="/extract", tags=["extract"])


@router.post("/manufacturer/{manufacturer_id}")
def extract_manufacturer(manufacturer_id: str, db: Session = Depends(get_db)):
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
            detail="Geen website_url bekend voor deze manufacturer."
        )

    url = manufacturer.website_url

    # ------------------------------
    # 1. HTML ophalen
    # ------------------------------
    try:
        response = requests.get(url, timeout=10)
        status_code = str(response.status_code)
        raw_html = response.text
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fout bij ophalen URL: {e}")

    # ------------------------------
    # 2. Clean text maken
    # ------------------------------
    soup = BeautifulSoup(raw_html, "html.parser")
    clean_text = soup.get_text(separator="\n").strip()

    # ------------------------------
    # 3. SourcePage opslaan
    # ------------------------------
    source_page = models.SourcePage(
        entity_type="manufacturer",
        entity_id=manufacturer.id,
        url=url,
        status_code=status_code,
        raw_html=raw_html[:10000],   # limiteren
        clean_text=clean_text[:10000],
    )
    db.add(source_page)
    db.commit()
    db.refresh(source_page)

    # ------------------------------
    # 4. Dummy “extractie” — hier komt later AI
    #    Voor nu: haal <title> → name
    # ------------------------------
    title_tag = soup.find("title")
    new_name = title_tag.get_text().strip() if title_tag else None

    suggested = {}

    if new_name and new_name != manufacturer.name:
        suggested["name"] = new_name

    if not suggested:
        return {
            "message": "Geen nieuwe informatie gevonden in deze URL.",
            "source_page_id": source_page.id,
        }

    # ------------------------------
    # 5. Suggestion genereren
    # ------------------------------
    suggestion = models.DataSuggestion(
        entity_type="manufacturer",
        entity_id=manufacturer.id,
        current_data={
            "name": manufacturer.name,
            "country_code": manufacturer.country_code,
            "website_url": manufacturer.website_url,
            "notes": manufacturer.notes,
        },
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
