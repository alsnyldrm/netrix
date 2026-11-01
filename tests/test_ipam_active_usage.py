import json
from datetime import timedelta

from conftest import make_vlan, vlan_payload
from netrix import models as m
from netrix.core import now
from netrix.ipam import service, table


def test_active_usage_filter_and_status_share_latest_ping(env):
    with env() as db:
        vrf = m.VRF(name="Active test")
        db.add(vrf)
        db.flush()
        prefix = make_vlan(cidr="10.1.0.0/29", vrf_id=vrf.id, warning_threshold=50)
        db.add(prefix)
        db.flush()
        rows = []
        for n in range(1, 7):
            row = m.IPAddress(
                address=f"10.1.0.{n}",
                vlan_id=prefix.id,
                vrf_id=vrf.id,
                status="active",
                hostname=f"host-{n}",
            )
            db.add(row)
            db.flush()
            rows.append(row)
            db.add(
                m.IPObservation(
                    address_id=row.id, source="dns", source_key="system", data={"hostname": f"host-{n}"}
                )
            )
        for index, state, age in (
            (0, "reachable", 0),
            (1, "no_reply", 0),
            (2, "reachable", 25),
            (4, "reachable", 0),
            (5, "reachable", 1),
            (5, "no_reply", 0),
        ):
            db.add(
                m.IPObservation(
                    address_id=rows[index].id,
                    source="icmp",
                    source_key=str(age),
                    data={"reachability": state},
                    observed_at=now() - timedelta(hours=age),
                )
            )
        db.add(
            m.IPObservation(
                address_id=rows[1].id, source="vcenter", source_key="vm", data={"power_state": "poweredOn"}
            )
        )
        db.add(
            m.IPObservation(
                address_id=rows[3].id, source="vcenter", source_key="vm", data={"power_state": "poweredOn"}
            )
        )
        db.commit()
        summary = service.vlan_summary(db, prefix)
        assert summary["used"] == 2 and summary["capacity"] == "6"
        assert summary["utilization"] == 33.33 and not summary["threshold_exceeded"]
        result = table.addresses(db, prefix, active_only=True, limit=1, offset=1)
        assert result["total"] == "2" and result["items"][0]["address"] == "10.1.0.5"
        result = table.addresses(
            db,
            prefix,
            active_only=True,
            q="host",
            filters=json.dumps([{"field": "hostname", "op": "not_contains", "value": "5"}]),
        )
        assert result["total"] == "1" and result["items"][0]["address"] == "10.1.0.1"
        all_rows = {r["address"]: r for r in service.enrich(db, rows)}
        assert all_rows["10.1.0.2"]["availability"] == "passive"
        assert all_rows["10.1.0.3"]["availability"] == "unknown"
        assert all_rows["10.1.0.4"]["availability"] == "unknown"
        assert all_rows["10.1.0.6"]["availability"] == "passive"
        prefix.warning_threshold = 30
        assert service.vlan_summary(db, prefix)["threshold_exceeded"]
        assert table.addresses(db, prefix)["total"] == "8"


def test_active_api_filters_registered_records_without_ping(admin_client, inventory, env):
    c = admin_client
    prefix = c.post(
        "/api/v1/vlans", json=vlan_payload({"cidr": "10.2.0.0/24", "vrf_id": inventory["vrf"]["id"]})
    ).json()
    c.post(
        "/api/v1/addresses",
        json={
            "address": "10.2.0.3",
            "vlan_id": prefix["id"],
            "vrf_id": prefix["vrf_id"],
            "status": "active",
        },
    )
    result = c.get(f"/api/v1/ipam/vlans/{prefix['id']}/addresses?active_only=true").json()
    assert result["items"] == [] and result["total"] == "0"
    assert result["vlan"]["used"] == 0
    for reachability, total in (("reachable", "1"), ("no_reply", "0")):
        with env() as db:
            service.observe(
                db,
                db.get(m.VLAN, prefix["id"]),
                "10.2.0.3",
                "icmp",
                prefix["id"],
                {"reachability": reachability},
            )
            db.commit()
        service.publish()
        result = c.get(f"/api/v1/ipam/vlans/{prefix['id']}/addresses?active_only=true").json()
        assert result["total"] == total and result["vlan"]["used"] == int(total)
    # Disabling the active filter preserves access to the passive IP record.
    assert c.get(f"/api/v1/ipam/vlans/{prefix['id']}/addresses?allocated=true").json()["total"] == "1"
