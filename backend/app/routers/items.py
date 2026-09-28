from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/items", tags=["items"])


@router.get("", response_model=list[schemas.ItemRead])
def list_items(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """List items with simple pagination."""
    return db.query(models.Item).offset(skip).limit(limit).all()


@router.post("", response_model=schemas.ItemRead, status_code=201)
def create_item(payload: schemas.ItemCreate, db: Session = Depends(get_db)):
    """Create a new item."""
    item = models.Item(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/{item_id}", response_model=schemas.ItemRead)
def get_item(item_id: int, db: Session = Depends(get_db)):
    """Fetch a single item by id."""
    item = db.get(models.Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: int, db: Session = Depends(get_db)):
    """Delete an item by id."""
    item = db.get(models.Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    db.delete(item)
    db.commit()
