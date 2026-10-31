import pytest
from netrix.configuration.diff import config_diff, redact_config

HEADER = "#config-version=FG-fixture\n#conf_file_ver=1\n"


def test_changed_value_includes_distant_config_and_edit_ancestors():
    old = (
        HEADER
        + 'config vdom\n    edit "root"\n        config system global\n'
        + "".join(f"            set fixture-{i} enable\n" for i in range(15))
        + "            set admintimeout 5\n        end\n    next\nend\n"
    )
    diff = config_diff(old, old.replace("admintimeout 5", "admintimeout 15"))
    assert 'config vdom > edit "root" > config system global' in diff
    assert "-            set admintimeout 5" in diff
    assert "+            set admintimeout 15" in diff
    assert "fixture-0" not in diff


def test_header_only_change_does_not_show_unchanged_config_section():
    old = HEADER + "config system global\n    set admintimeout 5\nend\n"
    diff = config_diff(old, old.replace("#conf_file_ver=1", "#conf_file_ver=2"))
    assert "Yalnızca dosya üstbilgisi değişmiş" in diff
    assert "config system global" not in diff
    assert "-#conf_file_ver=1" in diff and "+#conf_file_ver=2" in diff


def test_secret_change_remains_visible_with_key_but_without_value():
    old = (
        HEADER
        + 'config system admin\n    edit "admin"\n        set password ENC OLD-PRIVATE\n    next\nend\n'
    )
    diff = config_diff(old, old.replace("OLD-PRIVATE", "NEW-PRIVATE"))
    assert 'config system admin > edit "admin"' in diff
    assert "-        set password " in diff and "+        set password " in diff
    assert "OLD-PRIVATE" not in diff and "NEW-PRIVATE" not in diff
    assert config_diff(old, old) == ""


@pytest.mark.parametrize("change", ["replace", "insert", "delete"])
def test_multiple_sections_and_added_removed_lines_have_correct_paths(change):
    old = (
        HEADER
        + 'config system global\n    set admintimeout 5\nend\nconfig system interface\n    edit "port1"\n        set alias "before"\n    next\nend\n'
    )
    new = old.replace("admintimeout 5", "admintimeout 15")
    new = new.replace(
        '        set alias "before"\n',
        {
            "replace": '        set alias "after"\n',
            "insert": '        set alias "before"\n        set status down\n',
            "delete": "",
        }[change],
    )
    diff = config_diff(old, new)
    assert "Bölüm: config system global" in diff
    assert 'Bölüm: config system interface > edit "port1"' in diff
    assert "Yalnızca dosya üstbilgisi" not in diff


def test_multiline_secret_and_fake_section_inside_value_stay_masked():
    old = (
        HEADER
        + 'config vpn certificate local\n    edit "cert"\n        set private-key "FIRST-PRIVATE\nconfig fake section\nLAST-PRIVATE"\n        set password ENC SAME-PRIVATE\n    next\nend\n'
    )
    new = old.replace("LAST-PRIVATE", "CHANGED-PRIVATE")
    diff = config_diff(old, new)
    assert 'config vpn certificate local > edit "cert"' in diff
    for value in ("FIRST-PRIVATE", "LAST-PRIVATE", "CHANGED-PRIVATE", "SAME-PRIVATE", "config fake section"):
        assert value not in diff and value not in redact_config(new)


def test_generic_cli_secret_only_change_is_not_empty():
    diff = config_diff("password BEFORE-PRIVATE\n", "password AFTER-PRIVATE\n")
    assert diff and "BEFORE-PRIVATE" not in diff and "AFTER-PRIVATE" not in diff


async def test_saved_and_live_comparisons_return_sections_and_masked_changes(
    admin_client, inventory, env, monkeypatch
):
    from netrix import worker
    from netrix.configuration import management
    from netrix.identity.security import decrypt
    from test_backup_baselines import add_snapshot
    from test_fortios_backups import NATIVE, make_device

    device, _ = make_device(admin_client, inventory)
    old = NATIVE.replace('    set hostname "fixture"', '    set hostname "fixture"\n    set admintimeout 5')
    new = old.replace("admintimeout 5", "admintimeout 15").replace("FIXTURE-SECRET", "CHANGED-PRIVATE")
    with env() as db:
        before = add_snapshot(db, device["id"], old, -3)
        after = add_snapshot(db, device["id"], new, -1, True)
        db.commit()
        before_id, after_id = before.id, after.id
        original = after.encrypted_content
    response = admin_client.get(f"/api/v1/snapshots/{after_id}/diff")
    assert response.status_code == 200
    result = response.json()
    assert result["previous_created_at"]
    assert result["previous_id"] == before_id
    assert "Bölüm: config system global" in result["diff"]
    assert "+    set admintimeout 15" in result["diff"]
    assert "+        set password " in result["diff"]
    assert "FIXTURE-SECRET" not in response.text and "CHANGED-PRIVATE" not in response.text

    async def fetch(*args):
        return new

    monkeypatch.setattr(management, "fetch_config", fetch)
    job = admin_client.post(f"/api/v1/snapshots/{before_id}/compare-live").json()
    await worker.execute(job["id"])
    comparison = admin_client.get("/api/v1/backup-comparisons/" + job["id"]).json()
    assert comparison["status"] == "succeeded"
    assert comparison["result"]["diff"] == result["diff"]
    assert comparison["result"]["changed"] is True
    assert decrypt(original) == new


def test_hash_line_inside_multiline_value_is_not_file_metadata():
    old = HEADER + 'config system global\n    set alias "first\n#old text\nlast"\nend\n'
    diff = config_diff(old, old.replace("#old text", "#new text"))
    assert "Yalnızca dosya üstbilgisi" not in diff
    assert "Bölüm: config system global" in diff


def test_hash_at_start_of_quoted_value_does_not_hide_next_section():
    old = (
        HEADER
        + 'config system global\n    set alias "first\n#last"\nend\nconfig system interface\n    edit "port1"\n        set alias "before"\n    next\nend\n'
    )
    diff = config_diff(old, old.replace('"before"', '"after"'))
    assert 'Bölüm: config system interface > edit "port1"' in diff
    assert "config system global" not in diff
