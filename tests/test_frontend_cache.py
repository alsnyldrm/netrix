"""The application shell must not keep removed navigation in browser caches."""

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.testclient import TestClient
from netrix.main import security_headers


@pytest.mark.parametrize("path", ["/", "/index.html", "/devices"])
def test_html_shell_is_not_cacheable(path):
    app = FastAPI()
    app.middleware("http")(security_headers)

    @app.get("/{path:path}")
    def shell(path: str):
        return HTMLResponse("<!doctype html><title>NETRIX</title>")

    with TestClient(app) as client:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers.get("cache-control") == "no-store"


def test_asset_cache_policy_is_preserved():
    app = FastAPI()
    app.middleware("http")(security_headers)

    @app.get("/assets/app-hash.js")
    def asset():
        return PlainTextResponse(
            "export {};", headers={"Cache-Control": "public, max-age=31536000, immutable"}
        )

    with TestClient(app) as client:
        response = client.get("/assets/app-hash.js")
        assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
