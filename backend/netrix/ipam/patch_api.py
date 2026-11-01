from fastapi import APIRouter, Depends

from ..core import db_session
from ..identity.security import current_user, operator
from . import patch_panels as service
from .schemas import PatchPanelInput, PatchPortInput

router = APIRouter(prefix="/api/v1")


@router.post("/ipam/cabinets/{id}/patch-panels", status_code=201)
def create(id: str, payload: PatchPanelInput, user=Depends(operator), db=Depends(db_session)):
    return service.save_panel(db, id, payload, user)


@router.put("/ipam/cabinets/{id}/patch-panels/{panel_id}")
def update(id: str, panel_id: str, payload: PatchPanelInput, user=Depends(operator), db=Depends(db_session)):
    return service.save_panel(db, id, payload, user, panel_id)


@router.delete("/ipam/cabinets/{id}/patch-panels/{panel_id}", status_code=204)
def remove(id: str, panel_id: str, user=Depends(operator), db=Depends(db_session)):
    service.remove_panel(db, id, panel_id, user)


@router.get("/ipam/cabinets/{id}/patch-panels/{panel_id}/ports")
def ports(id: str, panel_id: str, user=Depends(current_user), db=Depends(db_session)):
    return service.ports(db, id, panel_id)


@router.put("/ipam/cabinets/{id}/patch-panels/{panel_id}/ports/{port_id}")
def save_port(
    id: str,
    panel_id: str,
    port_id: str,
    payload: PatchPortInput,
    user=Depends(operator),
    db=Depends(db_session),
):
    return service.save_port(db, id, panel_id, port_id, payload, user)


@router.get("/devices/{id}/patch-ports")
def device_ports(id: str, user=Depends(current_user), db=Depends(db_session)):
    return service.device_ports(db, id)
