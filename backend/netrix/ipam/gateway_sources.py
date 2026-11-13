"""Read canonical gateway bindings shared by manual and scheduled IPAM."""

from sqlalchemy import select

from .. import models as m


def bindings_query(vrf_id, devices):
    return select(m.GatewayBinding).where(
        m.GatewayBinding.vrf_id == vrf_id,
        m.GatewayBinding.present.is_(True),
        m.GatewayBinding.device_id.in_(
            [id for id, d in devices.items() if d.is_gateway or d.kind in ("router", "firewall")]
        ),
    )


def binding_view(binding, device):
    return {
        "device_id": device.id,
        "device_name": device.name,
        "mac_address": binding.mac_address,
        "observed_at": binding.observed_at.isoformat(),
        "source": "gateway",
    }
