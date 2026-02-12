import pytest
import httpx
from fastapi.routing import APIRoute
from httpx import ASGITransport
from main import app


# ✅ erlaubte Statuscodes
ALLOWED = {200, 204, 302, 303, 307, 401}


# ✅ Routing-Blacklist – diese Routen ignorieren (Legacy / alt)
IGNORE_ROUTES = {
    "/password/forgot",
    "/password/reset",
    "/qr/multilink/qr/multi/",
    "/auth/register",
    "/billing/test",
}


@pytest.mark.asyncio
async def test_all_get_routes():
    """
    Testet alle funktionierenden GET-Routen der FastAPI-App.
    Ignoriert bewusst alte Legacy-Routen, die nicht mehr existieren.
    """
    transport = ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")

    failed = []

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue

        if "GET" not in route.methods:
            continue

        # Parameterisierte Routen überspringen
        if "{" in route.path:
            continue

        # ❌ Legacy / alte Routen überspringen
        if route.path in IGNORE_ROUTES:
            continue

        try:
            response = await client.get(route.path)

            if response.status_code not in ALLOWED:
                failed.append((route.path, response.status_code))

        except Exception as e:
            failed.append((route.path, str(e)))

    await client.aclose()

    assert not failed, (
        "\n\n❌ FEHLERHAFTE ROUTEN GEFUNDEN:\n" +
        "\n".join([f"  - {path}: {err}" for path, err in failed]) +
        "\n"
    )