from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models, schemas

router = APIRouter(prefix="/manufacturers", tags=["manufacturers"])


@router.get("/", response_model=List[schemas.ManufacturerRead])
def list_manufacturers(db: Session = Depends(get_db)):
    return db.query(models.Manufacturer).order_by(models.Manufacturer.name).all()


@router.get("/{manufacturer_id}", response_model=schemas.ManufacturerRead)
def get_manufacturer(manufacturer_id: str, db: Session = Depends(get_db)):
    manufacturer = (
        db.query(models.Manufacturer)
        .filter(models.Manufacturer.id == manufacturer_id)
        .first()
    )
    if not manufacturer:
        raise HTTPException(status_code=404, detail="Manufacturer not found")
    return manufacturer


@router.post(
    "/", response_model=schemas.ManufacturerRead, status_code=status.HTTP_201_CREATED
)
def create_manufacturer(
    data: schemas.ManufacturerCreate, db: Session = Depends(get_db)
):
    manufacturer = models.Manufacturer(**data.dict())
    db.add(manufacturer)
    db.commit()
    db.refresh(manufacturer)
    return manufacturer


@router.put("/{manufacturer_id}", response_model=schemas.ManufacturerRead)
def update_manufacturer(
    manufacturer_id: str,
    data: schemas.ManufacturerUpdate,
    db: Session = Depends(get_db),
):
    manufacturer = (
        db.query(models.Manufacturer)
        .filter(models.Manufacturer.id == manufacturer_id)
        .first()
    )
    if not manufacturer:
        raise HTTPException(status_code=404, detail="Manufacturer not found")

    update_data = data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(manufacturer, key, value)

    db.commit()
    db.refresh(manufacturer)
    return manufacturer


@router.delete("/{manufacturer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_manufacturer(manufacturer_id: str, db: Session = Depends(get_db)):
    manufacturer = (
        db.query(models.Manufacturer)
        .filter(models.Manufacturer.id == manufacturer_id)
        .first()
    )
    if not manufacturer:
        raise HTTPException(status_code=404, detail="Manufacturer not found")

    db.delete(manufacturer)
    db.commit()
    return
