from __future__ import annotations

from fastapi import Request

from utils.app_url import resolve_app_base_url


def build_dynamic_url(request: Request, slug: str) -> str:
    """
    Baut eine dynamische URL passend zur aktuellen Umgebung:
    - lokal: aktueller Host (localhost/127.0.0.1)
    - prod/staging: APP_DOMAIN aus .env, sonst aktueller Host
    """
    return f"{resolve_app_base_url(request)}/d/{slug}"
