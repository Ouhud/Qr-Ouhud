# =============================================================================
# ✏️ routes/qr/edit_qr.py
# -----------------------------------------------------------------------------
# Zentrale Bearbeitungsrouten für ALLE dynamischen QR-Typen
# 🔐 Alle Inhalte werden AES-256-GCM verschlüsselt für Privatschutz
# -----------------------------------------------------------------------------
# Autor: Mohamad Hamza Mehmalat
# Projekt: Ouhud QR
# =============================================================================

import os
import json
import shutil
import html
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Optional, Dict, Any
from models.user import User
from fastapi import (
    APIRouter, Request, Depends, Form, UploadFile, File, HTTPException
)
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from routes.auth import get_current_user
from routes.qr.logo_utils import save_qr_logo
from routes.utils import normalize_url
from models.qrcode import QRCode
from utils.access_control import can_edit_qr
from utils.qr_design import resolve_design
from utils.qr_generator import generate_qr_png

router = APIRouter(prefix="/qr", tags=["QR Edit"])
templates = Jinja2Templates(directory="templates")


def get_qr_data(qr: QRCode) -> Dict[str, Any]:
    """Holt die entschlüsselten QR-Daten aus dem verschlüsselten Inhalt."""
    data = qr.get_data()  # 🔐 Automatische Entschlüsselung
    if data:
        return data
    # Fallback für alte unverschlüsselte Daten
    if hasattr(qr, "data") and qr.data and isinstance(qr.data, dict):
        return qr.data
    if qr.content:
        try:
            return json.loads(qr.content) if isinstance(qr.content, str) else qr.content
        except (json.JSONDecodeError, TypeError):
            return {"content": qr.content}
    return {}


def get_template_for_type(qr_type: str) -> str:
    """Gibt das passende Template für den QR-Typ zurück."""
    templates_map = {
        "vcard": "vcard.html",
        "pdf": "qr_pdf_form.html",
    }
    return templates_map.get(qr_type.lower(), "qr_edit.html")


# -------------------------------------------------------------------------
# 🧭 GET: QR-Code bearbeiten (ZENTRAL für ALLE Typen)
# -------------------------------------------------------------------------
@router.get("/edit/{slug}", response_class=HTMLResponse)
def edit_qr_page(
    request: Request,
    slug: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    """
    Zeigt die Bearbeitungsseite für ALLE QR-Typen an.
    Routet automatisch zum richtigen Template basierend auf dem QR-Typ.
    """
    qr: Optional[QRCode] = db.query(QRCode).filter(QRCode.slug == slug).first()
    if not qr:
        return HTMLResponse("<h2>❌ QR-Code nicht gefunden</h2>", status_code=404)
    if not can_edit_qr(db, user.id, qr):
        raise HTTPException(status_code=403, detail="Keine Berechtigung zum Bearbeiten")

    qr_type = str(qr.type).lower()
    qr_data = get_qr_data(qr)
    
    # Wähle das passende Template
    template_name = get_template_for_type(qr_type)
    
    # Mode für Templates die es unterstützen
    mode = "edit"
    
    # Für vCard: übergebe `vcard` statt `data`
    context = {"request": request, "qr": qr, "data": qr_data, "mode": mode}
    if qr_type == "vcard":
        context["vcard"] = qr_data
    
    return templates.TemplateResponse(
        template_name,
        context
    )


# -------------------------------------------------------------------------
# 🧾 POST: QR-Code aktualisieren (ZENTRAL für ALLE Typen)
# -------------------------------------------------------------------------
@router.post("/update/{slug}")
async def update_qr(
    request: Request,
    slug: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Aktualisiert den Inhalt eines QR-Codes.
    Unterstützt alle QR-Typen: URL, vCard, WiFi, Social, etc.
    🔐 Alle Daten werden verschlüsselt gespeichert.
    """
    qr: Optional[QRCode] = db.query(QRCode).filter(QRCode.slug == slug).first()
    if not qr:
        return HTMLResponse("<h2>❌ QR-Code nicht gefunden</h2>", status_code=404)
    if not can_edit_qr(db, user.id, qr):
        raise HTTPException(status_code=403, detail="Keine Berechtigung zum Bearbeiten")

    qr_type = str(qr.type).lower()
    form = await request.form()
    kwargs = dict(form)
    existing_data = qr.get_data() or {}
    existing_design = existing_data.get("design") if isinstance(existing_data.get("design"), dict) else {}

    logo_upload = kwargs.get("logo")
    if logo_upload is not None and hasattr(logo_upload, "filename") and getattr(logo_upload, "filename", ""):
        logo_fs_path, logo_public_path = save_qr_logo(logo_upload, qr.slug, f"{qr_type}_logo")
        if logo_public_path:
            qr.logo_path = logo_public_path
            existing_data["logo_path"] = logo_public_path

    design = resolve_design(
        style=str(kwargs.get("style") or qr.style or existing_design.get("style") or "classic"),
        fg_color=kwargs.get("fg_color") or kwargs.get("color_fg") or qr.color_fg or existing_design.get("fg"),
        bg_color=kwargs.get("bg_color") or kwargs.get("color_bg") or qr.color_bg or existing_design.get("bg"),
        module_style=kwargs.get("module_style") or existing_design.get("module_style"),
        eye_style=kwargs.get("eye_style") or existing_design.get("eye_style"),
        qr_size=kwargs.get("qr_size") or qr.qr_size or existing_design.get("qr_size"),
        output_preset=kwargs.get("output_preset") or existing_design.get("output_preset"),
        export_format=kwargs.get("export_format") or existing_design.get("export_format"),
        frame_style=kwargs.get("frame_style") or qr.frame_style or existing_design.get("frame_style"),
        logo_scale=kwargs.get("logo_scale") or existing_design.get("logo_scale"),
        logo_bg_mode=kwargs.get("logo_bg_mode") or existing_design.get("logo_bg_mode"),
        safe_mode=kwargs.get("safe_mode") or existing_design.get("safe_mode"),
    )
    
    # Update nach Typ - alle Daten werden verschlüsselt gespeichert
    if qr_type == "url":
        url = kwargs.get("url") or kwargs.get("field1")
        if url:
            current_data = qr.get_data() or {}
            utm = {
                "source": (kwargs.get("utm_source") or "").strip(),
                "medium": (kwargs.get("utm_medium") or "").strip(),
                "campaign": (kwargs.get("utm_campaign") or "").strip(),
                "term": (kwargs.get("utm_term") or "").strip(),
                "content": (kwargs.get("utm_content") or "").strip(),
            }
            if not any(utm.values()):
                utm = current_data.get("utm") or {}

            ab_targets = current_data.get("ab_targets") or []
            raw_ab = (kwargs.get("ab_targets_json") or "").strip()
            if raw_ab:
                try:
                    parsed_ab = json.loads(raw_ab)
                    if isinstance(parsed_ab, list):
                        ab_targets = parsed_ab
                except json.JSONDecodeError:
                    pass

            rules = current_data.get("rules") or []
            raw_rules = (kwargs.get("rules_json") or "").strip()
            if raw_rules:
                try:
                    parsed_rules = json.loads(raw_rules)
                    if isinstance(parsed_rules, list):
                        rules = parsed_rules
                except json.JSONDecodeError:
                    pass

            qr.set_data(
                {
                    "url": url,
                    "title": kwargs.get("title") or kwargs.get("name", ""),
                    "utm": utm,
                    "ab_targets": ab_targets,
                    "rules": rules,
                }
            )
            
    elif qr_type == "vcard":
        current_data = qr.get_data() or {}
        # Sammle vCard-Felder
        vcard_data = {
            "first_name": kwargs.get("first_name") or kwargs.get("field1", ""),
            "last_name": kwargs.get("last_name") or kwargs.get("field2", ""),
            "org": kwargs.get("org") or kwargs.get("field5", ""),
            "title": kwargs.get("title") or "",
            "email": kwargs.get("email") or kwargs.get("field4", ""),
            "phone": kwargs.get("phone") or kwargs.get("field3", ""),
            "address": kwargs.get("address", ""),
            "city": kwargs.get("city", ""),
            "zip_code": kwargs.get("zip_code", ""),
            "country": kwargs.get("country", ""),
            "website": kwargs.get("website", ""),
            "apple_wallet_url": normalize_url(kwargs.get("apple_wallet_url", "")) if kwargs.get("apple_wallet_url") else current_data.get("apple_wallet_url", ""),
            "google_wallet_url": normalize_url(kwargs.get("google_wallet_url", "")) if kwargs.get("google_wallet_url") else current_data.get("google_wallet_url", ""),
        }
        # Build vCard text
        first_name = vcard_data["first_name"]
        last_name = vcard_data["last_name"]
        vcard_text = (
            "BEGIN:VCARD\n"
            "VERSION:3.0\n"
            f"N:{last_name};{first_name};;;\n"
            f"FN:{first_name} {last_name}\n"
        )
        if vcard_data.get("org"):
            vcard_text += f"ORG:{vcard_data['org']}\n"
        if vcard_data.get("phone"):
            vcard_text += f"TEL;TYPE=cell:{vcard_data['phone']}\n"
        if vcard_data.get("email"):
            vcard_text += f"EMAIL;TYPE=internet:{vcard_data['email']}\n"
        if vcard_data.get("website"):
            vcard_text += f"URL:{vcard_data['website']}\n"
        vcard_text += "END:VCARD\n"
        vcard_data["vcard"] = vcard_text
        vcard_data["vcard_text"] = vcard_text
        qr.set_data(vcard_data)  # 🔐 Verschlüsselt speichern
        qr.title = f"{first_name} {last_name}"
        
    elif qr_type == "wifi":
        ssid = kwargs.get("ssid") or kwargs.get("field1", "")
        password = kwargs.get("password") or kwargs.get("field2", "")
        encryption = kwargs.get("encryption", "WPA")
        hidden = str(kwargs.get("hidden", "")).lower() in {"true", "1", "on", "yes"}
        qr.set_data({
            "ssid": ssid,
            "password": password,
            "encryption": encryption,
            "hidden": hidden,
        })  # 🔐 Verschlüsselt speichern
        qr.title = f"WLAN: {ssid}"
        
    elif qr_type == "social":
        current_data = qr.get_data() or {}
        name = kwargs.get("name", current_data.get("name", ""))
        title = kwargs.get("title", current_data.get("title", ""))
        links = {
            "Website": normalize_url(kwargs.get("website", "")) if kwargs.get("website") else current_data.get("website", ""),
            "Facebook": normalize_url(kwargs.get("facebook", "")) if kwargs.get("facebook") else current_data.get("facebook", ""),
            "Instagram": normalize_url(kwargs.get("instagram", "")) if kwargs.get("instagram") else current_data.get("instagram", ""),
            "WhatsApp": normalize_url(kwargs.get("whatsapp", "")) if kwargs.get("whatsapp") else current_data.get("whatsapp", ""),
            "LinkedIn": normalize_url(kwargs.get("linkedin", "")) if kwargs.get("linkedin") else current_data.get("linkedin", ""),
            "Xing": normalize_url(kwargs.get("xing", "")) if kwargs.get("xing") else current_data.get("xing", ""),
            "GitHub": normalize_url(kwargs.get("github", "")) if kwargs.get("github") else current_data.get("github", ""),
            "TikTok": normalize_url(kwargs.get("tiktok", "")) if kwargs.get("tiktok") else current_data.get("tiktok", ""),
            "X / Twitter": normalize_url(kwargs.get("twitter", "")) if kwargs.get("twitter") else current_data.get("twitter", ""),
        }

        fallback_target = current_data.get("url", "")
        for value in links.values():
            if value:
                fallback_target = value
                break

        display_name = title or name or qr.title or "Social Profil"
        social_links_html = "".join(
            f'<a class="social-link" href="{html.escape(link)}" target="_blank" rel="noopener">{html.escape(label)}</a>'
            for label, link in links.items()
            if link
        )
        avatar_html = (
            f'<img class="social-avatar" src="{html.escape(qr.logo_path)}" alt="Profilbild">'
            if qr.logo_path
            else ""
        )
        public_html = f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(display_name)}</title>
  <style>
    body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#f3f6ff;color:#0f172a}}
    .wrap{{max-width:620px;margin:0 auto;padding:22px}}
    .card{{background:#fff;border:1px solid #dbe7ff;border-radius:18px;box-shadow:0 10px 26px rgba(13,42,120,.12);padding:22px}}
    .social-avatar{{width:92px;height:92px;border-radius:50%;object-fit:cover;border:3px solid #dbeafe;display:block;margin:0 auto 12px}}
    h1{{margin:0 0 14px;text-align:center;color:#0d2a78;font-size:1.35rem}}
    .social-grid{{display:grid;gap:10px}}
    .social-link{{display:block;text-decoration:none;background:#0d2a78;color:#fff;border-radius:12px;padding:12px 14px;font-weight:700;text-align:center}}
    .social-link:hover{{background:#1d4ed8}}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      {avatar_html}
      <h1>{html.escape(display_name)}</h1>
      <div class="social-grid">{social_links_html}</div>
    </div>
  </div>
</body>
</html>"""

        qr.set_data(
            {
                "platform": "social",
                "url": fallback_target or "/",
                "name": name,
                "website": links["Website"],
                "facebook": links["Facebook"],
                "instagram": links["Instagram"],
                "whatsapp": links["WhatsApp"],
                "linkedin": links["LinkedIn"],
                "xing": links["Xing"],
                "github": links["GitHub"],
                "tiktok": links["TikTok"],
                "twitter": links["X / Twitter"],
                "public_html": public_html,
                "title": title,
            }
        )
        qr.title = display_name
        
    elif qr_type == "email":
        to = kwargs.get("email") or kwargs.get("to") or kwargs.get("email_to") or kwargs.get("field1", "")
        subject = kwargs.get("subject") or kwargs.get("field2", "")
        body = kwargs.get("body") or kwargs.get("field3", "")
        mailto = f"mailto:{to}"
        query_parts = []
        if subject:
            query_parts.append(f"subject={subject}")
        if body:
            query_parts.append(f"body={body}")
        if query_parts:
            mailto += "?" + "&".join(query_parts)
        qr.set_data({"mailto": mailto, "to": to, "subject": subject, "body": body})
        qr.title = kwargs.get("title") or kwargs.get("name") or f"Email: {to}"
        
    elif qr_type == "sms":
        phone = kwargs.get("phone") or kwargs.get("field1", "")
        message = kwargs.get("message") or kwargs.get("field2", "")
        sms = f"sms:{phone}"
        if message:
            sms += f"?body={message}"
        qr.set_data({"sms": sms, "phone": phone, "message": message})
        qr.title = kwargs.get("title") or kwargs.get("name") or f"SMS: {phone}"
        
    elif qr_type == "tel":
        phone = kwargs.get("phone") or kwargs.get("field1", "")
        qr.set_data({"tel": f"tel:{phone}", "phone": phone})  # 🔐 Verschlüsselt speichern
        qr.title = kwargs.get("title") or kwargs.get("name") or f"Tel: {phone}"
        
    elif qr_type == "event":
        summary = kwargs.get("summary") or kwargs.get("field1", "")
        dtstart = kwargs.get("dtstart") or kwargs.get("field2", "")
        dtend = kwargs.get("dtend") or kwargs.get("field3", "")
        location = kwargs.get("location") or kwargs.get("field4", "")
        description = kwargs.get("description") or kwargs.get("field5", "")
        ics = (
            "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Ouhud QR//EN\nBEGIN:VEVENT\n"
            f"SUMMARY:{summary}\nDTSTART:{dtstart}\n"
            f"DTEND:{dtend}\nLOCATION:{location}\nDESCRIPTION:{description}\n"
            "END:VEVENT\nEND:VCALENDAR\n"
        )
        qr.set_data({"summary": summary, "dtstart": dtstart, "dtend": dtend, 
                   "location": location, "description": description, "ics": ics})  # 🔐 Verschlüsselt speichern
        
    elif qr_type == "geo":
        lat = kwargs.get("lat") or kwargs.get("field1", "")
        lon = kwargs.get("lon") or kwargs.get("field2", "")
        qr.set_data({"lat": lat, "lon": lon})  # 🔐 Verschlüsselt speichern
        
    elif qr_type == "pdf":
        pdf_path = kwargs.get("pdf_path") or kwargs.get("field1", "")
        qr.set_data({"pdf_path": pdf_path})  # 🔐 Verschlüsselt speichern
        
    elif qr_type == "multilink":
        public_html = kwargs.get("public_html") or kwargs.get("field1", "")
        qr.set_data({"public_html": public_html})  # 🔐 Verschlüsselt speichern
        
    elif qr_type == "payment":
        payment_url = kwargs.get("payment_url") or kwargs.get("url") or kwargs.get("field1", "")
        qr.set_data({"payment_url": payment_url})  # 🔐 Verschlüsselt speichern
        
    elif qr_type == "product":
        product_url = kwargs.get("product_url") or kwargs.get("url") or kwargs.get("field1", "")
        name = kwargs.get("name") or kwargs.get("field2", "")
        price = kwargs.get("price") or kwargs.get("field3", "")
        qr.set_data({"product_url": product_url, "name": name, "price": price})  # 🔐 Verschlüsselt speichern

    elif qr_type == "wallet":
        current_data = qr.get_data() or {}
        pass_url = kwargs.get("pass_url") or kwargs.get("url") or kwargs.get("field1", "")
        apple_pass_url = kwargs.get("apple_pass_url", "")
        google_pass_url = kwargs.get("google_pass_url", "")
        wallet_type = kwargs.get("wallet_type", "loyalty")
        qr.set_data(
            {
                "pass_url": normalize_url(pass_url) if pass_url else current_data.get("pass_url", ""),
                "apple_pass_url": normalize_url(apple_pass_url) if apple_pass_url else current_data.get("apple_pass_url", ""),
                "google_pass_url": normalize_url(google_pass_url) if google_pass_url else current_data.get("google_pass_url", ""),
                "wallet_type": wallet_type,
            }
        )

    elif qr_type == "gs1":
        gs1_link = kwargs.get("gs1_link") or kwargs.get("url") or kwargs.get("field1", "")
        qr.set_data({"gs1_link": gs1_link})

    elif qr_type == "app_deeplink":
        qr.set_data(
            {
                "deep_link": kwargs.get("deep_link", ""),
                "ios_store_url": kwargs.get("ios_store_url", ""),
                "android_store_url": kwargs.get("android_store_url", ""),
                "web_fallback_url": kwargs.get("web_fallback_url", ""),
            }
        )

    elif qr_type == "review":
        qr.set_data({"review_url": kwargs.get("review_url") or kwargs.get("url") or kwargs.get("field1", "")})

    elif qr_type == "booking":
        qr.set_data({"booking_url": kwargs.get("booking_url") or kwargs.get("url") or kwargs.get("field1", "")})

    elif qr_type == "lead":
        qr.set_data(
            {
                "headline": kwargs.get("headline", ""),
                "description": kwargs.get("description", ""),
                "success_message": kwargs.get("success_message", ""),
            }
        )

    elif qr_type == "feedback":
        qr.set_data(
            {
                "question": kwargs.get("question", ""),
                "low_label": kwargs.get("low_label", ""),
                "high_label": kwargs.get("high_label", ""),
            }
        )

    elif qr_type == "coupon":
        qr.set_data(
            {
                "code": kwargs.get("code", ""),
                "offer": kwargs.get("offer", ""),
                "expires_at": kwargs.get("expires_at", ""),
                "max_redemptions": kwargs.get("max_redemptions", "0"),
            }
        )
        
    # Update title if provided
    if kwargs.get("title"):
        qr.title = kwargs.get("title")
    elif kwargs.get("name"):
        qr.title = kwargs.get("name")

    # 🎨 Neues Design vollständig übernehmen
    qr.style = design.style
    qr.color_fg = design.fg
    qr.color_bg = design.bg
    qr.qr_size = design.qr_size
    qr.frame_style = design.frame_style

    merged_data = qr.get_data() or {}
    merged_data["design"] = {
        "style": design.style,
        "fg": design.fg,
        "bg": design.bg,
        "module_style": design.module_style,
        "eye_style": design.eye_style,
        "frame_style": design.frame_style,
        "output_preset": design.output_preset,
        "export_format": design.export_format,
        "logo_scale": design.logo_scale,
        "logo_bg_mode": design.logo_bg_mode,
        "qr_size": design.qr_size,
        "quiet_zone": design.quiet_zone,
        "dpi": design.dpi,
        "contrast_ratio": design.contrast_ratio,
        "warnings": list(design.warnings),
        "safe_mode": design.safe_mode,
        "safe_mode_applied": design.safe_mode_applied,
    }
    if qr.logo_path:
        merged_data["logo_path"] = qr.logo_path
    qr.set_data(merged_data)

    # 🔁 QR-Bild + SVG/PDF neu rendern
    if qr.image_path:
        payload = qr.dynamic_url or f"/d/{qr.slug}"
        logo_fs_path = None
        if qr.logo_path:
            candidate = qr.logo_path.lstrip("/")
            if os.path.exists(candidate):
                logo_fs_path = candidate

        regen = generate_qr_png(
            payload=payload,
            size=design.qr_size,
            fg=design.fg,
            bg=design.bg,
            logo_path=logo_fs_path,
            module_style=design.module_style,
            eye_style=design.eye_style,
            frame_style=design.frame_style,
            logo_scale=design.logo_scale,
            logo_bg_mode=design.logo_bg_mode,
            quiet_zone=design.quiet_zone,
            dpi=design.dpi,
        )
        regen_bytes = regen["bytes"] if isinstance(regen, dict) else b""
        if regen_bytes:
            image_path = Path(str(qr.image_path))
            image_path.parent.mkdir(parents=True, exist_ok=True)
            image_path.write_bytes(regen_bytes)

            svg_bytes = regen.get("svg_bytes", b"") if isinstance(regen, dict) else b""
            if svg_bytes:
                svg_path = image_path.with_suffix(".svg")
                svg_path.write_bytes(svg_bytes)
                qr.svg_path = str(svg_path)

            pdf_bytes = regen.get("pdf_bytes", b"") if isinstance(regen, dict) else b""
            if pdf_bytes:
                pdf_path = image_path.with_suffix(".pdf")
                pdf_path.write_bytes(pdf_bytes)
        
    db.commit()
    print(f"[UPDATE] QR '{qr.slug}' ({qr.type}) erfolgreich aktualisiert.")
    return RedirectResponse(f"/qr/edit/{slug}?msg=ok", status_code=303)


# -------------------------------------------------------------------------
# 📦 GET: QR-Export (PNG / SVG / PDF)
# -------------------------------------------------------------------------
@router.get("/export/{slug}", response_class=Response)
def export_qr(
    slug: str,
    format: str = "png",
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    qr: Optional[QRCode] = db.query(QRCode).filter(QRCode.slug == slug).first()
    if qr is None:
        raise HTTPException(status_code=404, detail="QR-Code nicht gefunden")
    if not can_edit_qr(db, user.id, qr):
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    data = qr.get_data() or {}
    design = data.get("design") if isinstance(data.get("design"), dict) else {}
    payload = qr.dynamic_url or f"/d/{qr.slug}"
    fmt = str(format or "png").strip().lower()
    if fmt not in {"png", "svg", "pdf", "zip"}:
        fmt = "png"

    logo_fs_path = None
    if qr.logo_path:
        candidate = qr.logo_path.lstrip("/")
        if os.path.exists(candidate):
            logo_fs_path = candidate

    regen = generate_qr_png(
        payload=payload,
        size=int(qr.qr_size or design.get("qr_size") or 600),
        fg=str(qr.color_fg or design.get("fg") or "#0D2A78"),
        bg=str(qr.color_bg or design.get("bg") or "#FFFFFF"),
        logo_path=logo_fs_path,
        module_style=str(design.get("module_style") or "square"),
        eye_style=str(design.get("eye_style") or "square"),
        frame_style=str(qr.frame_style or design.get("frame_style") or "none"),
        logo_scale=int(design.get("logo_scale") or 20),
        logo_bg_mode=str(design.get("logo_bg_mode") or "auto-white"),
        quiet_zone=int(design.get("quiet_zone") or 4),
        dpi=int(design.get("dpi") or 300),
    )

    if fmt == "zip":
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"qr_{slug}.png", regen.get("bytes", b""))
            zf.writestr(f"qr_{slug}.svg", regen.get("svg_bytes", b""))
            zf.writestr(f"qr_{slug}.pdf", regen.get("pdf_bytes", b""))
        headers = {"Content-Disposition": f'attachment; filename=\"qr_{slug}.zip\"'}
        return Response(content=zip_buffer.getvalue(), media_type="application/zip", headers=headers)

    headers = {"Content-Disposition": f'attachment; filename=\"qr_{slug}.{fmt}\"'}
    if fmt == "svg":
        return Response(content=regen.get("svg_bytes", b""), media_type="image/svg+xml", headers=headers)
    if fmt == "pdf":
        return Response(content=regen.get("pdf_bytes", b""), media_type="application/pdf", headers=headers)
    return Response(content=regen.get("bytes", b""), media_type="image/png", headers=headers)


# -------------------------------------------------------------------------
# 🖼️ GET: QR-Image separat bearbeiten (Logo, Farbe etc.)
# -------------------------------------------------------------------------
@router.get("/image/{slug}/edit-image", response_class=HTMLResponse)
def edit_image_page(
    request: Request,
    slug: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Zeigt eine spezielle Seite zum Bearbeiten von Bild-basierten QR-Codes."""
    
    # 🔹 QR-Code aus der DB laden
    qr: Optional[QRCode] = db.query(QRCode).filter(QRCode.slug == slug).first()

    # 🔹 Prüfen, ob QR-Code existiert
    if qr is None:
        raise HTTPException(status_code=404, detail="QR-Code nicht gefunden")
    if not can_edit_qr(db, user.id, qr):
        raise HTTPException(status_code=403, detail="Keine Berechtigung zum Bearbeiten")

    # 🔹 Typ prüfen (nur image-QRs erlaubt)
    if str(qr.type) != "image":
        raise HTTPException(status_code=400, detail="Dieser QR ist kein Bild-Typ")

    # 🔹 QR-Inhalt dekodieren (z. B. {"logo": "...", "fg_color": "#000", "bg_color": "#fff"})
    data = {}
    if qr.content:
        try:
            data = json.loads(qr.content)
        except Exception:
            data = {}

    # 🔹 Template rendern
    return templates.TemplateResponse(
        "qr_edit_image.html",
        {
            "request": request,
            "qr": qr,
            "data": data,
        }
    )
    
    
# -------------------------------------------------------------------------
# 🧾 POST: Bild-QR aktualisieren (Logo, Farben)
# -------------------------------------------------------------------------
@router.post("/image/{slug}/update-image")
async def update_qr_image(
    slug: str,
    logo: Optional[UploadFile] = File(None),
    fg_color: Optional[str] = Form("#000000"),
    bg_color: Optional[str] = Form("#ffffff"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Aktualisiert Design oder Logo eines Bild-QR-Codes."""
    
    # 🔹 QR-Code prüfen
    qr: Optional[QRCode] = db.query(QRCode).filter(QRCode.slug == slug).first()
    if qr is None:
        raise HTTPException(status_code=404, detail="QR-Code nicht gefunden")
    if not can_edit_qr(db, user.id, qr):
        raise HTTPException(status_code=403, detail="Keine Berechtigung zum Bearbeiten")

    # 🔹 Logo speichern (falls vorhanden)
    logo_path: Optional[str] = None
    if logo and logo.filename:
        logo_dir = os.path.join("static", "logos")
        os.makedirs(logo_dir, exist_ok=True)

        # Sicheren Dateinamen erstellen
        import uuid
        ext = os.path.splitext(logo.filename or "upload.png")[1]
        safe_name = f"{uuid.uuid4().hex}{ext}"
        file_path = os.path.join(logo_dir, safe_name)

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(logo.file, buffer)

        # Relativen Pfad für Frontend speichern
        logo_path = f"/{file_path}"

    # 🔹 Farben & Logo als JSON verschlüsselt speichern
    qr.set_data({
        "logo": logo_path or "",
        "fg_color": fg_color or "#000000",
        "bg_color": bg_color or "#ffffff"
    })  # 🔐 Verschlüsselt speichern

    db.commit()
    print(f"[UPDATE IMAGE] QR '{slug}' erfolgreich mit neuem Logo/Farben gespeichert.")

    # 🔹 Weiterleitung zurück zur Bearbeitungsseite
    return RedirectResponse(
        url=f"/qr/image/{slug}/edit-image?msg=ok",
        status_code=303
    )
