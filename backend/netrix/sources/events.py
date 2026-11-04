"""Persist transient protocol projections through the canonical repositories."""

from sqlalchemy import event
from sqlalchemy.orm import Session


@event.listens_for(Session, "before_flush")
def normalize_sources(db, context, instances):
    from .. import models as m
    from . import neighbors, network, records, resolutions

    db.info.pop("source_links_by_ip", None)
    db.info.pop("resolution_views", None)
    # Parent identities are explicit before inserts, including migration batches.
    pending = list(db.new) + list(db.dirty)
    for row in pending:
        if (
            isinstance(row, (m.IPObservation, m.IPAMNetworkState, m.Observation, m.Link, m.IPAMResult))
            and not row.id
        ):
            row.id = m.uid()
    with db.no_autoflush:
        for child in pending:
            if isinstance(child, m.SourcePort):
                if child.state:
                    child.state.updated_at = m.now()
            elif isinstance(child, m.SwitchMacEntry) and child.snapshot_id:
                state = db.get(m.IPAMNetworkState, child.snapshot_id)
                if state:
                    state.updated_at = m.now()
        for row in pending:
            if isinstance(row, m.Observation) and "_pending_evidence" in row.__dict__:
                data = row.__dict__.pop("_pending_evidence")
                row.failed = bool(data.get("failed"))
                row.error_class = str(data.get("error_class") or "")[:80]
                state = network.state_for(db, row.device_id, row.address)
                row.network_state = state
                network.write(db, state, data, row.created_at or m.now())
            elif isinstance(row, m.IPAMNetworkState) and "_pending_evidence" in row.__dict__:
                legacy = row.__dict__.pop("_legacy_cache_context", None)
                if legacy:
                    device = db.get(m.Device, row.device_id)
                    row.read_context = [
                        legacy[0],
                        legacy[1],
                        legacy[2],
                        legacy[5],
                        legacy[6],
                        legacy[4],
                        device.config_port if device else 22,
                        device.ssh_trust_host_key if device else False,
                        None,
                        None,
                    ]
                network.write(db, row, row.__dict__.pop("_pending_evidence"), row.observed_at or m.now())
        for row in pending:
            if isinstance(row, m.Link) and any(
                k in row.__dict__
                for k in (
                    "_pending_evidence",
                    "_pending_remote_name",
                    "_pending_remote_port",
                    "_pending_interface_name",
                )
            ):
                neighbors.write(db, row)
            elif isinstance(row, m.IPObservation) and "_pending_data" in row.__dict__:
                records.write_observation(db, row, row.__dict__.pop("_pending_data"))
        for row in pending:
            if isinstance(row, m.IPAMResult) and "_pending_values" in row.__dict__:
                resolutions.write(db, row, row.__dict__.pop("_pending_values"))


@event.listens_for(Session, "after_transaction_end")
def clear_cache(db, transaction):
    if transaction.parent is None:
        db.info.pop("source_rows", None)
        db.info.pop("source_links_by_ip", None)
        db.info.pop("resolution_views", None)
