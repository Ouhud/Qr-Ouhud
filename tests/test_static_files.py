import pytest
import httpx
from httpx import ASGITransport
from fastapi.routing import APIRoute
from main import app

@pytest.mark.asyncio
async def test_all_get_routes():
    """
    Testet alle GET-Routen der FastAPI-App,
    aber ignoriert alte / nicht existierende Legacy-Routen.
    """
    transport = ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")

    failed = []

    # ❗ Liste der Legacy-Routen, die DEIN Projekt nicht mehr verwendet
    skip_routes = {
        "/password/forgot",
        "/password/reset",
        "/qr/multilink/qr/multi/",
    "/auth/register",
    "/billing/test",
    }

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue

        if "GET" not in route.methods:
            continue

        # dynamische Parameter überspringen
        if "{" in route.path:
            continue

        # ❌ Legacy-Routen ignorieren
        if route.path in skip_routes:
            continue

        try:
            response = await client.get(route.path)
            allowed = {200, 204, 302, 303, 307, 401}

            if response.status_code not in allowed:
                failed.append((route.path, response.status_code))

        except Exception as e:
            failed.append((route.path, str(e)))

    await client.aclose()

    assert not failed, (
        "\n\n❌ FEHLERHAFTE ROUTEN GEFUNDEN:\n" +
        "\n".join([f"  - {path}: {err}" for path, err in failed]) +
        "\n"
    )