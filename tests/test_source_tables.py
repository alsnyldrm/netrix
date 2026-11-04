"""Typed source ownership, repeatable updates and a verification gate before cleanup."""

import pytest
import sqlalchemy as sa
from netrix import models as m
from netrix.core import now
from netrix.sources import migrate_v1, records
from test_ipam_source_contract import network as network


def test_sources_have_no_serialized_payloads():
    names = {
        "ip_source_links",
        "ip_resolution_results",
        "network_source_states",
        "discovery_reads",
        "neighbor_links",
        "gateway_bindings",
        "dhcp_bindings",
        "dns_records",
        "ping_states",
        "mac_port_records",
        "vmware_hosts",
        "vmware_vms",
        "vmware_networks",
        "vmware_nics",
        "vmware_addresses",
        "vmware_physical_nics",
        "vmware_uplinks",
        "vmware_nic_hints",
        "vmware_hint_addresses",
        "lldp_neighbors",
        "cdp_neighbors",
    }
    for name in names:
        assert name in m.Base.metadata.tables
        assert not any(isinstance(c.type, sa.JSON) for c in m.Base.metadata.tables[name].columns), name
    assert not set(migrate_v1.LEGACY).intersection(m.Base.metadata.tables)


def test_ip_source_metadata_does_not_load_the_whole_switch_fdb(network):
    from netrix.sources.network import state_for

    sf, _, rid, ids = network
    with sf() as db:
        state = state_for(db, ids[0], db.get(m.Device, ids[0]).management_ip)
        state.mac_entries.extend(
            m.SwitchMacEntry(
                vrf_id=db.get(m.IPAddress, rid).vrf_id,
                vlan_vid=20,
                fdb_id=20,
                mac_address=f"02:00:00:00:{i // 256:02x}:{i % 256:02x}",
                port="7",
                if_index=7,
                observed_at=now(),
            )
            for i in range(300)
        )
        db.flush()
        db.add(m.IPObservation(address_id=rid, source="address_network", source_key=ids[0], network=state))
        db.commit()
    with sf() as db:
        source = db.scalar(sa.select(m.IPObservation).where(m.IPObservation.source == "address_network"))
        assert source.data["device_address"]
        assert not any(isinstance(row, m.SwitchMacEntry) for row in db.identity_map.values())
        assert len(source.network.mac_entries) == 300


def test_repeated_source_updates_keep_one_fact_and_survive_reload(network):
    sf, _, rid, _ = network
    for hostname in ("old", "new", "new"):
        with sf() as db:
            link = db.scalar(
                sa.select(m.IPObservation).where(
                    m.IPObservation.address_id == rid, m.IPObservation.source == "dns"
                )
            )
            link.data = {"hostname": hostname}
            db.commit()
        with sf() as db:
            assert db.scalar(sa.select(m.DNSRecord)).hostname == hostname
    with sf() as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(m.DNSRecord)) == 1
        assert db.scalar(sa.select(sa.func.count()).select_from(m.IPObservation)) == 1


def test_vmware_multiple_ips_share_nic_and_vm(network):
    sf, _, _, _ = network
    with sf() as db:
        for address in ("192.0.2.10", "192.0.2.11", "192.0.2.10"):
            records.vmware(
                db,
                "vc-fixture",
                {
                    "vm_id": "vm-9",
                    "nic_key": "4000",
                    "address": address,
                    "mac_address": "00:50:56:00:00:01",
                    "hostname": "vm-name",
                    "operating_system": "Linux",
                    "dvswitch": "ds-1",
                    "dvswitch_name": "FBU-DS",
                    "portgroup_key": "pg-20",
                    "network": "VLAN-020",
                    "dvport": "89",
                },
            )
            db.flush()
        db.commit()
        for cls, count in ((m.VMwareVM, 1), (m.VMwareNIC, 1), (m.VMwareAddress, 2), (m.VMwareNetwork, 1)):
            assert db.scalar(sa.select(sa.func.count()).select_from(cls)) == count


def test_rollback_does_not_reuse_transient_fact_from_cache(network):
    sf, _, _, _ = network
    with sf() as db:
        records.dhcp(
            db, "server", {"hostname": "discarded", "mac_address": "00:11:22:33:44:55"}, "192.0.2.50"
        )
        db.flush()
        db.rollback()
        records.dhcp(db, "server", {"hostname": "kept", "mac_address": "00:11:22:33:44:55"}, "192.0.2.50")
        db.commit()
        assert db.scalar(sa.select(m.DHCPBinding)).hostname == "kept"


def legacy_observations(engine):
    metadata = sa.MetaData()
    table = sa.Table(
        "ip_observations",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", m.UTCDateTime()),
        sa.Column("updated_at", m.UTCDateTime()),
        sa.Column("address_id", sa.String(36)),
        sa.Column("source", sa.String(20)),
        sa.Column("source_key", sa.String(120)),
        sa.Column("observed_at", m.UTCDateTime()),
        sa.Column("data", sa.JSON()),
    )
    metadata.create_all(engine)
    return table


def test_verified_legacy_move_preserves_fact_ids_and_removes_no_data_on_failure(network):
    sf, _, rid, _ = network
    engine = sf.kw["bind"]
    old = legacy_observations(engine)
    at = now()
    with engine.begin() as c:
        c.execute(
            old.insert(),
            dict(
                id="legacy-dhcp",
                created_at=at,
                updated_at=at,
                observed_at=at,
                address_id=rid,
                source="windows_dhcp",
                source_key="dhcp-server",
                data={"hostname": "client-name", "mac_address": "00:11:22:33:44:55", "reserved": True},
            ),
        )
        migrate_v1.transfer_and_verify(c)
        assert (
            c.scalar(sa.select(sa.func.count()).select_from(old)) == 1
        )  # deletion belongs to Alembic after verification
    with sf() as db:
        assert db.get(m.IPObservation, "legacy-dhcp").data["hostname"] == "client-name"
        assert db.scalar(sa.select(sa.func.count()).select_from(m.DHCPBinding)) == 1
    with engine.begin() as c:
        migrate_v1.transfer_and_verify(c)
    with sf() as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(m.DHCPBinding)) == 1
    with engine.begin() as c:
        c.execute(
            old.insert(),
            dict(
                id="bad-source",
                created_at=at,
                updated_at=at,
                observed_at=at,
                address_id=rid,
                source="unsupported",
                source_key="bad",
                data={"unmapped": "do not discard"},
            ),
        )
    with pytest.raises(ValueError, match="Unsupported persisted source"):
        with engine.begin() as c:
            migrate_v1.transfer_and_verify(c)
    with engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(old)) == 2


def test_conflicting_names_inside_one_native_vm_snapshot_are_rejected(network):
    from types import SimpleNamespace

    sf, _, _, _ = network
    with sf() as db:
        with pytest.raises(ValueError, match="conflicting native owner"):
            records.save_integration(
                db,
                SimpleNamespace(kind="vcenter", id="vc"),
                [
                    {"vm_id": "vm-1", "nic_key": "1", "hostname": "one"},
                    {"vm_id": "vm-1", "nic_key": "2", "hostname": "other"},
                ],
            )
        assert not db.scalar(sa.select(m.VMwareVM))


def test_retired_source_graph_is_bounded_but_referenced_last_known_facts_survive(network):
    from types import SimpleNamespace

    from netrix.ipam import service
    from netrix.sources.cleanup import prune

    sf, vid, rid, _ = network
    with sf() as db:
        row = db.get(m.IPAddress, rid)
        data = {
            "vm_id": "vm1",
            "nic_key": "1",
            "guest_address": row.address,
            "hostname": "saved",
            "mac_address": "00:50:56:00:00:01",
            "operating_system": "Linux",
            "dvswitch_name": "FBU-DS",
            "dvport": "89",
        }
        service.observe(db, db.get(m.VLAN, vid), row.address, "vcenter", "fixture:vm1:1", data)
        link = db.scalar(sa.select(m.IPObservation).where(m.IPObservation.source == "vcenter"))
        decision = m.IPAMResult(
            address_id=rid, address_scope=[row.address, row.vrf_id, vid], status="problem"
        )
        decision.fields.append(m.ResolutionField(field="hostname", source_link=link, source="vcenter"))
        db.add(decision)
        db.commit()
        records.save_integration(db, SimpleNamespace(kind="vcenter", id="fixture"), [], complete=True)
        prune(db)
        db.commit()
        assert db.scalar(sa.select(sa.func.count()).select_from(m.VMwareVM)) == 1
        assert decision.values["hostname"] == "saved"
        db.delete(decision)
        db.flush()
        prune(db)
        db.commit()
        for cls in (m.VMwareAddress, m.VMwareNIC, m.VMwareVM, m.VMwareHost, m.VMwareNetwork):
            assert db.scalar(sa.select(sa.func.count()).select_from(cls)) == 0


def test_port_indexes_can_swap_without_changing_physical_port_identity(network):
    from netrix.sources import network as source_network

    sf, _, _, devices = network
    with sf() as db:
        state = db.scalar(sa.select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == devices[1]))
        source_network.write(
            db,
            state,
            {
                "interfaces": [
                    {"if_index": 1, "name": "A1", "oper_status": "up"},
                    {"if_index": 2, "name": "A2", "oper_status": "up"},
                ]
            },
            now(),
        )
        db.commit()
        ids = {p.name: p.id for p in state.ports}
        source_network.write(
            db,
            state,
            {
                "interfaces": [
                    {"if_index": 2, "name": "A1", "oper_status": "up"},
                    {"if_index": 1, "name": "A2", "oper_status": "up"},
                ]
            },
            now(),
        )
        db.commit()
        assert {p.name: (p.id, p.if_index) for p in state.ports if p.name.startswith("A")} == {
            "A1": (ids["A1"], 2),
            "A2": (ids["A2"], 1),
        }
