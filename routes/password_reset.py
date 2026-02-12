# routes/password_reset.py
from __future__ import annotations
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import logging
from fastapi import APIRouter, Request, Form, HTTPException, Depends, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from dotenv import load_dotenv

# 📦 Eigene Module
from utils.email_service import send_reset_mail
from database import get_db
from models.user import User
from auth_utils import make_reset_token, verify_reset_token, password_hash
from utils.app_url import resolve_app_base_url

# 🌍 Umgebung laden
load_dotenv()

# ⚙️ Setup
router = APIRouter(prefix="/password", tags=["Password"])
templates = Jinja2Templates(directory="templates")
# --------------------------------------------------------------------------- #
# 🧭 1️⃣ Formular: Passwort vergessen
# --------------------------------------------------------------------------- #

@router.get("/forgot", response_class=HTMLResponse)
def forgot_form(request: Request) -> HTMLResponse:
    """Zeigt das Formular zum Anfordern eines Passwort-Resets."""
    return templates.TemplateResponse("forgot-password.html", {"request": request})


@router.post("/forgot", response_class=HTMLResponse)
async def forgot_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Bearbeitet das Formular für Passwort-Reset."""
    user: User | None = db.query(User).filter(User.email == email).first()

    if not user:
        return templates.TemplateResponse(
            "password_forgot.html",
            {"request": request, "error": "❌ E-Mail-Adresse wurde nicht gefunden."},
        )

    # 🔐 Reset-Link erzeugen
    token = make_reset_token(str(user.id))
    app_base = resolve_app_base_url(request)
    reset_link = f"{app_base}/password/reset?token={token}"

    # 📧 E-Mail asynchron im Hintergrund senden
    logging.info(f"🧩 Passwort-Reset-Link wird an {email} gesendet ...")

    background_tasks.add_task(
        send_reset_mail,
        name=user.username or "Benutzer",
        email=email,
        reset_link=reset_link
    )

    # ✅ Rückmeldung an Benutzer
    return templates.TemplateResponse(
        "password_forgot.html",
        {"request": request, "msg": "✅ E-Mail mit Link zum Zurücksetzen wurde gesendet."},
    )

# --------------------------------------------------------------------------- #
# 🧾 2️⃣ Formular: Neues Passwort setzen
# --------------------------------------------------------------------------- #
@router.get("/reset", response_class=HTMLResponse)
def reset_form(request: Request, token: str) -> HTMLResponse:
    """Zeigt das Formular zum Zurücksetzen des Passworts."""
    valid, uid = verify_reset_token(token)
    if not valid:
        raise HTTPException(status_code=400, detail="Ungültiger oder abgelaufener Token.")
    return templates.TemplateResponse(
        "password_reset.html",
        {"request": request, "token": token, "uid": uid}
    )


@router.post("/reset", response_class=HTMLResponse)
def reset_submit(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Verarbeitet das Zurücksetzen des Passworts."""
    valid, uid = verify_reset_token(token)
    if not valid:
        raise HTTPException(status_code=400, detail="Ungültiger oder abgelaufener Token.")

    user: User | None = db.query(User).filter(User.id == uid).first()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden.")

    # 🔑 Neues Passwort speichern
    hashed_pw = password_hash(password)
    user.password_hash = hashed_pw
    db.commit()

    logging.info(f"✅ Passwort erfolgreich geändert für Benutzer {user.email}.")
    return RedirectResponse("/auth/login?msg=Passwort erfolgreich geändert", status_code=303)
