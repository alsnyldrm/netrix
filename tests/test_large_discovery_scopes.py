"""Large IPv4 scopes must save and enumerate fully without unbounded task creation."""

import asyncio
import ipaddress
from itertools import islice
from types import SimpleNamespace

import pytest
from netrix import models as m
from netrix.discovery.protocols import NetworkError
from netrix.worker import discover, scope_targets
from sqlalchemy import select


def test_21_scope_saves_without_seeds_and_does_not_enqueue(admin_client, inventory):
    payload = dict(
        name="VLAN-60",
        cidr="10.6.0.0/21",
        vrf_id=inventory["vrf"]["id"],
        credential_ids=[inventory["credential"]["id"]],
    )
    response = admin_client.post("/api/v1/scopes", json=payload)
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["seeds"] == []
    assert admin_client.put("/api/v1/scopes/" + row["id"], json=payload).status_code == 200
    assert admin_client.get("/api/v1/jobs").json()["total"] == 0
    targets = list(scope_targets(SimpleNamespace(**row)))
    assert len(targets) == 2046
    assert targets[0] == "10.6.0.1" and targets[-1] == "10.6.7.254"
    assert "10.6.4.1" in targets


@pytest.mark.parametrize(
    "cidr,exclusions",
    [
        ("10.6.0.0/21", ["10.6.1.0/24", "10.6.1.0/25", "10.6.7.254/32"]),
        ("192.0.2.0/31", []),
        ("192.0.2.1/32", []),
        ("127.0.0.0/30", []),
        ("169.254.0.0/30", []),
        ("224.0.0.0/30", []),
        ("0.0.0.0/31", []),
        ("10.6.0.0/21", ["10.6.0.0/21"]),
    ],
)
def test_target_ranges_equal_host_filtering(cidr, exclusions):
    scope = SimpleNamespace(cidr=cidr, seeds=[], enabled=True, exclusions=exclusions)
    expected = [
        str(ip)
        for ip in ipaddress.ip_network(cidr).hosts()
        if not (ip.is_multicast or ip.is_loopback or ip.is_link_local or ip.is_unspecified)
        and not any(ip in ipaddress.ip_network(e) for e in exclusions)
    ]
    targets = scope_targets(scope)
    assert len(targets) == len(expected)
    assert list(targets) == expected


def test_large_scope_targets_are_lazy_and_countable():
    scope = SimpleNamespace(cidr="10.0.0.0/8", seeds=[], enabled=True, exclusions=["10.2.0.0/16"])
    targets = scope_targets(scope)
    assert not isinstance(targets, list)
    assert len(targets) == 16777214 - 65536
    assert list(islice(targets, 3)) == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]


async def test_worker_reaches_last_21_address_with_four_consumers(admin_client, inventory, env):
    response = admin_client.put(
        "/api/v1/scopes/" + inventory["scope"]["id"],
        json={
            "name": "Large",
            "cidr": "10.6.0.0/21",
            "vrf_id": inventory["vrf"]["id"],
            "credential_ids": [inventory["credential"]["id"]],
        },
    )
    assert response.status_code == 200, response.text
    response = admin_client.post(
        "/api/v1/jobs", json={"kind": "discovery", "target_id": inventory["scope"]["id"]}
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    calls, workers = set(), set()
    active = peak = 0

    class Collector:
        async def collect(self, host, port, secret):
            nonlocal active, peak
            workers.add(asyncio.current_task())
            calls.add(host)
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0)
                raise NetworkError("offline fixture")
            finally:
                active -= 1

    result = await discover(job_id, Collector())
    assert result == {"reachable": 0, "unresponsive": 2046, "total": 2046}
    assert len(calls) == 2046 and "10.6.7.254" in calls
    assert len(workers) <= 4 and peak <= 4
    with env() as db:
        job = db.get(m.Job, job_id)
        assert job.total == job.progress == 2046
        assert not list(db.scalars(select(m.Device)))


async def test_large_discovery_cancellation_stops_all_four_inflight_targets(admin_client, inventory, env):
    response = admin_client.put(
        "/api/v1/scopes/" + inventory["scope"]["id"],
        json={
            "name": "Large cancellable scope",
            "cidr": "10.0.0.0/8",
            "vrf_id": inventory["vrf"]["id"],
            "credential_ids": [inventory["credential"]["id"]],
        },
    )
    assert response.status_code == 200, response.text
    response = admin_client.post(
        "/api/v1/jobs", json={"kind": "discovery", "target_id": inventory["scope"]["id"]}
    )
    assert response.status_code == 202
    job_id = response.json()["id"]
    started, finished = set(), set()
    ready = asyncio.Event()

    class Collector:
        async def collect(self, host, port, secret):
            started.add(host)
            if len(started) == 4:
                ready.set()
            try:
                await asyncio.Future()
            finally:
                finished.add(host)

    task = asyncio.create_task(discover(job_id, Collector()))
    try:
        await asyncio.wait_for(ready.wait(), timeout=5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert started == finished and len(started) == 4
    with env() as db:
        job = db.get(m.Job, job_id)
        assert job.total == 16777214 and job.progress == 0


def test_explicit_ipv4_targets_remain_a_subset_and_respect_exclusions():
    scope = SimpleNamespace(
        cidr="10.6.0.0/21",
        seeds=["10.6.0.1", "10.6.4.1", "10.6.0.1", "10.7.0.1"],
        enabled=True,
        exclusions=["10.6.0.0/24"],
    )
    assert scope_targets(scope) == ["10.6.4.1"]
    scope.enabled = False
    assert scope_targets(scope) == []
