import pytest


def test_normalized_ip_uniqueness_vrf_and_prefix_boundaries(admin_client):
    c = admin_client
    v1 = c.get("/api/v1/vrfs").json()["items"][0]["id"]
    v2 = c.post("/api/v1/vrfs", json={"name": "Other"}).json()["id"]
    for vrf in (v1, v2):
        prefix = c.post("/api/v1/prefixes", json={"cidr": "192.0.2.0/24", "vrf_id": vrf}).json()
        assert (
            c.post(
                "/api/v1/addresses", json={"address": "192.0.2.1", "vrf_id": vrf, "prefix_id": prefix["id"]}
            ).status_code
            == 201
        )
        assert (
            c.post(
                "/api/v1/addresses", json={"address": "192.0.2.1", "vrf_id": vrf, "prefix_id": prefix["id"]}
            ).status_code
            == 409
        )
        for bad in ("192.0.3.1", "192.0.2.0", "192.0.2.255"):
            assert (
                c.post(
                    "/api/v1/addresses", json={"address": bad, "vrf_id": vrf, "prefix_id": prefix["id"]}
                ).status_code
                == 422
            )
        assert (
            c.post(
                "/api/v1/addresses",
                json={"address": "192.0.2.2", "vrf_id": v1 if vrf == v2 else v2, "prefix_id": prefix["id"]},
            ).status_code
            == 422
        )


@pytest.mark.parametrize(
    "cidr,addresses",
    [
        ("192.0.2.0/31", ["192.0.2.0", "192.0.2.1"]),
        ("192.0.2.9/32", ["192.0.2.9"]),
        ("2001:db8::/64", ["2001:db8::1"]),
    ],
)
def test_ipv6_and_point_to_point_capacity(admin_client, env, cidr, addresses):
    from netrix import models as m
    from netrix.ipam.service import observe

    c = admin_client
    vrf = c.get("/api/v1/vrfs").json()["items"][0]["id"]
    p = c.post("/api/v1/prefixes", json={"cidr": cidr, "vrf_id": vrf})
    assert p.status_code == 201, p.text
    for address in addresses:
        assert (
            c.post(
                "/api/v1/addresses", json={"address": address, "vrf_id": vrf, "prefix_id": p.json()["id"]}
            ).status_code
            == 201
        )
    row = c.get("/api/v1/prefixes").json()["items"][0]
    assert row["used"] == 0
    with env() as db:
        prefix = db.get(m.Prefix, p.json()["id"])
        for address in addresses:
            observe(db, prefix, address, "icmp", prefix.id, {"reachability": "reachable"})
        db.commit()
        from netrix.ipam.service import prefix_summary

        row = prefix_summary(db, prefix)
    assert row["used"] == len(addresses)
    if ":" not in cidr:
        assert row["utilization"] == 100


def test_prefix_edit_preserves_existing_assignments(admin_client):
    c = admin_client
    vrf = c.get("/api/v1/vrfs").json()["items"][0]["id"]
    p = c.post("/api/v1/prefixes", json={"cidr": "192.0.2.0/24", "vrf_id": vrf}).json()
    c.post("/api/v1/addresses", json={"address": "192.0.2.200", "vrf_id": vrf, "prefix_id": p["id"]})
    assert (
        c.put("/api/v1/prefixes/" + p["id"], json={"cidr": "192.0.2.0/25", "vrf_id": vrf}).status_code == 409
    )
    assert c.delete("/api/v1/prefixes/" + p["id"]).status_code == 204
    assert c.get("/api/v1/addresses").json()["total"] == 0


def test_vlan_domain_uniqueness_and_bounds(admin_client):
    for domain in ("campus", "datacenter"):
        assert (
            admin_client.post(
                "/api/v1/vlans", json={"name": "Users", "domain": domain, "vid": 10}
            ).status_code
            == 201
        )
    assert (
        admin_client.post(
            "/api/v1/vlans", json={"name": "Duplicate", "domain": "campus", "vid": 10}
        ).status_code
        == 409
    )
    assert admin_client.post("/api/v1/vlans", json={"name": "Invalid", "vid": 4095}).status_code == 422
