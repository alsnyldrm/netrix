from fastapi import APIRouter, Depends

from ..core import db_session
from ..identity.security import admin, current_user, operator
from . import scan_schedules as service
from .schemas import ScanGroupInput

router = APIRouter(prefix="/api/v1/ipam/scan-groups")


@router.get("")
def groups(user=Depends(current_user), db=Depends(db_session)):
    return service.catalog(db)


@router.post("", status_code=201)
def create(payload: ScanGroupInput, user=Depends(operator), db=Depends(db_session)):
    return service.save(db, payload, user)


@router.put("/{id}")
def update(id: str, payload: ScanGroupInput, user=Depends(operator), db=Depends(db_session)):
    return service.save(db, payload, user, id)


@router.delete("/{id}", status_code=204)
def remove(id: str, user=Depends(admin), db=Depends(db_session)):
    service.remove(db, id, user)


@router.post("/{id}/scan", status_code=202)
def start(id: str, user=Depends(operator), db=Depends(db_session)):
    return service.start(db, id, user)


@router.get("/{id}/runs")
def history(id: str, user=Depends(current_user), db=Depends(db_session)):
    return service.history(db, id)
