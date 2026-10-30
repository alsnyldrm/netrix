"""Reclassify snapshot flags for explicitly selected devices; never read a device."""

import argparse
import json

from netrix.configuration.history import repair_change_flags
from netrix.core import session_factory
from netrix.services import publish

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--device-id", action="append", required=True)
parser.add_argument("--apply", action="store_true", help="Commit corrections; otherwise preview only")
args = parser.parse_args()
with session_factory()() as db:
    result = {
        device_id: repair_change_flags(db, device_id, apply=args.apply)
        for device_id in sorted(set(args.device_id))
    }
    if args.apply:
        db.commit()
        publish()
    else:
        db.rollback()
    print(json.dumps({"applied": args.apply, "changes": result}))
