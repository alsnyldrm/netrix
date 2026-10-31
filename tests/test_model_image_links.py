from netrix import models as m
from sqlalchemy import select

IMAGE = "https://cdn.blueally.com/avfirewalls/images/fortigate/fg-600f.png"
SOURCE = "https://docs.fortinet.com/document/fortigate/8.0.2/hardware-acceleration/589036/fortigate-600f-and-601f-fast-path-architecture"


def test_supplied_fortinet_image_links_save_reload_and_match_csp(admin_client, inventory, env):
    with env() as db:
        device = m.Device(
            name="Firewall",
            management_ip="192.0.2.44",
            vrf_id=inventory["vrf"]["id"],
            vendor="Fortinet",
            model="FGT_600F",
        )
        db.add(device)
        db.commit()
        id = device.id
    url = f"/api/v1/ipam/devices/{id}/model-image"
    response = admin_client.put(url, json={"url": IMAGE, "source": SOURCE})
    assert response.status_code == 200, response.text
    assert admin_client.get(url).json() == {"url": IMAGE, "source": SOURCE}
    assert (
        "https://cdn.blueally.com"
        in response.headers["Content-Security-Policy"].split("img-src ")[1].split(";")[0]
    )
    for bad in (
        "https://cdn.blueally.com.evil.test/a.png",
        "http://cdn.blueally.com/a.png",
        "https://user:secret@cdn.blueally.com/a.png",
        "https://cdn.blueally.com:8443/a.png",
        "https://127.0.0.1/a.png",
    ):
        assert admin_client.put(url, json={"url": bad, "source": SOURCE}).status_code == 422
    assert (
        admin_client.put(
            url, json={"url": IMAGE, "source": "https://docs.fortinet.com.evil.test/a"}
        ).status_code
        == 422
    )
    assert admin_client.get(url).json() == {"url": IMAGE, "source": SOURCE}
    with env() as db:
        assert len(db.scalars(select(m.ModelImage)).all()) == 1
    admin_client.cookies.clear()
    assert admin_client.get(url).status_code == 401
