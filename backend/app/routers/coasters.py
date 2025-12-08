from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models, schemas

router = APIRouter(prefix="/coasters", tags=["coasters"])


@router.get("/", response_model=List[schemas.CoasterRead])
def list_coasters(db: Session = Depends(get_db)):
    return db.query(models.Coaster).order_by(models.Coaster.name).all()


@router.get("/{coaster_id}", response_model=schemas.CoasterRead)
def get_coaster(coaster_id: str, db: Session = Depends(get_db)):
    coaster = (
        db.query(models.Coaster)
        .filter(models.Coaster.id == coaster_id)
        .first()
    )
    if not coaster:
        raise HTTPException(status_code=404, detail="Coaster not found")
    return coaster


@router.post(
    "/", response_model=schemas.CoasterRead, status_code=status.HTTP_201_CREATED
)
def create_coaster(data: schemas.CoasterCreate, db: Session = Depends(get_db)):
    coaster = models.Coaster(**data.dict())
    db.add(coaster)
    db.commit()
    db.refresh(coaster)
    return coaster


@router.put("/{coaster_id}", response_model=schemas.CoasterRead)
def update_coaster(
    coaster_id: str,
    data: schemas.CoasterUpdate,
    db: Session = Depends(get_db),
):
    coaster = (
        db.query(models.Coaster)
        .filter(models.Coaster.id == coaster_id)
        .first()
    )
    if not coaster:
        raise HTTPException(status_code=404, detail="Coaster not found")

    update_data = data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(coaster, key, value)

    db.commit()
    db.refresh(coaster)
    return coaster


@router.delete("/{coaster_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_coaster(coaster_id: str, db: Session = Depends(get_db)):
    coaster = (
        db.query(models.Coaster)
        .filter(models.Coaster.id == coaster_id)
        .first()
    )
    if not coaster:
        raise HTTPException(status_code=404, detail="Coaster not found")

    db.delete(coaster)
    db.commit()
    return
