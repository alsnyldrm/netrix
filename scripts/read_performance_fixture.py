"""Local-only fixture; optionally compare an earlier compiled UI against the same API."""

import os
from pathlib import Path

import uvicorn
from vlan_configuration_fixture import main

if os.environ.get("NETRIX_BROWSER_DIST"):
    main.STATIC = Path(os.environ["NETRIX_BROWSER_DIST"]).resolve()
    for route in main.app.routes:
        if getattr(route, "name", None) == "assets":
            route.app.directory = str(main.STATIC / "assets")
            route.app.all_directories = [str(main.STATIC / "assets")]

uvicorn.run(main.app, host="127.0.0.1", port=8215, log_level="warning")
