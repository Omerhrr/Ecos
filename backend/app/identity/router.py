from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.identity import models as m

router = APIRouter(tags=["identity"])


@router.get("/orgs")
def list_orgs(db: Session = Depends(get_db)):
    rows = db.query(m.Organization).all()
    return [
        {
            "id": o.id, "name": o.name, "type": o.type,
            "country": o.country, "currency": o.currency,
        }
        for o in rows
    ]


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    rows = db.query(m.User).all()
    return [
        {"id": u.id, "org_id": u.org_id, "name": u.name, "email": u.email, "role": u.role}
        for u in rows
    ]
