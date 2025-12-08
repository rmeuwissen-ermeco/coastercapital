from typing import List, Optional

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


@router.get("/", response_model=List[schemas.DataSuggestionRead])
def list_suggestions(
    status_filter: Optional[str] = Query(
        None,
        description="Filter op status: pending, accepted, rejected",
        alias="status",
    ),
    db: Session = Depends(get_db),
):
    query = db.query(models.DataSuggestion).order_by(models.DataSuggestion.created_at.desc())
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
    "/{suggestion_id}/review", response_model=schemas.DataSuggestionRead
)
def review_suggestion(
    suggestion_id: str,
    review: schemas.DataSuggestionReview,
    db: Session = Depends(get_db),
):
    """
    Eén generiek review-endpoint:
    - action = 'accept' -> toepassen op echte entiteit (nieuw of bestaand) + status 'accepted'
    - action = 'reject' -> alleen status 'rejected'
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

    # Altijd: review_note + reviewed_at bijwerken
    from datetime import datetime as _dt

    suggestion.review_note = review.review_note
    suggestion.reviewed_at = _dt.now()

    # 1) REJECT
    if review.action == "reject":
        suggestion.status = "rejected"
        db.commit()
        db.refresh(suggestion)
        return suggestion

    # Vanaf hier: ACCEPT-logica
    # Bepaal het model op basis van entity_type
    model_cls = ENTITY_MODEL_MAP.get(suggestion.entity_type)
    if not model_cls:
        raise HTTPException(
            status_code=400,
            detail=f"Onbekend entity_type: {suggestion.entity_type}",
        )

    forbidden_keys = {"id", "created_at", "updated_at"}

    # 2) ACCEPT + entity_id == None -> nieuw record aanmaken
    if not suggestion.entity_id:
        # Nieuwe entiteit creëren
        entity = model_cls()  # id komt uit default in het model (uuid)

        for key, value in (suggestion.suggested_data or {}).items():
            if key in forbidden_keys:
                continue
            if not hasattr(entity, key):
                # Voor nu: onbekende velden negeren i.p.v. crashen
                continue
            setattr(entity, key, value)

        db.add(entity)
        db.commit()
        db.refresh(entity)

        # Suggestie koppelen aan nieuw record
        suggestion.entity_id = getattr(entity, "id", None)
        suggestion.status = "accepted"
        db.commit()
        db.refresh(suggestion)
        return suggestion

    # 3) ACCEPT + entity_id != None -> bestaand record updaten
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

    for key, value in (suggestion.suggested_data or {}).items():
        if key in forbidden_keys:
            continue
        if not hasattr(entity, key):
            continue
        setattr(entity, key, value)

    suggestion.status = "accepted"

    db.commit()
    db.refresh(suggestion)
    return suggestion

