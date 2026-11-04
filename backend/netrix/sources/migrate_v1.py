"""Version 50 verified move. Reads legacy payloads only during Alembic upgrade.

No source backup is made. Source facts are normalized before legacy tables can be
removed. A failed parity check leaves legacy tables intact and aborts the upgrade.
"""

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .. import models as m
from . import neighbors, network, records, resolutions

LEGACY = (
    "ip_observations",
    "ipam_network_states",
    "ipam_results",
    "topology_links",
    "switch_mac_snapshots",
    "switch_mac_entries",
    "discovery_observations",
)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if isinstance(value, datetime) and not value.tzinfo else value


def entity(row, keys):
    return {k: utc(row[k]) for k in keys if k in row}


def transfer_and_verify(connection):
    metadata = sa.MetaData()
    old = {
        name: sa.Table(
            name,
            metadata,
            *(
                sa.Column(c, sa.JSON())
                for c in {
                    "ip_observations": ("data",),
                    "ipam_network_states": ("evidence",),
                    "ipam_results": ("values", "address_scope", "issues", "steps"),
                    "topology_links": ("evidence",),
                    "switch_mac_snapshots": ("evidence", "read_context"),
                    "discovery_observations": ("evidence",),
                }.get(name, ())
            ),
            autoload_with=connection,
        )
        for name in LEGACY
        if sa.inspect(connection).has_table(name)
    }
    if not old:
        return
    print("NETRIX source transfer: normalizing latest discovery facts", flush=True)
    with Session(connection, expire_on_commit=False) as db:
        # Read latest successful per device/source first. Historical payloads are
        # superseded observations, not additional copies of current source facts.
        discovery = old.get("discovery_observations")
        if discovery is not None:
            metadata_rows = list(
                connection.execute(
                    sa.select(*(c for c in discovery.c if c.name != "evidence")).order_by(
                        discovery.c.created_at.desc(), discovery.c.id
                    )
                ).mappings()
            )
            seen = set()
            for row in metadata_rows:
                key = (row["device_id"], row["address"], row["source"])
                if key in seen:
                    continue
                data = (
                    connection.scalar(sa.select(discovery.c.evidence).where(discovery.c.id == row["id"]))
                    or {}
                )
                if data.get("failed"):
                    continue
                seen.add(key)
                state = network.state_for(db, row["device_id"], row["address"])
                network.write(db, state, data, utc(row["created_at"]))
                db.flush()
            # Journal rows contain metadata only. Batch them without loading the
            # canonical object graph once for each historical read.
            existing_ids = set(db.scalars(sa.select(m.Observation.id)))
            states = {(v.device_id, v.address): v.id for v in db.scalars(sa.select(m.IPAMNetworkState))}
            # Extract historical status in bounded PK batches; a single JSON
            # filter/window over the entire old history can exceed DB timeouts.
            flags = {}
            all_ids = [row["id"] for row in metadata_rows]
            for start in range(0, len(all_ids), 100):
                flags.update(
                    {
                        row.id: (bool(row.failed), str(row.error_class or "")[:80])
                        for row in connection.execute(
                            sa.select(
                                discovery.c.id,
                                discovery.c.evidence["failed"].as_boolean().label("failed"),
                                discovery.c.evidence["error_class"].as_string().label("error_class"),
                            ).where(discovery.c.id.in_(all_ids[start : start + 100]))
                        )
                    }
                )
            batch = []
            for row in metadata_rows:
                if row["id"] in existing_ids:
                    continue
                key = (row["device_id"], row["address"])
                if key not in states:
                    state = network.state_for(db, *key)
                    db.flush()
                    states[key] = state.id
                values = entity(
                    row,
                    (
                        "id",
                        "created_at",
                        "updated_at",
                        "job_id",
                        "device_id",
                        "address",
                        "source",
                        "confidence",
                    ),
                )
                values.update(
                    network_state_id=states[key],
                    failed=flags[row["id"]][0],
                    error_class=flags[row["id"]][1],
                )
                batch.append(values)
                if len(batch) == 500:
                    connection.execute(m.Observation.__table__.insert(), batch)
                    batch = []
            if batch:
                connection.execute(m.Observation.__table__.insert(), batch)
            assert_count(connection, discovery, m.Observation.__table__)
        print("NETRIX source transfer: normalizing shared network snapshots", flush=True)
        for name in ("switch_mac_snapshots", "ipam_network_states"):
            table = old.get(name)
            if table is None:
                continue
            for row in connection.execute(sa.select(table)).mappings():
                device = db.get(m.Device, row["device_id"])
                state = network.state_for(db, row["device_id"], row.get("address") or device.management_ip)
                if row["observed_at"]:
                    data = dict(row["evidence"] or {})
                    if row.get("read_context"):
                        data["read_context"] = row["read_context"]
                    network.write(db, state, data, utc(row["observed_at"]))
                attempted = utc(row.get("attempted_at"))
                if attempted and (not state.attempted_at or attempted >= state.attempted_at):
                    state.attempted_at = attempted
                    state.healthy = bool(row["healthy"])
                    state.error_class = str(row.get("error_class") or "")[:80]
                    state.job_id = row.get("job_id")
                db.flush()
        entries, snapshots = old.get("switch_mac_entries"), old.get("switch_mac_snapshots")
        print("NETRIX source transfer: verifying legacy MAC/port identities", flush=True)
        if entries is not None and snapshots is not None:
            # Canonical snapshots already own most of these facts. Index the
            # identity once instead of locking/loading the device and scanning
            # its entire FDB for each legacy row (tens of thousands in practice).
            db.flush()
            devices = {d.id: d for d in db.scalars(sa.select(m.Device))}
            states = {(s.device_id, s.address): s for s in db.scalars(sa.select(m.IPAMNetworkState))}
            facts = {
                s.id: {(e.fdb_id, e.mac_address, e.port): e for e in s.mac_entries} for s in states.values()
            }
            fids_by_state = {}
            for s in states.values():
                vids = {}
                for v in s.vlan_fdbs:
                    vids.setdefault(v.vlan_vid, set()).add(v.fdb_id)
                fids_by_state[s.id] = vids
            statement = sa.select(
                entries,
                snapshots.c.device_id,
                snapshots.c.observed_at.label("source_at"),
                snapshots.c.healthy,
            ).join(snapshots, snapshots.c.id == entries.c.snapshot_id)
            for position, row in enumerate(connection.execute(statement).mappings(), 1):
                device = devices[row["device_id"]]
                skey = (device.id, device.management_ip)
                state = states.get(skey)
                if state is None:
                    state = network.state_for(db, *skey)
                    db.flush()
                    states[skey] = state
                    facts[state.id], fids_by_state[state.id] = {}, {}
                fids = fids_by_state[state.id].get(row["vlan_vid"], set())
                fid = next(iter(fids)) if len(fids) == 1 else 0
                key = (fid, row["mac_address"], row["port"])
                fact = facts[state.id].get(key)
                if fact is None:
                    fact = m.SwitchMacEntry(
                        id=row["id"],
                        fdb_id=fid,
                        mac_address=row["mac_address"],
                        port=row["port"],
                        vrf_id=row["vrf_id"],
                        vlan_vid=row["vlan_vid"],
                        if_index=row["if_index"],
                        bridge_port=0,
                        status="3",
                        observed_at=utc(row["source_at"]) or utc(row["updated_at"]),
                        present=False,
                    )
                    state.mac_entries.append(fact)
                    facts[state.id][key] = fact
                if position % 500 == 0:
                    db.flush()
                if fact.mac_address != row["mac_address"] or fact.port != row["port"]:
                    raise RuntimeError("MAC/port transfer parity failed; legacy records preserved")
            db.flush()
        # Operator corrections and exclusions are authoritative. Import after
        # snapshots so discovery cannot retire or replace them during transfer.
        links = old.get("topology_links")
        print("NETRIX source transfer: preserving neighbor identities and operator choices", flush=True)
        if links is not None:
            for row in connection.execute(sa.select(links)).mappings():
                device = db.get(m.Device, row["device_id"])
                state = network.state_for(db, device.id, device.management_ip)
                port = network.port_for(state, row["interface_name"])
                db.flush()
                link = db.get(m.Link, row["id"])
                if not link:
                    # Remove a snapshot-derived duplicate of this same neighbor;
                    # the stable legacy link ID owns operator preferences.
                    import hashlib

                    identity = hashlib.sha256(
                        (row["remote_name"] + "\0" + row["remote_port"]).encode()
                    ).hexdigest()
                    duplicate = db.scalar(
                        sa.select(m.Link).where(
                            m.Link.device_id == device.id,
                            m.Link.port_id == port.id,
                            m.Link.identity_key == identity,
                        )
                    )
                    if duplicate:
                        db.delete(duplicate)
                        db.flush()
                    link = m.Link(id=row["id"], device_id=device.id, local_port=port)
                    db.add(link)
                for key in (
                    "remote_device_id",
                    "manual_remote_name",
                    "manual_remote_port",
                    "manual_remote_device_id",
                    "source",
                    "confidence",
                    "auto_add_excluded",
                    "is_current",
                    "last_seen_at",
                    "created_at",
                    "updated_at",
                ):
                    if key in row:
                        setattr(link, key, utc(row[key]))
                link.interface_name, link.remote_name, link.remote_port = (
                    row["interface_name"],
                    row["remote_name"],
                    row["remote_port"],
                )
                link.evidence = row["evidence"] or {}
                neighbors.write(db, link)
                db.flush()
                if (link.interface_name, link.remote_name, link.remote_port) != (
                    row["interface_name"],
                    row["remote_name"],
                    row["remote_port"],
                ):
                    raise RuntimeError("Neighbor transfer parity failed; legacy records preserved")
        table = old.get("ip_observations")
        print("NETRIX source transfer: normalizing IP source references", flush=True)
        if table is not None:
            for row in connection.execute(sa.select(table).order_by(table.c.observed_at)).mappings():
                link = db.get(m.IPObservation, row["id"])
                if not link:
                    link = m.IPObservation(
                        **entity(
                            row,
                            (
                                "id",
                                "created_at",
                                "updated_at",
                                "address_id",
                                "source",
                                "source_key",
                                "observed_at",
                            ),
                        )
                    )
                    db.add(link)
                records.write_observation(db, link, row["data"] or {})
                db.flush()
                expected = row["data"] or {}
                actual = link.data
                for field in ("hostname", "mac_address", "operating_system", "reachability"):
                    if expected.get(field) and actual.get(field) != expected[field]:
                        raise RuntimeError(
                            f"Source transfer parity failed for {row['source']}/{field}; legacy records preserved"
                        )
            assert_count(connection, table, m.IPObservation.__table__)
        table = old.get("ipam_results")
        print("NETRIX source transfer: verifying IP resolution references", flush=True)
        if table is not None:
            for row in connection.execute(sa.select(table)).mappings():
                result = db.get(m.IPAMResult, row["id"])
                if not result:
                    result = m.IPAMResult(
                        **entity(
                            row,
                            (
                                "id",
                                "created_at",
                                "updated_at",
                                "address_id",
                                "status",
                                "retained",
                                "started_at",
                                "completed_at",
                                "last_success_at",
                            ),
                        )
                    )
                    db.add(result)
                result.address_scope, result.issues, result.steps = (
                    row["address_scope"],
                    row["issues"],
                    row["steps"],
                )
                resolutions.write(db, result, row["values"] or {})
                db.flush()
                actual = result.values
                # A result is a decision, never a second fact store. Do not
                # delete a materialization whose only source facts were lost.
                for field in (
                    "hostname",
                    "mac_address",
                    "operating_system",
                    "connected_device",
                    "connected_port",
                ):
                    wanted = (row["values"] or {}).get(field)
                    if wanted and not actual.get(field):
                        raise RuntimeError(f"Resolution transfer lacks {field}; legacy records preserved")
            assert_count(connection, table, m.IPAMResult.__table__)
        verify(connection)
        print("NETRIX source transfer: source parity verified; pruning superseded facts", flush=True)
        from .cleanup import prune

        prune(db)
        db.flush()
        # Session is bound to Alembic's external transaction; commit flushes its
        # unit of work without committing the migration's encompassing transaction.
        db.commit()
    scrub_journals(connection)
    jobs = m.Job.__table__
    for row in connection.execute(
        sa.select(jobs.c.id, jobs.c.result).where(jobs.c.kind == "identify")
    ).mappings():
        result = row["result"] or {}
        if isinstance(result.get("fields"), dict):
            result = {**result, "fields": sorted(result["fields"])}
            connection.execute(jobs.update().where(jobs.c.id == row["id"]).values(result=result))


def assert_count(connection, old, new):
    expected = connection.scalar(sa.select(sa.func.count()).select_from(old))
    actual = connection.scalar(sa.select(sa.func.count()).select_from(new))
    missing = connection.scalar(
        sa.select(sa.func.count())
        .select_from(old.outerjoin(new, old.c.id == new.c.id))
        .where(new.c.id.is_(None))
    )
    if actual < expected or missing:
        raise RuntimeError(f"Transfer count check failed: {old.name}; legacy records preserved")


def verify(connection):
    from sqlalchemy import JSON

    source_tables = {
        t.name
        for t in m.Base.metadata.tables.values()
        if t.name
        in {
            "gateway_bindings",
            "dhcp_bindings",
            "vmware_hosts",
            "vmware_vms",
            "vmware_networks",
            "vmware_nics",
            "vmware_addresses",
            "vmware_physical_nics",
            "lldp_neighbors",
            "cdp_neighbors",
            "mac_port_records",
            "network_source_states",
            "ip_source_links",
            "ip_resolution_results",
            "discovery_reads",
            "neighbor_links",
        }
    }
    for name in source_tables:
        if any(isinstance(c.type, JSON) for c in m.Base.metadata.tables[name].columns):
            raise RuntimeError("Serialized source payload remains")
    # Database UNIQUE/FK constraints validate source identity and reference parity.
    for table in (m.LLDPNeighbor.__table__, m.CDPNeighbor.__table__):
        orphan = connection.scalar(
            sa.select(sa.func.count())
            .select_from(table.outerjoin(m.Link.__table__, table.c.link_id == m.Link.id))
            .where(m.Link.id.is_(None))
        )
        if orphan:
            raise RuntimeError("Orphan protocol source; legacy records preserved")


def scrub_journals(connection):
    # Remove historical automatic-event source copies, retaining event identity,
    # time and changed field names. Managed audit values/configuration are not
    # source observations and are intentionally outside this move.
    table = m.Event.__table__
    kinds = {
        "ip_observation",
        "ipam_observation",
        "ipam_source_changed",
        "ip_observed",
        "ip_observation_change",
        "hostname_change",
        "link_observed",
    }
    ids = list(connection.scalars(sa.select(table.c.id).where(table.c.kind.in_(kinds))))
    for start in range(0, len(ids), 100):
        for row in connection.execute(
            sa.select(table.c.id, table.c.kind, table.c.details).where(
                table.c.id.in_(ids[start : start + 100])
            )
        ).mappings():
            data = row["details"] or {}
            keys = (
                ["hostname"]
                if row["kind"] == "hostname_change"
                else ["neighbor"]
                if row["kind"] == "link_observed"
                else sorted(set((data.get("previous") or {})) | set((data.get("current") or {})))
            )
            connection.execute(table.update().where(table.c.id == row["id"]).values(details={"fields": keys}))
