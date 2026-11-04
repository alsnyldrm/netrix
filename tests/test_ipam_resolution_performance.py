from netrix.ipam import service, table
from test_ipam_endpoint_connections import endpoint


def test_table_returns_summary_without_raw_evidence(admin_client, inventory, env):
    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        db.commit()
        item = table.addresses(db, prefix, allocated=True)["items"][0]
        assert item["connected_device"] == ""
        assert "observations" not in item and "connections" not in item
        assert service.enrich(db, [row])[0]["observations"]


def test_responses_always_read_sql_and_never_write_a_json_cache(env, monkeypatch):
    import json

    from netrix import services
    from netrix.ipam import read_cache

    def forbidden(*args, **kwargs):
        raise AssertionError("IPAM source responses must not be stored in Redis")

    monkeypatch.setattr(services, "redis_client", forbidden)
    calls = []

    def load():
        calls.append(1)
        return {"generation": len(calls)}

    for count in range(1, 5):
        response = read_cache.json_response(["fixture"], load)
        assert json.loads(response.body)["generation"] == count
        assert 'desc="sql"' in response.headers["Server-Timing"]


def test_cached_table_still_requires_authentication(admin_client, inventory, env, monkeypatch):

    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        db.commit()
        url = f"/api/v1/ipam/vlans/{prefix.id}/addresses?allocated=true"
    first = admin_client.get(url)
    assert first.status_code == 200
    cached = admin_client.get(url)
    assert 'desc="sql"' in cached.headers["Server-Timing"]
    admin_client.post("/api/v1/auth/logout")
    assert admin_client.get(url).status_code == 401


def test_dhcp_active_leases_and_reservations_have_distinct_status():
    from netrix.ipam.adapters import DHCP_SCRIPT, dhcp_records

    rows = dhcp_records(
        b'[{"address":"192.0.2.5","hostname":"lease","reserved":false}, {"address":"192.0.2.6","hostname":"reservation","reserved":true}, {"address":"192.0.2.6","hostname":"lease-duplicate","reserved":false}]'
    )
    assert len(rows) == 2
    assert not rows[0]["reserved"]
    assert rows[1]["reserved"] and rows[1]["hostname"] == "reservation"
    assert "Get-DhcpServerv4Lease" in DHCP_SCRIPT and "-AllLeases" not in DHCP_SCRIPT


def test_explicit_refresh_bypasses_and_updates_server_cache(admin_client, inventory, env, monkeypatch):
    from netrix import models as m

    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        service.observe(db, prefix, row.address, "dns", "system", {"hostname": "before.example"})
        db.commit()
        urls = [
            f"/api/v1/ipam/vlans/{prefix.id}/addresses?allocated=true",
            f"/api/v1/ipam/addresses/{row.id}",
        ]
        prefix_id, row_id = prefix.id, row.id
    for url in urls:
        assert admin_client.get(url).status_code == 200
        assert 'desc="sql"' in admin_client.get(url).headers["Server-Timing"]
    with env() as db:
        row = db.get(m.IPAddress, row_id)
        service.observe(
            db, db.get(m.VLAN, prefix_id), row.address, "dns", "system", {"hostname": "after.example"}
        )
        db.commit()  # Another writer; deliberately no cache invalidation notification.
    for url in urls:
        stale = admin_client.get(url).json()
        assert (stale["items"][0] if "items" in stale else stale)["hostname"] == "after.example"
        refreshed = admin_client.get(url, headers={"Cache-Control": "no-cache"})
        assert 'desc="sql"' in refreshed.headers["Server-Timing"]
        item = refreshed.json()
        assert (item["items"][0] if "items" in item else item)["hostname"] == "after.example"
        assert 'desc="sql"' in admin_client.get(url).headers["Server-Timing"]
    admin_client.post("/api/v1/auth/logout")
    assert admin_client.get(urls[0], headers={"Cache-Control": "no-cache"}).status_code == 401


def test_explicit_refresh_updates_vlan_list_and_dashboard(admin_client, inventory, env, monkeypatch):
    from conftest import make_vlan

    urls = ["/api/v1/vlans?limit=200", "/api/v1/dashboard"]
    before = [admin_client.get(url).json() for url in urls]
    for url in urls:
        assert 'desc="sql"' in admin_client.get(url).headers["Server-Timing"]
    with env() as db:
        db.add(make_vlan(vid=333, cidr="203.0.113.0/24", vrf_id=inventory["vrf"]["id"]))
        db.commit()
    assert [admin_client.get(url).json() for url in urls] != before
    after = [admin_client.get(url, headers={"Cache-Control": "no-cache"}).json() for url in urls]
    assert after[0]["total"] == before[0]["total"] + 1
    assert after[1]["counts"]["vlans"] == before[1]["counts"]["vlans"] + 1
