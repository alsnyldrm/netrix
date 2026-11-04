"""Explicit SQL-only rehearsal stream. No source dump file and no plaintext credentials."""

import os
import pickle
import sys

import sqlalchemy as sa
from netrix import models as m
from netrix.core import engine

assert os.environ.get("NETRIX_REHEARSAL_EXPORT") == "1"
assert engine().url.database == "netrix"
# All protocol facts and the minimal inventory/reference context. Configuration
# backups, sessions, audit content and firmware binaries are not transferred.
selected = {
    "vrfs",
    "institutions",
    "sites",
    "credentials",
    "device_types",
    "discovery_scopes",
    "scope_credentials",
    "users",
    "devices",
    "interfaces",
    "dns_servers",
    "vlans",
    "integrations",
    "ip_addresses",
    "jobs",
    "ip_observations",
    "ipam_network_states",
    "ipam_results",
    "topology_links",
    "switch_mac_snapshots",
    "switch_mac_entries",
    "discovery_observations",
}
output = sys.stdout.buffer
with engine().connect() as c:
    c.execute(sa.text("SET TRANSACTION READ ONLY"))
    c.execute(sa.text("START TRANSACTION WITH CONSISTENT SNAPSHOT"))
    for table in m.Base.metadata.sorted_tables:
        if table.name not in selected:
            continue
        statement = sa.select(table)
        if table.name == "discovery_observations":
            # Only current protocol snapshots; obsolete payload histories are
            # deliberately excluded from the temporary rehearsal copy.
            metadata = list(
                c.execute(
                    sa.select(*(v for v in table.c if v.name != "evidence")).order_by(
                        table.c.created_at.desc(), table.c.id
                    )
                ).mappings()
            )
            seen, current = set(), []
            for item in metadata:
                key = (item["device_id"], item["address"], item["source"])
                if key in seen:
                    continue
                payload = c.scalar(sa.select(table.c.evidence).where(table.c.id == item["id"])) or {}
                if payload.get("failed"):
                    continue
                seen.add(key)
                current.append({**dict(item), "evidence": payload})
            items = current
        else:
            items = c.execute(statement).mappings()
        count = 0
        for item in items:
            row = dict(item)
            if table.name == "credentials":
                row["encrypted_secret"] = "rehearsal-unused"
            if table.name == "integrations":
                row["encrypted_secret"] = "rehearsal-unused"
            if table.name == "devices":
                row["base_snapshot_id"] = None
                row["approved_config_hash"] = ""
            if table.name == "users":
                row["password_hash"] = "rehearsal-login-disabled"
                row["role"] = "admin"
                row["email"] = row["id"] + "@fixture.invalid"
                row["display_name"] = "Rehearsal user"
                for key in ("avatar", "avatar_content", "avatar_data", "avatar_mime"):
                    if key in row:
                        row[key] = None
            if table.name == "jobs":
                row["active_key"] = None
                row["result"] = {}
            pickle.dump((table.name, row), output, protocol=4)
            count += 1
        output.flush()
        print(f"SQL rehearsal stream: {table.name}={count}", file=sys.stderr, flush=True)
    c.rollback()
pickle.dump(None, output, protocol=4)
output.flush()
