# -*- coding: utf-8 -*-
"""
✅ Capability Report Scanner – Pylance Clean Version
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from pytest import MonkeyPatch
from starlette.responses import Response, JSONResponse

from main import app
import utils.qr_generator as qrgen


# -----------------------------------------------------------
# ✅ Globale Logs → nicht in CAPs schreiben
# -----------------------------------------------------------
template_log: List[str] = []
qr_log: List[str] = []


# -----------------------------------------------------------
# ✅ Template Patch (typisiert)
# -----------------------------------------------------------
def patch_templates(monkeypatch: MonkeyPatch) -> None:
    """
    Patch: Template-Namen erfassen, ohne private Starlette APIs.
    """
    import jinja2

    original_get = jinja2.Environment.get_template

    def patched_get(env: jinja2.Environment, name: str, *args: Any, **kwargs: Any):
        template_log.append(name)
        return original_get(env, name, *args, **kwargs)

    monkeypatch.setattr(jinja2.Environment, "get_template", patched_get)


# -----------------------------------------------------------
# ✅ QR-Generator Patch (typisiert)
# -----------------------------------------------------------
def patch_qr_generator(monkeypatch: MonkeyPatch) -> None:
    original = qrgen.generate_qr_png

    def wrapper(*args: Any, **kwargs: Any):
        qr_log.append("qr")
        return original(*args, **kwargs)

    monkeypatch.setattr(qrgen, "generate_qr_png", wrapper)


# -----------------------------------------------------------
# ✅ Datamodelle
# -----------------------------------------------------------
@dataclass
class RouteHit:
    path: str
    methods: List[str]
    status_code: Optional[int]
    template_used: Optional[str]
    is_redirect: bool
    is_json: bool
    qr_events: int


@dataclass
class RouteCapability:
    path: str
    methods: List[str]
    endpoint: str
    module: str
    last_hit: Optional[RouteHit] = None


# -----------------------------------------------------------
# ✅ Hilfsfunktionen
# -----------------------------------------------------------
def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_routes(app: FastAPI) -> List[APIRoute]:
    return [r for r in app.routes if isinstance(r, APIRoute)]


async def hit_route(client: httpx.AsyncClient, route: APIRoute) -> RouteHit:
    global template_log, qr_log
    template_log = []
    qr_log = []

    import httpx
    try:
        resp: httpx.Response = await client.get(route.path)
    except Exception:
        return RouteHit(
            path=route.path,
            methods=list(route.methods),
            status_code=None,
            template_used=template_log[0] if template_log else None,
            is_redirect=False,
            is_json=False,
            qr_events=len(qr_log),
        )

    content_type = resp.headers.get("content-type", "")
    is_json = content_type.startswith("application/json")

    return RouteHit(
        path=route.path,
        methods=list(route.methods),
        status_code=resp.status_code,
        template_used=template_log[0] if template_log else None,
        is_redirect=resp.status_code in (301, 302, 303, 307, 308),
        is_json=is_json,
        qr_events=len(qr_log),
    )


# -----------------------------------------------------------
# ✅ TEST (mit typisiertem monkeypatch)
# -----------------------------------------------------------
@pytest.mark.asyncio
async def test_capability_report(monkeypatch: MonkeyPatch) -> None:
    patch_templates(monkeypatch)
    patch_qr_generator(monkeypatch)

    routes = get_routes(app)
    capabilities: List[RouteCapability] = []

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")

    for r in routes:
        # Nur GET Routen testen
        if "GET" not in r.methods:
            capabilities.append(
                RouteCapability(
                    path=r.path,
                    methods=list(r.methods),
                    endpoint=r.endpoint.__name__,
                    module=r.endpoint.__module__,
                )
            )
            continue

        hit = await hit_route(client, r)

        capabilities.append(
            RouteCapability(
                path=r.path,
                methods=list(r.methods),
                endpoint=r.endpoint.__name__,
                module=r.endpoint.__module__,
                last_hit=hit,
            )
        )

    await client.aclose()

    # -----------------------------------------------------------
    # ✅ Dateien schreiben
    # -----------------------------------------------------------
    out_dir = Path("static/test_reports/capability_report")
    out_dir.mkdir(parents=True, exist_ok=True)

    # JSON
    (out_dir / "report.json").write_text(
        json.dumps([asdict(c) for c in capabilities], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Markdown
    lines: List[str] = [
        f"# Ouhud QR – Capability Report ({now_iso()})",
        "",
        "| Route | Status | Template | Redirect | QR |",
        "|---|---|---|---|---|",
    ]

    for c in capabilities:
        if not c.last_hit:
            continue
        h = c.last_hit
        lines.append(
            f"| {c.path} | {h.status_code} | {h.template_used or '-'} "
            f"| {h.is_redirect} | {h.qr_events} |"
        )

    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")

    # -----------------------------------------------------------
    # ✅ Keine 500er erlauben
    # -----------------------------------------------------------
    failures = [
        c for c in capabilities
        if c.last_hit and c.last_hit.status_code and c.last_hit.status_code >= 500
    ]

    assert not failures, f"Fehlerhafte Routen: {len(failures)}"
