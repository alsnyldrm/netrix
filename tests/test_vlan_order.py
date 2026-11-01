"""VLANs retain VID ordering across pagination and search."""

from conftest import make_vlan


def test_vlan_order_is_numeric_before_pagination_and_search(admin_client, inventory, env):
    vrf_id = inventory["vrf"]["id"]
    expected = [
        "10.1.0.0/23",
        "10.1.0.0/24",
        "10.2.0.0/24",
        "10.10.0.0/24",
        "10.100.0.0/24",
        "192.0.2.0/24",
        "2001:db8:2::/48",
        "2001:db8:a::/48",
        "2001:db8:10::/48",
    ]
    # Deliberately interleave IP families and creation order.
    with env() as db:
        for index in [3, 0, 8, 2, 7, 4, 1, 5, 6]:
            db.add(make_vlan(cidr=expected[index], vrf_id=vrf_id, vid=index + 1))
            db.flush()
        db.commit()

    def page(offset=0, q="", limit=2):
        response = admin_client.get("/api/v1/vlans", params={"limit": limit, "offset": offset, "q": q})
        assert response.status_code == 200, response.text
        return response.json()

    assert page()["total"] == len(expected)
    assert [row["cidr"] for offset in range(0, len(expected), 2) for row in page(offset)["items"]] == expected
    assert [row["cidr"] for row in page(q="10.", limit=200)["items"]] == expected[:5]
    assert [row["cidr"] for row in page(2, q="10.")["items"]] == expected[2:4]
    assert page(100)["items"] == []
    assert page(q="not-a-network")["total"] == 0
