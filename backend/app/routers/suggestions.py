from typing import List, Optional
from typing import Literal

from datetime import datetime

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models, schemas

router = APIRouter(prefix="/suggestions", tags=["suggestions"])


# Mapping van entity_type -> SQLAlchemy-model
ENTITY_MODEL_MAP = {
    "manufacturer": models.Manufacturer,
    "park": models.Park,
    "coaster": models.Coaster,
}


class SuggestionFieldAction(BaseModel):
    field: str
    action: Literal["accept", "reject"]


@router.post(
    "/{suggestion_id}/fields",
    response_model=schemas.DataSuggestionRead,
)
def handle_suggestion_field(
    suggestion_id: str,
    payload: SuggestionFieldAction,
    db: Session = Depends(get_db),
):
    """
    Keur één veld van een DataSuggestion goed of af.

    - action == "accept" -> waarde wordt op het entity-record gezet.
    - action == "reject" -> veld wordt verwijderd uit suggested_data.
    - In beide gevallen wordt het veld uit suggested_data gehaald.
    - Als er geen velden meer overblijven:
        - status = 'accepted' of 'rejected' (afhankelijk van laatste actie)
        - reviewed_at wordt gezet.
    """
    suggestion = (
        db.query(models.DataSuggestion)
        .filter(models.DataSuggestion.id == suggestion_id)
        .first()
    )

    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion niet gevonden")

    if suggestion.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Suggestion heeft status '{suggestion.status}', alleen 'pending' kan worden bewerkt.",
        )

    suggested = suggestion.suggested_data or {}
    current = suggestion.current_data or {}

    if payload.field not in suggested:
        raise HTTPException(
            status_code=400,
            detail=f"Veld '{payload.field}' niet aanwezig in suggested_data",
        )

    field = payload.field
    action = payload.action
    new_value = suggested[field]

    # Als er geaccepteerd wordt, moet dit naar de echte entity
    if action == "accept":
        model_cls = ENTITY_MODEL_MAP.get(suggestion.entity_type)
        if model_cls is None:
            raise HTTPException(
                status_code=400,
                detail=f"Onbekend entity_type '{suggestion.entity_type}'",
            )

        entity = (
            db.query(model_cls)
            .filter(model_cls.id == suggestion.entity_id)
            .first()
        )
        if entity is None:
            raise HTTPException(
                status_code=404,
                detail="Doelrecord niet gevonden",
            )

        if not hasattr(entity, field):
            raise HTTPException(
                status_code=400,
                detail=f"Entity heeft geen veld '{field}'",
            )

        # Nieuwe waarde op het entity-record zetten
        setattr(entity, field, new_value)

        # current_data bijwerken zodat het snapshot klopt
        current[field] = new_value

        db.add(entity)

    # In beide gevallen: veld uit suggested_data halen
    suggested.pop(field, None)

    suggestion.current_data = current
    suggestion.suggested_data = suggested

    # Als er geen velden meer over zijn, status afronden
    if not suggestion.suggested_data:
        suggestion.status = "accepted" if action == "accept" else "rejected"
        suggestion.reviewed_at = datetime.utcnow()

    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)

    return suggestion


@router.get("/", response_model=List[schemas.DataSuggestionRead])
def list_suggestions(
    status_filter: Optional[str] = Query(
        None,
        description="Filter op status: pending, accepted, rejected",
        alias="status",
    ),
    db: Session = Depends(get_db),
):
    """
    Lijst van AI-voorstellen.

    Optioneel filter op status via ?status=pending / accepted / rejected.
    """
    query = db.query(models.DataSuggestion).order_by(
        models.DataSuggestion.created_at.desc()
    )
    if status_filter:
        query = query.filter(models.DataSuggestion.status == status_filter)
    return query.all()


@router.get("/{suggestion_id}", response_model=schemas.DataSuggestionRead)
def get_suggestion(suggestion_id: str, db: Session = Depends(get_db)):
    suggestion = (
        db.query(models.DataSuggestion)
        .filter(models.DataSuggestion.id == suggestion_id)
        .first()
    )
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return suggestion


@router.post(
    "/", response_model=schemas.DataSuggestionRead, status_code=status.HTTP_201_CREATED
)
def create_suggestion(
    data: schemas.DataSuggestionCreate, db: Session = Depends(get_db)
):
    """
    Endpoint voor crawler/AI (of test-tools) om een nieuw voorstel te registreren.
    """
    suggestion = models.DataSuggestion(
        entity_type=data.entity_type,
        entity_id=data.entity_id,
        source_url=data.source_url,
        suggested_data=data.suggested_data,
        current_data=data.current_data,
        status="pending",
    )
    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)
    return suggestion


@router.post(
    "/{suggestion_id}/review",
    response_model=schemas.DataSuggestionRead,
)
def review_suggestion(
    suggestion_id: str,
    review: schemas.DataSuggestionReview,
    db: Session = Depends(get_db),
):
    """
    Oud 'alles of niets'-review endpoint.

    - action = 'accept' -> alle suggested_data velden toepassen + status 'accepted'
    - action = 'reject' -> alleen status 'rejected'

    NB: de nieuwe veld-per-veld goedkeuring gaat via /{suggestion_id}/fields.
    """
    suggestion = (
        db.query(models.DataSuggestion)
        .filter(models.DataSuggestion.id == suggestion_id)
        .first()
    )
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    if suggestion.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Suggestion is already {suggestion.status}, alleen 'pending' kan beoordeeld worden.",
        )

    suggestion.review_note = review.review_note
    suggestion.reviewed_at = datetime.utcnow()

    # REJECT
    if review.action == "reject":
        suggestion.status = "rejected"
        db.commit()
        db.refresh(suggestion)
        return suggestion

    # ACCEPT -> alle velden toepassen
    model_cls = ENTITY_MODEL_MAP.get(suggestion.entity_type)
    if not model_cls:
        raise HTTPException(
            status_code=400,
            detail=f"Onbekend entity_type: {suggestion.entity_type}",
        )

    entity = (
        db.query(model_cls)
        .filter(model_cls.id == suggestion.entity_id)
        .first()
    )
    if not entity:
        raise HTTPException(
            status_code=404,
            detail=f"Doel-entiteit (type {suggestion.entity_type}) niet gevonden.",
        )

    forbidden_keys = {"id", "created_at", "updated_at"}

    for key, value in (suggestion.suggested_data or {}).items():
        if key in forbidden_keys:
            continue
        if not hasattr(entity, key):
            continue
        setattr(entity, key, value)

    db.add(entity)
    suggestion.status = "accepted"
    db.add(suggestion)

    db.commit()
    db.refresh(suggestion)
    return suggestion
