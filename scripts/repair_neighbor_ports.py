"""Repair labels from stored CDP/LLDP evidence. No device connections; dry run by default."""

import argparse
import json

from netrix.core import session_factory
from netrix.discovery.links import repair_stored_ports

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--apply", action="store_true")
args = parser.parse_args()
with session_factory()() as db:
    result = repair_stored_ports(db)
    if args.apply:
        db.commit()
    else:
        db.rollback()
    print(json.dumps({**result, "applied": args.apply}))
