"""Reapply saved neighbor deletions. No device connections; dry run by default."""

import argparse
import json

from netrix.core import session_factory
from netrix.discovery.link_deletions import repair_stored_exclusions

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--apply", action="store_true")
args = parser.parse_args()
with session_factory()() as db:
    result = repair_stored_exclusions(db)
    if args.apply:
        db.commit()
    else:
        db.rollback()
    print(json.dumps({**result, "applied": args.apply}))
