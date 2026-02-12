# routes/auth.py
from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from passlib.hash import bcrypt
from datetime import timedelta, datetime, timezone
from database import get_db, SessionLocal
from models.user import User
from models.plan import Plan
from models.login_device import LoginDevice
from utils.two_factor import verify_totp
from utils.app_url import resolve_app_base_url
from auth_utils import make_reset_token, verify_reset_token

# 📧 Mail-Funktion importieren (für Passwort-Reset)
# type: ignore
from utils.email_service import send_reset_mail
import secrets                             # ✅ für Token-Erzeugung (sicherer Zufallswert)
# ─────────────────────────────────────────────
# 🔐 Authentifizierungs-Router
# ─────────────────────────────────────────────
router = APIRouter(prefix="/auth", tags=["Authentication"])
templates = Jinja2Templates(directory="templates")


def _detect_device_name(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if "iphone" in ua or "ipad" in ua:
        return "iPhone/iPad"
    if "android" in ua:
        return "Android"
    if "windows" in ua:
        return "Windows"
    if "macintosh" in ua or "mac os" in ua:
        return "Mac"
    if "linux" in ua:
        return "Linux"
    return "Unbekannt"


def _registration_plans(db: Session) -> list[Plan]:
    """Liefert Pläne in stabiler Reihenfolge für die Registrierungsseite."""
    plan_map = {
        str(plan.name or "").strip().lower(): plan
        for plan in db.query(Plan).all()
    }
    preferred_order = ["basic", "pro", "business"]
    ordered = [plan_map[key] for key in preferred_order if key in plan_map]
    return ordered


# ─────────────────────────────────────────────
# 🧾 Registrierung (GET)
# ─────────────────────────────────────────────
@router.get("/register", response_class=HTMLResponse)
def register_form(request: Request, db: Session = Depends(get_db)):
    """Zeigt das Registrierungsformular an."""
    return templates.TemplateResponse(
        "register.html",
        {
            "request": request,
            "plans": _registration_plans(db),
            "selected_plan": "basic",
        },
    )


# ─────────────────────────────────────────────
# 🧩 Registrierung (POST)
# ─────────────────────────────────────────────
@router.post("/register")
def register_user(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    selected_plan: str = Form("basic"),
    privacy_accepted: str = Form(None),
    db: Session = Depends(get_db)
):
    """Registriert neuen Benutzer und führt je nach Tarif in den passenden nächsten Schritt."""
    selected_plan_key = str(selected_plan or "basic").strip().lower()
    available_plans = {str(p.name or "").strip().lower(): p for p in _registration_plans(db)}

    if selected_plan_key not in available_plans:
        selected_plan_key = "basic"

    basic_plan = available_plans.get("basic")
    selected_plan_obj = available_plans.get(selected_plan_key)
    render_context = {
        "request": request,
        "plans": _registration_plans(db),
        "selected_plan": selected_plan_key,
        "prefill_username": username,
        "prefill_email": email,
    }

    # 🔒 Passwort bestätigen
    if password != confirm_password:
        return templates.TemplateResponse(
            "register.html",
            {**render_context, "error": "❌ Die Passwörter stimmen nicht überein."},
            status_code=400,
        )

    # 🔒 Datenschutz prüfen
    if not privacy_accepted:
        return templates.TemplateResponse(
            "register.html",
            {**render_context, "error": "❌ Bitte akzeptiere die Datenschutzbestimmungen."},
            status_code=400,
        )

    # 🔍 Prüfen, ob Benutzer existiert
    if db.query(User).filter(User.email == email).first():
        return templates.TemplateResponse(
            "register.html",
            {**render_context, "error": "❌ Diese E-Mail-Adresse ist bereits registriert."},
            status_code=400,
        )

    # 🔐 Passwort hashen
    hashed_pw = bcrypt.hash(password)

    # 💾 Benutzer speichern (Initialplan: Basic als sicherer Einstieg)
    new_user = User(
        username=username,
        email=email,
        password_hash=hashed_pw,
        plan_id=basic_plan.id if basic_plan else (selected_plan_obj.id if selected_plan_obj else None),
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # 🔐 Direkt einloggen, damit nach Registrierung sofort der nächste Schritt klappt
    request.session.clear()
    request.session["user_id"] = new_user.id
    request.session["user"] = {
        "id": new_user.id,
        "username": new_user.username,
        "email": new_user.email,
    }
    request.session["expiry"] = int(timedelta(minutes=30).total_seconds())

    print(f"[REGISTER] Neuer Benutzer registriert: {username} ({email})")

    # 🧭 Onboarding nach gewähltem Tarif
    if selected_plan_key in {"pro", "business"}:
        return RedirectResponse(f"/billing/upgrade/{selected_plan_key}", status_code=303)

    return RedirectResponse("/dashboard/", status_code=303)


# ─────────────────────────────────────────────
# 🔐 Login (GET)
# ─────────────────────────────────────────────
@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    """Zeigt das Login-Formular."""
    return templates.TemplateResponse("login.html", {"request": request})

# ─────────────────────────────────────────────
# 🔑 Login (POST)
# ─────────────────────────────────────────────
@router.post("/login")
def login_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    otp_code: str = Form(""),
    remember_me: str = Form(None),
    db: Session = Depends(get_db)
):
    """Prüft Login-Daten und erstellt eine Session."""
    user = db.query(User).filter(User.email == email).first()

    # 🔒 Passwortprüfung
    if not user or not bcrypt.verify(password, str(user.password_hash)):
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "❌ Ungültige E-Mail oder Passwort.",
                "prefill_email": email,
            },
            status_code=400,
        )

    # 🔐 2FA prüfen (wenn aktiviert)
    if getattr(user, "two_factor_enabled", False):
        if not otp_code:
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": "❌ Bitte 2FA-Code eingeben.",
                    "prefill_email": email,
                    "require_2fa": True,
                },
                status_code=400,
            )
        if not user.two_factor_secret or not verify_totp(user.two_factor_secret, otp_code):
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": "❌ Ungültiger 2FA-Code.",
                    "prefill_email": email,
                    "require_2fa": True,
                },
                status_code=400,
            )

    # 🧹 Alte Session löschen (Schutz vor Session-Fixation)
    request.session.clear()

    # 💾 Benutzer-ID und -Infos speichern
    request.session["user_id"] = user.id
    request.session["user"] = {
        "id": user.id,
        "username": user.username,
        "email": user.email
    }

    # ⏱️ Sessiondauer (Remember-Me)
    if remember_me:
        request.session["expiry"] = int(timedelta(days=7).total_seconds())
    else:
        request.session["expiry"] = int(timedelta(minutes=30).total_seconds())

    # 💻 Login-Gerät speichern/aktivieren
    session_token = secrets.token_urlsafe(24)
    request.session["session_token"] = session_token
    user_agent = request.headers.get("user-agent", "")
    ip_addr = request.client.host if request.client else None
    try:
        device = LoginDevice(
            user_id=user.id,
            session_token=session_token,
            device_name=_detect_device_name(user_agent),
            ip_address=ip_addr,
            user_agent=user_agent[:255] if user_agent else None,
            active=True,
            last_seen_at=datetime.now(timezone.utc),
        )
        db.add(device)
        user.last_login = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"⚠️ Login-Gerät konnte nicht gespeichert werden: {exc}")

    print(f"[LOGIN] Benutzer {user.username} (ID {user.id}) erfolgreich eingeloggt.")
    return RedirectResponse("/dashboard/", status_code=303)


# ─────────────────────────────────────────────
# 🚪 Logout
# ─────────────────────────────────────────────
from fastapi.responses import RedirectResponse

@router.get("/logout")
def logout_user(request: Request):
    """Benutzer abmelden und zur Startseite weiterleiten."""
    user_id = request.session.get("user_id")
    if user_id:
        print(f"[LOGOUT] Benutzer-ID {user_id} wurde abgemeldet.")
    else:
        print("[LOGOUT] Kein Benutzer aktiv – anonyme Abmeldung.")

    # 🧹 Aktuelles Login-Gerät deaktivieren
    session_token = request.session.get("session_token")
    if user_id and session_token:
        db = SessionLocal()
        try:
            dev = (
                db.query(LoginDevice)
                .filter(LoginDevice.user_id == user_id, LoginDevice.session_token == session_token)
                .first()
            )
            if dev:
                dev.active = False
                dev.last_seen_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    # 🧹 Sitzung löschen
    request.session.clear()

    # 🔁 Sicheren Redirect auch bei HTMX-Anfragen
    response = RedirectResponse(url="/", status_code=303)
    response.headers["HX-Redirect"] = "/"  # wichtig für HTMX
    return response


# ─────────────────────────────────────────────
# 🔐 Passwort ändern
# ─────────────────────────────────────────────
@router.post("/change-password")
async def change_password(
    request: Request,
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Ermöglicht eingeloggten Benutzern, ihr Passwort zu ändern."""
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/auth/login", status_code=303)

    if new_password != confirm_password:
        return RedirectResponse("/profile?error=nomatch", status_code=303)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    user.password_hash = bcrypt.hash(new_password)
    db.commit()
    print(f"[PASS] Benutzer-ID {user_id} Passwort geändert.")
    return RedirectResponse("/profile?msg=pass_updated", status_code=303)


# ─────────────────────────────────────────────
# 📧 Passwort vergessen (ECHT)
# ─────────────────────────────────────────────


@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request):
    """Zeigt Formular zum Zurücksetzen des Passworts an."""
    return templates.TemplateResponse("forgot-password.html", {"request": request})


@router.post("/forgot-password")
def forgot_password(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db)
):
    """Sendet echten Passwort-Reset-Link per E-Mail."""
    user = db.query(User).filter(User.email == email).first()

    if not user:
        # ❌ Kein Benutzer mit dieser E-Mail gefunden
        return templates.TemplateResponse(
            "forgot-password.html",
            {"request": request, "error": "❌ Diese E-Mail ist nicht registriert."},
            status_code=400,
        )

    # 🔑 Reset-Link erzeugen (lokal: localhost, server: APP_DOMAIN)
    token = make_reset_token(str(user.id))
    app_base = resolve_app_base_url(request)
    reset_link = f"{app_base}/auth/reset-password?token={token}"

    try:
        # 📧 Mail senden (funktioniert über mail_service.py)
        send_reset_mail(user.username, user.email, reset_link)
        print(f"[RESET] Passwort-Reset-Link gesendet an {email}")
        return RedirectResponse("/auth/login?msg=reset_sent", status_code=303)

    except Exception as e:
        print(f"❌ Fehler beim Senden der Mail: {e}")
        return templates.TemplateResponse(
            "forgot-password.html",
            {"request": request, "error": "❌ Fehler beim Senden der E-Mail."},
            status_code=500,
        )


@router.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(request: Request, token: str = ""):
    """Zeigt die Seite zum Zurücksetzen des Passworts an."""
    is_valid, _ = verify_reset_token(token)
    if not is_valid:
        return templates.TemplateResponse(
            "reset-password.html",
            {
                "request": request,
                "token": token,
                "error": "❌ Ungültiger oder abgelaufener Reset-Link.",
            },
            status_code=400,
        )

    return templates.TemplateResponse(
        "reset-password.html",
        {"request": request, "token": token},
    )


@router.post("/reset-password")
def reset_password_submit(
    request: Request,
    token: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    """Setzt das Passwort mit gültigem Reset-Token zurück."""
    if new_password != confirm_password:
        return templates.TemplateResponse(
            "reset-password.html",
            {
                "request": request,
                "token": token,
                "error": "❌ Die Passwörter stimmen nicht überein.",
            },
            status_code=400,
        )

    is_valid, user_id = verify_reset_token(token)
    if not is_valid or not user_id:
        return templates.TemplateResponse(
            "reset-password.html",
            {
                "request": request,
                "token": token,
                "error": "❌ Ungültiger oder abgelaufener Reset-Link.",
            },
            status_code=400,
        )

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        return templates.TemplateResponse(
            "reset-password.html",
            {
                "request": request,
                "token": token,
                "error": "❌ Benutzer nicht gefunden.",
            },
            status_code=404,
        )

    user.password_hash = bcrypt.hash(new_password)
    db.commit()
    return RedirectResponse("/auth/login?msg=pass_reset_ok", status_code=303)
# ─────────────────────────────────────────────
# 🧩 Hilfsfunktion: aktuellen Benutzer abrufen
# ─────────────────────────────────────────────
def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Gibt den aktuell eingeloggten Benutzer zurück."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht eingeloggt.")

    session_token = request.session.get("session_token")
    if not session_token:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sitzung ungültig.")

    device = (
        db.query(LoginDevice)
        .filter(
            LoginDevice.user_id == user_id,
            LoginDevice.session_token == session_token,
            LoginDevice.active == True,
        )
        .first()
    )
    if not device:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sitzung abgelaufen.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Benutzer nicht gefunden.")
    return user
