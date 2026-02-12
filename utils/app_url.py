from __future__ import annotations

import os
from typing import Optional

from fastapi import Request


def resolve_app_base_url(request: Optional[Request] = None, env_var: str = "APP_DOMAIN") -> str:
    """
    Liefert die korrekte Basis-URL fuer die aktuelle Umgebung.

    Prioritaet:
    1) Wenn Request auf localhost/127.0.0.1 laeuft -> Request-Host verwenden
    2) Sonst env_var (z.B. APP_DOMAIN), falls gesetzt
    3) Sonst Request-Host
    4) Sonst localhost-Fallback
    """
    request_base = str(request.base_url).rstrip("/") if request is not None else ""
    env_base = str(os.getenv(env_var, "")).strip().rstrip("/")

    if request_base and ("localhost" in request_base or "127.0.0.1" in request_base):
        return request_base
    if env_base:
        return env_base
    if request_base:
        return request_base
    return "http://127.0.0.1:8000"

