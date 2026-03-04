from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..database import get_db
from ..models.resource import Resource
from ..schemas import ResourceRead

router = APIRouter(prefix="/resources", tags=["resources"])


@router.get("", response_model=list[ResourceRead])
def list_resources(db: Session = Depends(get_db)):
    return db.exec(select(Resource)).all()


@router.get("/{resource_id}", response_model=ResourceRead)
def get_resource(resource_id: int, db: Session = Depends(get_db)):
    resource = db.get(Resource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    return resource


@router.get("/by-name/{name}", response_model=ResourceRead)
def get_resource_by_name(name: str, db: Session = Depends(get_db)):
    resource = db.exec(
        select(Resource).where(Resource.name == name)
    ).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    return resource


@router.get("/{resource_id}/granularity")
def get_granularity(resource_id: int, db: Session = Depends(get_db)):
    resource = db.get(Resource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    return {"granularity": resource.granularity}
