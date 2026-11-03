"""Execution grouping, actual CLI transcripts, redaction, bounds and legacy truthfulness."""

from types import SimpleNamespace

import pytest
from netrix import models as m
from netrix.core import now
from netrix.firmware import adapters, history, runtime
from sqlalchemy import event, select
from test_firmware import fw as firmware_fixture
from test_firmware import make_plan, start

fw = firmware_fixture


def test_grouped_history_filters_paging_and_frozen_membership(fw):
    c = fw["client"]
    plan = make_plan(fw)
    assert c.get("/api/v1/firmware/history").json()["total"] == 0
    start(fw, plan)
    response = c.get("/api/v1/firmware/history?q=rollout&status=queued&mode=check").json()
    assert response["total"] == 1 and response["items"][0]["counts"] == {"queued": 3}
    assert "targets" not in response["items"][0]
    assert c.get("/api/v1/firmware/history?q=%25").json()["total"] == 0
    assert c.get("/api/v1/firmware/history?status=invalid").status_code == 422
    assert c.get("/api/v1/firmware/history?limit=51").status_code == 422
    detail = c.get("/api/v1/firmware/history/" + plan["id"]).json()
    assert [g["counts"] for g in detail["groups"]] == [{"queued": 2}, {"queued": 1}]
    assert "targets" not in detail
    path = f"/api/v1/firmware/history/{plan['id']}/targets"
    first = c.get(path + "?stage=0&limit=1").json()
    second = c.get(path + "?stage=0&limit=1&offset=1").json()
    assert first["total"] == 2 and first["items"][0]["id"] != second["items"][0]["id"]
    waiting = c.get("/api/v1/firmware/history/targets/" + first["items"][0]["id"]).json()
    assert waiting["total"] == 0 and not waiting["legacy"] and waiting["items"] == []
    assert c.get(path + "?stage=8").status_code == 404
    assert c.get(path + "?stage=-1").status_code == 422
    assert c.delete("/api/v1/firmware/groups/" + fw["groups"][0]["id"]).status_code == 204
    detail = c.get("/api/v1/firmware/history/" + plan["id"]).json()
    assert detail["groups"][0]["group_name"] == "Role 0"
    assert c.get(path).json()["total"] == 2


def test_legacy_history_never_invents_commands_or_success(fw):
    plan = make_plan(fw)
    start(fw, plan)
    id = runtime.claim()
    with fw["sf"]() as db:
        target = db.get(m.FirmwareTarget, id)
        target.status, target.error_code, target.error = "attention", "image", adapters.ERRORS["image"]
        target.finished_at = now()
        target.evidence = {key: value for key, value in target.evidence.items() if key != "history_version"}
        target.evidence = {**target.evidence, "preflight_at": now().isoformat()}
        db.commit()
    response = fw["client"].get("/api/v1/firmware/history/targets/" + id).json()
    assert response["legacy"] and response["total"] == 3
    page = fw["client"].get(f"/api/v1/firmware/history/targets/{id}?limit=1&offset=1").json()
    assert page["total"] == 3 and len(page["items"]) == 1 and page["items"][0]["id"] == "preflight_at"
    assert all(not e.get("command") for e in response["items"])
    assert response["target"]["verified_version"] == ""
    assert response["items"][-1]["title"] == "Sonuç belirsiz; müdahale gerekiyor"
    assert "transfer_secret_hash" not in str(response)
    assert "connection_stamp" not in str(response)  # internal connection identity is not a transcript


@pytest.mark.parametrize(
    "sample",
    [
        "password secret-value\nhostname okay",
        'snmp-server community "secret-value"\nhostname okay',
        "-----BEGIN PRIVATE KEY-----\nsecret-value\n-----END PRIVATE KEY-----\nhostname okay",
        '{"token":"secret-value","name":"okay"}',
        "<root><password>secret-value</password><name>okay</name></root>",
    ],
)
def test_transcript_redacts_config_secrets(sample):
    result, truncated = history.safe_text(sample)
    assert "secret-value" not in result and "okay" in result and not truncated


@pytest.mark.asyncio
async def test_actual_cli_command_response_failure_and_reboot_are_recorded(fw):
    plan = make_plan(fw, "upgrade")
    start(fw, plan)
    id = runtime.claim()
    recorder = history.Recorder(id, ("fixture-login-secret",))
    username, filename, password = "fw_" + "a" * 20, "netrix-fw-" + "b" * 48 + ".swi", "source-fixture-secret"
    recorder.secrets.append(password)
    command = f"copy scp://{username}@192.0.2.100:2222/{filename} secondary vrf default"
    chunks, sent = [], []

    async def read(_):
        return chunks.pop(0)

    def write(value):
        # A command must be durable before anything is sent to a device.
        with fw["sf"]() as db:
            latest = db.scalar(
                select(m.FirmwareEvent)
                .where(m.FirmwareEvent.target_id == id)
                .order_by(m.FirmwareEvent.id.desc())
            )
            assert latest.status == "started"
        sent.append(value)

    cli = adapters.CLI(
        SimpleNamespace(stdin=SimpleNamespace(write=write), stdout=SimpleNamespace(read=read)),
        "aruba_6100",
        recorder=recorder,
    )
    cli.prompt = "switch#"
    chunks[:] = [f"{command}\nPassword: ", f"{password}\nCopy complete\nswitch#"]
    await cli.command(command, action="transfer", password=password)
    chunks[:] = ["show images\nError: fixture rejected\nswitch#"]
    with pytest.raises(adapters.FirmwareError):
        await cli.command("show images")
    chunks[:] = ["Rebooting", ""]
    await cli.command("boot system secondary", action="boot", disconnect=True)
    response = fw["client"].get("/api/v1/firmware/history/targets/" + id).json()
    assert not response["legacy"]
    assert [e["status"] for e in response["items"]] == ["succeeded", "failed", "sent"]
    assert "Copy complete" in response["items"][0]["response"]
    assert "Error: fixture rejected" in response["items"][1]["response"]
    assert sent == [command + "\n", password + "\n", "show images\n", "boot system secondary\n"]
    with fw["sf"]() as db:
        stored = str([vars(e) for e in db.scalars(select(m.FirmwareEvent))])
        assert db.get(m.FirmwareTarget, id).status == "running"  # boot command isn't upgrade success
    for secret in (username, filename, password, "fixture-login-secret"):
        assert secret not in str(response) and secret not in stored


@pytest.mark.asyncio
async def test_history_pagination_bounds_does_not_load_other_devices(fw, monkeypatch):
    plan = make_plan(fw)
    start(fw, plan)
    id = runtime.claim()
    runtime.set_phase(id, "preflight")
    recorder = history.Recorder(id)
    for n in range(43):
        await recorder.note(f"Adım {n}", "visible " + "x" * 14000 + "long-tail", kind="phase")
    result = fw["client"].get(f"/api/v1/firmware/history/targets/{id}?limit=7&offset=35").json()
    assert result["total"] == 44 and len(result["items"]) == 7
    assert [e["id"] for e in result["items"]] == list(range(36, 43))
    assert all(e["truncated"] and len(e["response"]) == history.OUTPUT_LIMIT for e in result["items"])
    masked, cut = history.safe_text(
        "x" * (history.OUTPUT_LIMIT - 3) + "full-sensitive-value", ("full-sensitive-value",)
    )
    assert cut and "ful" not in masked
    monkeypatch.setattr(history, "EVENT_LIMIT", 44)
    await recorder.note("not stored", "hidden")
    await recorder.note("not stored either", "hidden")
    with fw["sf"]() as db:
        records = list(db.scalars(select(m.FirmwareEvent).where(m.FirmwareEvent.target_id == id)))
        assert len(records) == 45 and records[-1].title == "Ayrıntılı kayıt sınırına ulaşıldı"


def test_history_list_uses_bounded_queries_without_transcripts(fw):
    plan = make_plan(fw)
    start(fw, plan)
    with fw["sf"]() as db:
        statements = []
        engine = db.get_bind()

        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture)
        try:
            history.listing(db)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 3
    assert all("firmware_events" not in statement for statement in statements)


def test_history_requires_authentication_and_viewers_can_read_only(fw):
    plan = make_plan(fw)
    start(fw, plan)
    target_id = runtime.claim()
    paths = [
        "/api/v1/firmware/history",
        f"/api/v1/firmware/history/{plan['id']}",
        f"/api/v1/firmware/history/{plan['id']}/targets",
        f"/api/v1/firmware/history/targets/{target_id}",
    ]
    with fw["sf"]() as db:
        user = db.scalar(select(m.User))
        user.role = "viewer"
        db.commit()
    for path in paths:
        assert fw["client"].get(path).status_code == 200
    assert fw["client"].post(f"/api/v1/firmware/plans/{plan['id']}/cancel").status_code == 403
    fw["client"].cookies.clear()
    for path in paths:
        assert fw["client"].get(path).status_code == 401


@pytest.mark.asyncio
async def test_command_is_not_sent_when_durable_history_cannot_be_opened():
    sent = []

    async def fail(*args):
        raise RuntimeError("fixture database unavailable")

    cli = adapters.CLI(
        SimpleNamespace(stdin=SimpleNamespace(write=sent.append)),
        "aruba_6100",
        recorder=SimpleNamespace(begin=fail),
    )
    with pytest.raises(RuntimeError):
        await cli.command("boot system primary", action="boot", disconnect=True)
    assert sent == []


@pytest.mark.asyncio
async def test_rejected_boot_command_is_failed_not_sent(fw):
    plan = make_plan(fw)
    start(fw, plan)
    id = runtime.claim()
    chunks = ["Error: command rejected\nswitch#"]

    async def read(_):
        return chunks.pop(0)

    cli = adapters.CLI(
        SimpleNamespace(stdin=SimpleNamespace(write=lambda _: None), stdout=SimpleNamespace(read=read)),
        "aruba_6100",
        recorder=history.Recorder(id),
    )
    cli.prompt = "switch#"
    with pytest.raises(adapters.FirmwareError):
        await cli.command("boot system primary", action="boot", disconnect=True)
    result = fw["client"].get("/api/v1/firmware/history/targets/" + id).json()
    assert result["items"][0]["status"] == "failed"
    assert "yeniden başlatılması" in result["items"][0]["title"]
