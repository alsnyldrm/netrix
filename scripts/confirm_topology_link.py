"""Record an explicitly confirmed link by device ID; does not contact devices."""
import argparse

from netrix.core import session_factory
from netrix.discovery.manual_links import confirm_link

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-id', required=True)
    parser.add_argument('--remote-id', required=True)
    args = parser.parse_args()
    with session_factory()() as db:
        link = confirm_link(db, args.local_id, args.remote_id)
        db.commit()
        print(f'Confirmed device link: {link.id}; physical ports remain unspecified.')
