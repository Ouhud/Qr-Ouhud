# =============================================================================
# ⚙️ routes/settings.py
# -----------------------------------------------------------------------------
# Zentrale Account- und Einstellungsseite für Benutzer.
# Enthält:
#   - Benutzerinformationen anzeigen & aktualisieren
#   - Tarif- & QR-Code-Übersicht
#   - Abonnement & Rechnungen (Billing)
#   - Sicherheit (Passwort ändern, 2FA-Platzhalter)
#   - Kontakt-Weiterleitung für API-Zugang
# -----------------------------------------------------------------------------
# Autor: Hamza Mehmalat
# Projekt: Ouhud QR
# =============================================================================

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone
from models.api_key import APIKey
from utils.api_keys import (
    generate_api_key,
    hash_api_key,
    key_last4,
    key_prefix,
    serialize_api_key_row,
)
from routes.auth import get_current_user
from database import get_db
from models.qrcode import QRCode
from models.login_device import LoginDevice
from passlib.hash import bcrypt
from utils.two_factor import (
    generate_base32_secret,
    build_otpauth_uri,
    qr_data_uri,
    verify_totp,
)
from utils.billing_access import is_billing_exempt_user

# -------------------------------------------------------------------------
# 🔹 Router-Setup & Templates
# -------------------------------------------------------------------------
router = APIRouter(
    prefix="/settings",
    tags=["Settings"],
    responses={404: {"description": "Nicht gefunden"}}
)
templates = Jinja2Templates(directory="templates")


def _api_key_name_exists(
    db: Session,
    user_id: int,
    name: str,
    exclude_key_id: int | None = None,
) -> bool:
    q = db.query(APIKey).filter(
        APIKey.user_id == user_id,
        APIKey.active_name == name.strip().lower(),
    )
    if exclude_key_id is not None:
        q = q.filter(APIKey.id != exclude_key_id)
    return q.first() is not None


def _next_default_key_name(db: Session, user_id: int) -> str:
    base = "Default"
    if not _api_key_name_exists(db, user_id, base):
        return base
    i = 2
    while True:
        candidate = f"Default {i}"
        if not _api_key_name_exists(db, user_id, candidate):
            return candidate
        i += 1

# =============================================================================
# ⚙️ 1. Allgemeine Einstellungsseite
# =============================================================================
@router.get("/", response_class=HTMLResponse)
def settings_page(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    """Zeigt die Einstellungsseite mit Benutzerprofil, Tarifdetails und QR-Übersicht."""
    lang = getattr(getattr(request, "state", None), "lang", "de")
    qrcodes = db.query(QRCode).filter(QRCode.user_id == user.id).all()
    qr_count = len(qrcodes)

    if lang == "en":
        basic_features = ["📦 Up to 10 QR codes", "🎁 1 month free", "🔒 No API access"]
        pro_features = ["📦 Up to 50 QR codes", "🎁 3 months free", "🔒 No API access"]
        business_features = ["📦 Up to 250 QR codes", "🎁 6 months free", "🔗 API access included"]
        enterprise_features = ["📦 Unlimited QR codes", "🔗 API access included", "👨‍💼 Custom solutions & SLA"]
        basic_price, pro_price, business_price, enterprise_price = (
            "4.99 € / month",
            "14.99 € / month",
            "29.99 € / month",
            "On request",
        )
    elif lang == "ar":
        basic_features = ["📦 حتى 10 رموز QR", "🎁 شهر مجاني", "🔒 بدون API"]
        pro_features = ["📦 حتى 50 رمز QR", "🎁 3 أشهر مجانية", "🔒 بدون API"]
        business_features = ["📦 حتى 250 رمز QR", "🎁 6 أشهر مجانية", "🔗 API متاح"]
        enterprise_features = ["📦 رموز QR غير محدودة", "🔗 API متاح", "👨‍💼 حلول مخصصة وSLA"]
        basic_price, pro_price, business_price, enterprise_price = (
            "4.99 € / شهريًا",
            "14.99 € / شهريًا",
            "29.99 € / شهريًا",
            "حسب الطلب",
        )
    else:
        basic_features = ["📦 Bis zu 10 QR-Codes", "🎁 1 Monat(e) gratis", "🔒 Kein API-Zugang"]
        pro_features = ["📦 Bis zu 50 QR-Codes", "🎁 3 Monat(e) gratis", "🔒 Kein API-Zugang"]
        business_features = ["📦 Bis zu 250 QR-Codes", "🎁 6 Monat(e) gratis", "🔗 API-Zugang inklusive"]
        enterprise_features = ["📦 Unbegrenzte QR-Codes", "🔗 API-Zugang inklusive", "👨‍💼 Individuelle Lösungen & SLA"]
        basic_price, pro_price, business_price, enterprise_price = (
            "4,99 € / Monat",
            "14,99 € / Monat",
            "29,99 € / Monat",
            "Auf Anfrage",
        )

    # 💼 Dynamische Tariflogik
    if qr_count <= 10:
        plan, color, price, features = (
            "Basic", "emerald", basic_price, basic_features
        )
    elif qr_count <= 50:
        plan, color, price, features = (
            "Pro", "amber", pro_price, pro_features
        )
    elif qr_count <= 250:
        plan, color, price, features = (
            "Business", "blue", business_price, business_features
        )
    else:
        plan, color, price, features = (
            "Enterprise", "indigo", enterprise_price, enterprise_features
        )

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "user": user,
            "plan": plan,
            "price": price,
            "color": color,
            "features": features,
            "qr_count": qr_count,
            "qrcodes": qrcodes,
            "current_language": getattr(request.state, "lang", "de"),
        },
    )


# =============================================================================
# 📝 2. Profil aktualisieren
# =============================================================================
@router.post("/update-profile")
def update_profile(
    first_name: str = Form(""),
    last_name: str = Form(""),
    username: str = Form(...),
    email: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    user.first_name = first_name.strip()
    user.last_name = last_name.strip()
    user.username = username.strip()
    user.email = email.strip()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return RedirectResponse("/settings/?error=duplicate_user", status_code=303)
    print(f"[UPDATE] Benutzer {user.username} ({user.email}) hat sein Profil geändert.")
    return RedirectResponse("/settings/?msg=profile_updated", status_code=303)


# =============================================================================
# 💳 3. Abonnement- & Rechnungsseite
# =============================================================================
@router.get("/billing", response_class=HTMLResponse)
def billing_page(
    request: Request,
    user=Depends(get_current_user)
):
    """Zeigt Abonnementdetails und Rechnungsverlauf an."""
    lang = getattr(getattr(request, "state", None), "lang", "de")
    current_plan = user.plan
    plan_name = current_plan.name if current_plan else "Basic"
    if current_plan and float(current_plan.price or 0) > 0:
        if lang == "en":
            price = f"{float(current_plan.price):.2f} € / month"
        elif lang == "ar":
            price = f"{float(current_plan.price):.2f} € / شهريًا"
        else:
            price = f"{float(current_plan.price):.2f} € / Monat"
    elif current_plan:
        price = "On request" if lang == "en" else ("حسب الطلب" if lang == "ar" else "Auf Anfrage")
    else:
        price = "4.99 € / month" if lang == "en" else ("4.99 € / شهريًا" if lang == "ar" else "4,99 € / Monat")

    raw_status = str(getattr(user, "plan_status", "active") or "active").lower()
    billing_exempt = is_billing_exempt_user(user)
    if billing_exempt:
        raw_status = "active"

    if raw_status in {"active", "trialing"}:
        status = "Active" if lang == "en" else ("نشط" if lang == "ar" else "Aktiv")
    elif raw_status in {"cancelled", "canceled", "unpaid"}:
        status = "Cancelled" if lang == "en" else ("ملغى" if lang == "ar" else "Gekündigt")
    else:
        status = "In progress" if lang == "en" else ("قيد المعالجة" if lang == "ar" else "In Bearbeitung")

    expiry = getattr(user, "plan_expiry", None)
    next_billing = expiry.strftime("%d.%m.%Y") if expiry else None
    if billing_exempt:
        next_billing = None
        price = (
            "0.00 € / month (Owner access)"
            if lang == "en"
            else ("0.00 € / شهريًا (وصول المالك)" if lang == "ar" else "0,00 € / Monat (Owner-Zugang)")
        )

    if lang == "en":
        feature_map = {
            "basic": ["📦 Up to 10 QR codes", "🎁 1 month free", "🔒 No API access"],
            "pro": ["📦 Up to 50 QR codes", "🎁 3 months free", "🎨 Advanced design"],
            "business": ["📦 Up to 250 QR codes", "🔗 API access included", "👥 Team features"],
            "enterprise": ["📦 Unlimited", "🔗 API access", "🛠️ Custom support"],
        }
    elif lang == "ar":
        feature_map = {
            "basic": ["📦 حتى 10 رموز QR", "🎁 شهر مجاني", "🔒 بدون API"],
            "pro": ["📦 حتى 50 رمز QR", "🎁 3 أشهر مجانية", "🎨 تصميم متقدم"],
            "business": ["📦 حتى 250 رمز QR", "🔗 API متاح", "👥 ميزات الفريق"],
            "enterprise": ["📦 غير محدود", "🔗 API متاح", "🛠️ دعم مخصص"],
        }
    else:
        feature_map = {
            "basic": ["📦 Bis zu 10 QR-Codes", "🎁 1 Monat kostenlos", "🔒 Kein API-Zugang"],
            "pro": ["📦 Bis zu 50 QR-Codes", "🎁 3 Monate kostenlos", "🎨 Erweitertes Design"],
            "business": ["📦 Bis zu 250 QR-Codes", "🔗 API-Zugang inklusive", "👥 Team-Funktionen"],
            "enterprise": ["📦 Unbegrenzt", "🔗 API-Zugang", "🛠️ Individuelle Betreuung"],
        }
    features = feature_map.get(plan_name.lower(), feature_map["basic"])

    payment_required = raw_status in {"past_due", "incomplete", "incomplete_expired", "unpaid"}
    trial_end = next_billing if raw_status == "trialing" else None
    if billing_exempt:
        payment_required = False
        trial_end = None

    # Stripe-Rechnungen könnten später live aus Stripe API geladen werden.
    invoices: list[dict[str, str]] = []

    return templates.TemplateResponse(
        "settings_billing.html",
        {
            "request": request,
            "user": user,
            "plan": plan_name,
            "price": price,
            "status": status,
            "next_billing": next_billing,
            "features": features,
            "payment_required": payment_required,
            "trial_end": trial_end,
            "billing_exempt": billing_exempt,
            "invoices": invoices,
        },
    )


# =============================================================================
# 🔒 4. Sicherheitsseite (Passwort & 2FA)
# =============================================================================
@router.get("/security", response_class=HTMLResponse)
def security_page(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    """Zeigt die Sicherheitsseite (Passwort ändern, 2FA)."""
    session_token = request.session.get("session_token")
    devices = []
    try:
        rows = (
            db.query(LoginDevice)
            .filter(LoginDevice.user_id == user.id, LoginDevice.active == True)
            .order_by(LoginDevice.last_seen_at.desc())
            .all()
        )
        devices = [
            {
                "id": d.id,
                "device": f"{d.device_name}{' (dieses Gerät)' if session_token and d.session_token == session_token else ''}",
                "ip": d.ip_address or "-",
                "last_login": (d.last_seen_at or d.created_at).strftime("%d.%m.%Y %H:%M") if (d.last_seen_at or d.created_at) else "-",
            }
            for d in rows
        ]
    except Exception as exc:
        print(f"⚠️ Login-Geräte konnten nicht geladen werden: {exc}")

    pending_secret = request.session.get("pending_2fa_secret")
    twofa_qr = None
    twofa_secret = None
    if pending_secret:
        twofa_secret = pending_secret
        twofa_qr = qr_data_uri(build_otpauth_uri(pending_secret, user.email, issuer="Ouhud QR"))

    key_rows = (
        db.query(APIKey)
        .filter(APIKey.user_id == user.id, APIKey.revoked_at.is_(None))
        .order_by(APIKey.created_at.desc())
        .all()
    )
    api_keys = [serialize_api_key_row(r) for r in key_rows]
    newly_created_api_key = request.session.pop("new_api_key", None)

    return templates.TemplateResponse(
        "settings_security.html",
        {
            "request": request,
            "user": user,
            "plan": "Pro",
            "price": "14,99 € / Monat",
            "plan_status": "active",
            "twofa_enabled": bool(getattr(user, "two_factor_enabled", False)),
            "twofa_qr": twofa_qr,
            "twofa_secret": twofa_secret,
            "devices": devices,
            "api_keys": api_keys,
            "newly_created_api_key": newly_created_api_key,
        },
    )


@router.post("/security/change-password")
def change_password(
    old_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    """Ändert das Benutzerpasswort nach Bestätigung."""
    if not bcrypt.verify(old_password, user.password_hash):
        return RedirectResponse("/settings/security?error=wrong_old", status_code=303)
    if new_password != confirm_password:
        return RedirectResponse("/settings/security?error=nomatch", status_code=303)

    user.password_hash = bcrypt.hash(new_password)
    db.commit()
    print(f"[PASS] Benutzer {user.email} hat sein Passwort geändert.")
    return RedirectResponse("/settings/security?msg=updated", status_code=303)


@router.post("/security/2fa/start")
def start_2fa_setup(
    request: Request,
    user=Depends(get_current_user),
):
    """Startet 2FA-Setup und erzeugt temporären Secret im Session-Kontext."""
    if getattr(user, "two_factor_enabled", False):
        return RedirectResponse("/settings/security?error=2fa_already_enabled", status_code=303)

    request.session["pending_2fa_secret"] = generate_base32_secret()
    return RedirectResponse("/settings/security?msg=2fa_setup_started", status_code=303)


@router.post("/security/2fa/confirm")
def confirm_2fa_setup(
    request: Request,
    otp_code: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Bestätigt 2FA-Einrichtung mit TOTP-Code und aktiviert 2FA."""
    pending_secret = request.session.get("pending_2fa_secret")
    if not pending_secret:
        return RedirectResponse("/settings/security?error=2fa_no_setup", status_code=303)

    if not verify_totp(pending_secret, otp_code):
        return RedirectResponse("/settings/security?error=2fa_invalid_code", status_code=303)

    user.two_factor_secret = pending_secret
    user.two_factor_enabled = True
    db.commit()
    request.session.pop("pending_2fa_secret", None)
    return RedirectResponse("/settings/security?msg=2fa_enabled", status_code=303)


@router.post("/security/2fa/disable")
def disable_2fa(
    request: Request,
    password: str = Form(...),
    otp_code: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Deaktiviert 2FA nur nach Passwort + gültigem OTP-Code."""
    if not getattr(user, "two_factor_enabled", False) or not user.two_factor_secret:
        return RedirectResponse("/settings/security?error=2fa_not_enabled", status_code=303)

    if not bcrypt.verify(password, user.password_hash):
        return RedirectResponse("/settings/security?error=2fa_wrong_password", status_code=303)

    if not verify_totp(user.two_factor_secret, otp_code):
        return RedirectResponse("/settings/security?error=2fa_invalid_code", status_code=303)

    user.two_factor_enabled = False
    user.two_factor_secret = None
    db.commit()
    request.session.pop("pending_2fa_secret", None)
    return RedirectResponse("/settings/security?msg=2fa_disabled", status_code=303)


@router.get("/security/device/remove/{device_id}")
def remove_device_session(
    request: Request,
    device_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Beendet eine aktive Login-Sitzung eines Geräts."""
    try:
        dev = (
            db.query(LoginDevice)
            .filter(LoginDevice.id == device_id, LoginDevice.user_id == user.id, LoginDevice.active == True)
            .first()
        )
    except Exception:
        return RedirectResponse("/settings/security?error=device_not_found", status_code=303)
    if not dev:
        return RedirectResponse("/settings/security?error=device_not_found", status_code=303)

    dev.active = False
    dev.last_seen_at = datetime.now(timezone.utc)
    db.commit()

    # Falls aktuelles Gerät beendet wurde: direkt ausloggen
    if request.session.get("session_token") == dev.session_token:
        request.session.clear()
        return RedirectResponse("/auth/login?msg=session_ended", status_code=303)

    return RedirectResponse("/settings/security?msg=device_removed", status_code=303)


@router.post("/security/api-keys/create")
def create_api_key(
    request: Request,
    name: str = Form("Default"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Erstellt einen neuen API-Key (wird nur einmal vollständig angezeigt)."""
    clean_name = (name or "Default").strip()[:120] or "Default"
    if _api_key_name_exists(db, user.id, clean_name):
        return RedirectResponse("/settings/security?error=api_key_name_exists", status_code=303)

    raw_key = generate_api_key()
    row = APIKey(
        user_id=user.id,
        name=clean_name,
        active_name=clean_name.lower(),
        key_prefix=key_prefix(raw_key),
        key_hash=hash_api_key(raw_key),
        last4=key_last4(raw_key),
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    request.session["new_api_key"] = raw_key
    return RedirectResponse("/settings/security?msg=api_key_created", status_code=303)


@router.get("/security/api/new")
def create_api_key_legacy(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Legacy compatibility route used by old template links.
    Creates a default key and redirects to security page.
    """
    auto_name = _next_default_key_name(db, user.id)
    raw_key = generate_api_key()
    row = APIKey(
        user_id=user.id,
        name=auto_name,
        active_name=auto_name.lower(),
        key_prefix=key_prefix(raw_key),
        key_hash=hash_api_key(raw_key),
        last4=key_last4(raw_key),
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    request.session["new_api_key"] = raw_key
    return RedirectResponse("/settings/security?msg=api_key_created", status_code=303)


@router.post("/security/api-keys/{key_id}/rename")
def rename_api_key(
    key_id: int,
    name: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    clean_name = name.strip()[:120] or "Default"
    row = (
        db.query(APIKey)
        .filter(APIKey.id == key_id, APIKey.user_id == user.id, APIKey.revoked_at.is_(None))
        .first()
    )
    if not row:
        return RedirectResponse("/settings/security?error=api_key_not_found", status_code=303)
    if _api_key_name_exists(db, user.id, clean_name, exclude_key_id=row.id):
        return RedirectResponse("/settings/security?error=api_key_name_exists", status_code=303)
    row.name = clean_name
    row.active_name = clean_name.lower()
    db.commit()
    return RedirectResponse("/settings/security?msg=api_key_renamed", status_code=303)


@router.post("/security/api-keys/{key_id}/delete")
def delete_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = (
        db.query(APIKey)
        .filter(APIKey.id == key_id, APIKey.user_id == user.id, APIKey.revoked_at.is_(None))
        .first()
    )
    if not row:
        return RedirectResponse("/settings/security?error=api_key_not_found", status_code=303)
    row.revoked_at = datetime.now(timezone.utc)
    row.active_name = None
    db.commit()
    return RedirectResponse("/settings/security?msg=api_key_deleted", status_code=303)


# =============================================================================
# 📞 5. API-Kontaktlink
# =============================================================================
@router.get("/contact-api", response_class=RedirectResponse)
def contact_api():
    return RedirectResponse("/contact?topic=api-access", status_code=303)
