# =============================================================================
# 🚀 Ouhud QR – Hauptapplikation (main.py)
# =============================================================================

from __future__ import annotations
import os
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Depends, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from dotenv import load_dotenv
from typing import List, Dict

from database import engine, get_db
from models.plan import Plan
from utils.two_factor import ensure_2fa_columns
from utils.login_devices import ensure_login_devices_table
from utils.engagement_tables import ensure_engagement_tables
from utils.enterprise_tables import ensure_enterprise_tables
from utils.api_keys import ensure_api_key_columns, ensure_api_keys_table

# -------------------------------------------------------------------------
# 1️⃣ .env laden (muss ganz oben sein!)
# -------------------------------------------------------------------------
env_path = Path(__file__).resolve().parent / ".env"
print("🧩 Lade .env von:", env_path)
load_dotenv(dotenv_path=env_path)

# -------------------------------------------------------------------------
# 2️⃣ FastAPI App
# -------------------------------------------------------------------------
app = FastAPI(title="Ouhud QR", version="2.0")
ensure_2fa_columns(engine)
ensure_login_devices_table(engine)
ensure_engagement_tables(engine)
ensure_enterprise_tables(engine)
ensure_api_key_columns(engine)
ensure_api_keys_table(engine)

# -------------------------------------------------------------------------
# 3️⃣ Templates & Static
# -------------------------------------------------------------------------
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# -------------------------------------------------------------------------
# 4️⃣ Session Middleware
# -------------------------------------------------------------------------
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "ouhud-secret-key"),
    max_age=60 * 60 * 24 * 7,
    session_cookie=os.getenv("SESSION_COOKIE_NAME", "ouhud_session"),
    same_site=os.getenv("SESSION_SAME_SITE", "lax"),
    https_only=os.getenv("SESSION_HTTPS_ONLY", "0") in {"1", "true", "yes"},
)

SUPPORTED_LANGUAGES = {"de", "en", "ar"}


def _normalize_language(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw.startswith("de"):
        return "de"
    if raw.startswith("en"):
        return "en"
    if raw.startswith("ar"):
        return "ar"
    return "de"


def _detect_accept_language(header: str | None) -> str:
    raw = str(header or "").strip().lower()
    if not raw:
        return "de"
    for part in raw.split(","):
        token = part.split(";")[0].strip()
        normalized = _normalize_language(token)
        if normalized in SUPPORTED_LANGUAGES:
            return normalized
    return "de"


def _safe_redirect_path(raw_target: str | None) -> str:
    target = str(raw_target or "").strip()
    if not target:
        return "/"
    parsed = urlparse(target)
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = "/"
    if parsed.query:
        return f"{path}?{parsed.query}"
    return path


@app.middleware("http")
async def language_middleware(request: Request, call_next):
    session_data = request.scope.get("session") or {}
    has_session_lang = "lang" in session_data
    session_lang = _normalize_language(session_data.get("lang"))
    has_cookie_lang = request.cookies.get("preferred_lang") is not None
    cookie_lang = _normalize_language(request.cookies.get("preferred_lang"))
    header_lang = _detect_accept_language(request.headers.get("accept-language"))

    if has_session_lang and session_lang in SUPPORTED_LANGUAGES:
        selected = session_lang
    elif has_cookie_lang and cookie_lang in SUPPORTED_LANGUAGES:
        selected = cookie_lang
    else:
        selected = header_lang

    if selected not in SUPPORTED_LANGUAGES:
        selected = "de"

    request.state.lang = selected
    response = await call_next(request)
    if request.cookies.get("preferred_lang") != selected:
        response.set_cookie(
            "preferred_lang",
            selected,
            max_age=60 * 60 * 24 * 365,
            samesite="lax",
        )
    return response

# -------------------------------------------------------------------------
# 5️⃣ Routen laden – NUR die neuen, modularen Router
# -------------------------------------------------------------------------
from routes import auth
from routes import dashboard
from routes import qr_base
from routes import qr_resolve   # für /d/<slug>
from routes import dyn
from routes import user_profile
from routes import settings
from routes import billing
from routes import team
from routes import sla
from routes import api
from routes import legal

# Individual QR Routes
from routes.qr import (
    url,
    vcard,
    pdf,
    wifi,
    email,
    sms,
    tel,
    social,
    event,
    geo,
    multilink,
    product,
    payment,
    edit_qr,
    wallet,
    gs1,
    app_deeplink,
    review,
    booking,
    lead,
    feedback,
    coupon,
)

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(user_profile.router)
app.include_router(settings.router)
app.include_router(billing.router)
app.include_router(team.router)
app.include_router(sla.router)
app.include_router(api.router)
app.include_router(legal.router)

# zentrale QR-Erstellung
app.include_router(qr_base.router)

# zentraler Resolver
app.include_router(qr_resolve.router)
app.include_router(dyn.router)

# Individual QR Type Routes
app.include_router(url.router)
app.include_router(vcard.router)
app.include_router(pdf.router)
app.include_router(wifi.router)
app.include_router(email.router)
app.include_router(sms.router)
app.include_router(tel.router)
app.include_router(social.router)
app.include_router(event.router)
app.include_router(geo.router)
app.include_router(multilink.router)
app.include_router(product.router)
app.include_router(payment.router)
app.include_router(wallet.router)
app.include_router(gs1.router)
app.include_router(app_deeplink.router)
app.include_router(review.router)
app.include_router(booking.router)
app.include_router(lead.router)
app.include_router(feedback.router)
app.include_router(coupon.router)

# Central edit routes for all QR types
app.include_router(edit_qr.router)

# -------------------------------------------------------------------------
# 6️⃣ Home
# -------------------------------------------------------------------------
def _fallback_home_plans() -> List[Dict[str, object]]:
    return [
        {
            "name": "Basic",
            "price": 4.99,
            "qr_limit": 10,
            "free_months": 1,
            "has_api_access": False,
        },
        {
            "name": "Pro",
            "price": 14.99,
            "qr_limit": 50,
            "free_months": 3,
            "has_api_access": False,
        },
        {
            "name": "Business",
            "price": 29.99,
            "qr_limit": 250,
            "free_months": 6,
            "has_api_access": True,
        },
        {
            "name": "Enterprise",
            "price": 0.0,
            "qr_limit": 999999,
            "free_months": 0,
            "has_api_access": True,
        },
    ]


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    sort_order = {"basic": 1, "pro": 2, "business": 3, "enterprise": 4}
    plans: List[object]
    try:
        db_plans = db.query(Plan).all()
        if db_plans:
            plans = sorted(
                db_plans,
                key=lambda p: sort_order.get(str(getattr(p, "name", "")).lower(), 99),
            )
        else:
            plans = _fallback_home_plans()
    except Exception:
        plans = _fallback_home_plans()

    return templates.TemplateResponse("index.html", {"request": request, "plans": plans})


@app.post("/language", include_in_schema=False)
def set_language(
    request: Request,
    language: str = Form("de"),
    next: str = Form("/"),
):
    selected = _normalize_language(language)
    if selected not in SUPPORTED_LANGUAGES:
        selected = "de"

    request.session["lang"] = selected
    target = _safe_redirect_path(next or request.headers.get("referer") or "/")
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        "preferred_lang",
        selected,
        max_age=60 * 60 * 24 * 365,
        samesite="lax",
    )
    return response

# -------------------------------------------------------------------------
# 6.1️⃣ Favicon
# -------------------------------------------------------------------------
@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse("static/favicon.ico", media_type="image/x-icon")

# -------------------------------------------------------------------------
# 6.2️⃣ Example QR Image
# -------------------------------------------------------------------------
@app.get("/example-qr")
def example_qr():
    return FileResponse("static/default-qr.png", media_type="image/png")

# -------------------------------------------------------------------------
# 6.3️⃣ Service Worker
# -------------------------------------------------------------------------
@app.get("/sw.js")
def service_worker():
    return FileResponse("static/sw.js", media_type="application/javascript")

# -------------------------------------------------------------------------
# 6.4️⃣ Chrome DevTools Well-Known Probe (noise-free logs)
# -------------------------------------------------------------------------
@app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
def chrome_devtools_probe() -> Response:
    # Chrome probes this endpoint locally; 204 avoids noisy 404 logs.
    return Response(status_code=204)

# -------------------------------------------------------------------------
# 7️⃣ Debug Route
# -------------------------------------------------------------------------
@app.get("/debug/routes")
def debug_routes() -> List[Dict[str, str]]:
    return [{"path": r.path, "name": r.name} for r in app.routes]
