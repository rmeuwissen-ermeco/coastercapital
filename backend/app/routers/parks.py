from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models, schemas

router = APIRouter(prefix="/parks", tags=["parks"])


@router.get("/", response_model=List[schemas.ParkRead])
def list_parks(db: Session = Depends(get_db)):
    return db.query(models.Park).order_by(models.Park.name).all()


@router.get("/{park_id}", response_model=schemas.ParkRead)
def get_park(park_id: str, db: Session = Depends(get_db)):
    park = db.query(models.Park).filter(models.Park.id == park_id).first()
    if not park:
        raise HTTPException(status_code=404, detail="Park not found")
    return park


@router.post("/", response_model=schemas.ParkRead, status_code=status.HTTP_201_CREATED)
def create_park(data: schemas.ParkCreate, db: Session = Depends(get_db)):
    park = models.Park(**data.dict())
    db.add(park)
    db.commit()
    db.refresh(park)
    return park


@router.put("/{park_id}", response_model=schemas.ParkRead)
def update_park(
    park_id: str, data: schemas.ParkUpdate, db: Session = Depends(get_db)
):
    park = db.query(models.Park).filter(models.Park.id == park_id).first()
    if not park:
        raise HTTPException(status_code=404, detail="Park not found")

    update_data = data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(park, key, value)

    db.commit()
    db.refresh(park)
    return park


@router.delete("/{park_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_park(park_id: str, db: Session = Depends(get_db)):
    park = db.query(models.Park).filter(models.Park.id == park_id).first()
    if not park:
        raise HTTPException(status_code=404, detail="Park not found")

    db.delete(park)
    db.commit()
    return
