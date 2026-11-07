"""Reclaim superseded unreferenced facts; last-known resolution proofs stay valid."""

from sqlalchemy import delete, exists, or_, select

from .. import models as m


def prune(db, *, inventory=True):
    db.flush()
    # Association metadata is not a history store. Keep a retired association
    # only while a retained resolution explicitly depends on it.
    db.execute(
        delete(m.IPObservation).where(
            or_(
                m.IPObservation.present.is_(False),
                exists(
                    select(m.VMwareAddress.id).where(
                        m.VMwareAddress.id == m.IPObservation.vmware_id, m.VMwareAddress.present.is_(False)
                    )
                ),
                exists(
                    select(m.DHCPBinding.id).where(
                        m.DHCPBinding.id == m.IPObservation.dhcp_id, m.DHCPBinding.present.is_(False)
                    )
                ),
                exists(
                    select(m.GatewayBinding.id).where(
                        m.GatewayBinding.id == m.IPObservation.gateway_id, m.GatewayBinding.present.is_(False)
                    )
                ),
            ),
            ~exists(
                select(m.ResolutionField.result_id).where(
                    m.ResolutionField.source_link_id == m.IPObservation.id
                )
            ),
        )
    )
    for model, reference, columns in (
        (m.SwitchMacEntry, m.ResolutionConnection.mac_port_id, ()),
        (m.GatewayBinding, m.ResolutionField.gateway_id, (m.IPObservation.gateway_id,)),
        (m.DHCPBinding, m.IPObservation.dhcp_id, ()),
        (m.VMwareAddress, m.IPObservation.vmware_id, ()),
    ):
        if model is m.SwitchMacEntry and not inventory:
            continue
        conditions = [model.present.is_(False), ~exists(select(reference).where(reference == model.id))]
        conditions.extend(~exists(select(column).where(column == model.id)) for column in columns)
        db.execute(delete(model).where(*conditions).execution_options(synchronize_session=False))
    if inventory:
        db.execute(
            delete(m.Link)
            .where(
                m.Link.is_current.is_(False),
                m.Link.auto_add_excluded.is_(False),
                m.Link.source != "manual",
                m.Link.manual_remote_name.is_(None),
                m.Link.manual_remote_port.is_(None),
                m.Link.manual_remote_device_id.is_(None),
                ~exists(
                    select(m.ResolutionConnection.id).where(m.ResolutionConnection.neighbor_id == m.Link.id)
                ),
            )
            .execution_options(synchronize_session=False)
        )

    db.execute(
        delete(m.VMwareNIC)
        .where(
            ~exists(select(m.VMwareAddress.id).where(m.VMwareAddress.nic_id == m.VMwareNIC.id)),
            ~exists(
                select(m.ResolutionConnection.id).where(
                    m.ResolutionConnection.vmware_nic_id == m.VMwareNIC.id
                )
            ),
        )
        .execution_options(synchronize_session=False)
    )
    db.execute(
        delete(m.VMwareVM)
        .where(
            ~exists(select(m.VMwareNIC.id).where(m.VMwareNIC.vm_id == m.VMwareVM.id)),
        )
        .execution_options(synchronize_session=False)
    )
    db.execute(
        delete(m.VMwareHost)
        .where(
            ~exists(select(m.VMwareNIC.id).where(m.VMwareNIC.host_id == m.VMwareHost.id)),
            ~exists(select(m.VMwareVM.id).where(m.VMwareVM.host_id == m.VMwareHost.id)),
        )
        .execution_options(synchronize_session=False)
    )
    db.execute(
        delete(m.VMwareNetwork)
        .where(
            ~exists(select(m.VMwareNIC.id).where(m.VMwareNIC.network_id == m.VMwareNetwork.id)),
        )
        .execution_options(synchronize_session=False)
    )
