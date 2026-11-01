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


def test_response_cache_invalidation_expiry_and_failure(env, monkeypatch):
    import json

    from netrix import services
    from netrix.ipam import read_cache

    memory = services.redis_client()
    monkeypatch.setattr(read_cache, "client", lambda _: memory)
    monkeypatch.setattr(read_cache, "_retry_after", 0)
    calls = []

    def load():
        calls.append(1)
        return {"generation": len(calls)}

    def read(key="prefix-a"):
        return json.loads(read_cache.json_response([key], load).body)

    assert read()["generation"] == 1
    assert read()["generation"] == 1
    services.publish()
    assert read()["generation"] == 2
    assert read("prefix-b")["generation"] == 3
    current = read_cache.time.time()
    monkeypatch.setattr(read_cache.time, "time", lambda: current + 6)
    assert read()["generation"] == 4

    def unavailable(_):
        raise ConnectionError("cache unavailable")

    monkeypatch.setattr(read_cache, "client", unavailable)
    assert read()["generation"] == 5
    assert read()["generation"] == 6


def test_cached_table_still_requires_authentication(admin_client, inventory, env, monkeypatch):
    from netrix import services
    from netrix.ipam import read_cache

    monkeypatch.setattr(read_cache, "client", lambda _: services.redis_client())
    monkeypatch.setattr(read_cache, "_retry_after", 0)
    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        db.commit()
        url = f"/api/v1/ipam/vlans/{prefix.id}/addresses?allocated=true"
    first = admin_client.get(url)
    assert first.status_code == 200
    cached = admin_client.get(url)
    assert "hit" in cached.headers["Server-Timing"]
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
