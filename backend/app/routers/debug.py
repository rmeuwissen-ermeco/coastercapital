from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models, schemas

router = APIRouter(prefix="/debug", tags=["debug"])


@router.post(
    "/generate_suggestion/manufacturer/{manufacturer_id}",
    response_model=schemas.DataSuggestionRead,
    status_code=status.HTTP_201_CREATED,
)
def generate_manufacturer_suggestion(
    manufacturer_id: str,
    db: Session = Depends(get_db),
):
    """
    Debug/ontwikkel-endpoint:
    Maak op basis van een bestaande manufacturer een DataSuggestion
    met kleine wijzigingen (naam, landcode, website).
    """

    manufacturer = (
        db.query(models.Manufacturer)
        .filter(models.Manufacturer.id == manufacturer_id)
        .first()
    )
    if not manufacturer:
        raise HTTPException(status_code=404, detail="Manufacturer not found")

    # Kleine, deterministische "AI-achtige" wijziging:
    orig_name = manufacturer.name or "Onbekende manufacturer"
    if orig_name.endswith(" (AI)"):
        new_name = orig_name
    else:
        new_name = f"{orig_name} (AI)"

    orig_country = manufacturer.country_code or "NL"
    new_country = "DE" if orig_country != "DE" else "NL"

    orig_website = manufacturer.website_url or ""
    if orig_website:
        new_website = orig_website
    else:
        new_website = f"https://example.com/manufacturer/{manufacturer.id}"

    suggested_data = {
        "name": new_name,
        "country_code": new_country,
        "website_url": new_website,
    }

    current_data = {
        "name": manufacturer.name,
        "country_code": manufacturer.country_code,
        "website_url": manufacturer.website_url,
    }

    suggestion = models.DataSuggestion(
        entity_type="manufacturer",
        entity_id=manufacturer.id,
        source_url=manufacturer.website_url,
        suggested_data=suggested_data,
        current_data=current_data,
        status="pending",
    )

    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)

    return suggestion


@router.post(
    "/generate_suggestion/park/{park_id}",
    response_model=schemas.DataSuggestionRead,
    status_code=status.HTTP_201_CREATED,
)
def generate_park_suggestion(
    park_id: str,
    db: Session = Depends(get_db),
):
    """
    Debug/ontwikkel-endpoint:
    Maak op basis van een bestaand park een DataSuggestion
    met kleine wijzigingen (naam, landcode, website).
    """

    park = db.query(models.Park).filter(models.Park.id == park_id).first()
    if not park:
        raise HTTPException(status_code=404, detail="Park not found")

    orig_name = park.name or "Onbekend park"
    if orig_name.endswith(" (AI)"):
        new_name = orig_name
    else:
        new_name = f"{orig_name} (AI)"

    orig_country = park.country_code or "NL"
    new_country = "DE" if orig_country != "DE" else "NL"

    orig_website = park.website_url or ""
    if orig_website:
        new_website = orig_website
    else:
        new_website = f"https://example.com/park/{park.id}"

    suggested_data = {
        "name": new_name,
        "country_code": new_country,
        "website_url": new_website,
    }

    current_data = {
        "name": park.name,
        "country_code": park.country_code,
        "website_url": park.website_url,
    }

    suggestion = models.DataSuggestion(
        entity_type="park",
        entity_id=park.id,
        source_url=park.website_url,
        suggested_data=suggested_data,
        current_data=current_data,
        status="pending",
    )

    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)

    return suggestion

@router.post(
    "/generate_suggestion/coaster/{coaster_id}",
    response_model=schemas.DataSuggestionRead,
    status_code=status.HTTP_201_CREATED,
)
def generate_coaster_suggestion(
    coaster_id: str,
    db: Session = Depends(get_db),
):
    """
    Debug/ontwikkel-endpoint:
    Maak op basis van een bestaande coaster een DataSuggestion
    met kleine wijzigingen (naam, status, hoogte).
    """

    coaster = (
        db.query(models.Coaster)
        .filter(models.Coaster.id == coaster_id)
        .first()
    )
    if not coaster:
        raise HTTPException(status_code=404, detail="Coaster not found")

    # Naam: suffix toevoegen (net als bij parks/manufacturers)
    orig_name = coaster.name or "Onbekende coaster"
    if orig_name.endswith(" (AI)"):
        new_name = orig_name
    else:
        new_name = f"{orig_name} (AI)"

    # Status licht variëren binnen de bekende set
    allowed_statuses = [
        "Operating",
        "Under construction",
        "Standing but not operating",
        "In storage",
    ]
    orig_status = coaster.status or "Operating"
    try:
        idx = allowed_statuses.index(orig_status)
        new_status = allowed_statuses[(idx + 1) % len(allowed_statuses)]
    except ValueError:
        # Onbekende status? Schakel dan naar Operating
        new_status = "Operating"

    # Hoogte iets aanpassen
    orig_height = coaster.height_m or 30.0
    new_height = round(float(orig_height) + 1.0, 1)

    suggested_data = {
        "name": new_name,
        "status": new_status,
        "height_m": new_height,
    }

    current_data = {
        "name": coaster.name,
        "status": coaster.status,
        "height_m": coaster.height_m,
    }

    suggestion = models.DataSuggestion(
        entity_type="coaster",
        entity_id=coaster.id,
        source_url=None,  # later kunnen we hier bv. rcdb_url toevoegen
        suggested_data=suggested_data,
        current_data=current_data,
        status="pending",
    )

    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)

    return suggestion
