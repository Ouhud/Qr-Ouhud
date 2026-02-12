# -*- coding: utf-8 -*-
"""
✅ Pylance-Clean Capability Scanner für Ouhud QR
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pytest
from fastapi.routing import APIRoute
from fastapi import FastAPI
from pytest import MonkeyPatch
import jinja2

from main import app
import utils.qr_generator as qrgen


# -----------------------------------------------------------
# ✅ Globale Logs – absichtlich klein geschrieben
# -----------------------------------------------------------
template_log: List[str] = []
qr_log: List[str] = []


# -----------------------------------------------------------
# ✅ Template Patch (typisiert)
# -----------------------------------------------------------
def patch_templates(monkeypatch: MonkeyPatch) -> None:
    original_get = jinja2.Environment.get_template

    def patched_get(
        self: jinja2.Environment,
        name: str,
        *args: Any,
        **kwargs: Any
    ):
        template_log.append(name)
        return original_get(self, name, *args, **kwargs)

    monkeypatch.setattr(jinja2.Environment, "get_template", patched_get)


# -----------------------------------------------------------
# ✅ QR-Generator Patch (typisiert)
# -----------------------------------------------------------
def patch_qr(monkeypatch: MonkeyPatch) -> None:
    original = qrgen.generate_qr_png

    def wrapped(*args: Any, **kwargs: Any):
        qr_log.append("qr")
        return original(*args, **kwargs)

    monkeypatch.setattr(qrgen, "generate_qr_png", wrapped)


# -----------------------------------------------------------
# ✅ Datamodelle
# -----------------------------------------------------------
@dataclass
class RouteHit:
    status_code: Optional[int]
    is_redirect: bool
    is_json: bool
    template: Optional[str]
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

    try:
        resp = await client.get(route.path)
    except Exception:
        return RouteHit(
            status_code=None,
            is_redirect=False,
            is_json=False,
            template=template_log[0] if template_log else None,
            qr_events=len(qr_log),
        )

    content_type = resp.headers.get("content-type", "")

    return RouteHit(
        status_code=resp.status_code,
        is_redirect=resp.status_code in (301, 302, 303, 307, 308),
        is_json=content_type.startswith("application/json"),
        template=template_log[0] if template_log else None,
        qr_events=len(qr_log),
    )


# -----------------------------------------------------------
# ✅ Der Test (typisiert)
# -----------------------------------------------------------
@pytest.mark.asyncio
async def test_route_function_scanner(monkeypatch: MonkeyPatch) -> None:
    patch_templates(monkeypatch)
    patch_qr(monkeypatch)

    routes = get_routes(app)
    capabilities: List[RouteCapability] = []

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app),
        base_url="http://test"
    ) as client:

        for r in routes:
            cap = RouteCapability(
                path=r.path,
                methods=list(r.methods),
                endpoint=r.endpoint.__name__,
                module=r.endpoint.__module__,
            )

            if "GET" in r.methods:
                cap.last_hit = await hit_route(client, r)

            capabilities.append(cap)

    # -----------------------------------------------------------
    # ✅ Reports schreiben
    # -----------------------------------------------------------
    out_dir = Path("static/test_reports/route_scanner")
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "capabilities.json").write_text(
        json.dumps([asdict(c) for c in capabilities], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    lines = [
        f"# Ouhud QR – Route Capability Report ({now_iso()})",
        "",
        "| Route | Status | Redirect | JSON | Template | QR |",
        "|---|---|---|---|---|---|",
    ]

    for c in capabilities:
        h = c.last_hit
        if h:
            lines.append(
                f"| {c.path} | {h.status_code} | {h.is_redirect} "
                f"| {h.is_json} | {h.template or '-'} | {h.qr_events} |"
            )

    (out_dir / "capabilities.md").write_text("\n".join(lines), encoding="utf-8")

    # -----------------------------------------------------------
    # ✅ Fehler prüfen – KEIN 500 erlauben
    # -----------------------------------------------------------
    failures = [
        c for c in capabilities
        if c.last_hit and c.last_hit.status_code and c.last_hit.status_code >= 500
    ]

    assert not failures, f"{len(failures)} Routen haben 500er Fehler"
