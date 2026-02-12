# routes/qr_base.py
# =============================================================================
# 🚀 Zentrale QR-Base-Routen (Ouhud QR)
# - 1 Formular (/qr/new)
# - 1 Create-Route (/qr/create)
# - 1 Update-Route (/qr/update-by-id/{id})
# Speichert alles verschlüsselt in QRCode(encrypted_content) + dynamic_url + Bilddatei
# 🔐 Alle Inhalte werden AES-256-GCM verschlüsselt für Privatschutz
# =============================================================================

from __future__ import annotations
import uuid
import base64
from pathlib import Path
from typing import Union, Dict, Any, Optional

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models.qrcode import QRCode
from routes.auth import get_current_user
from routes.qr.dynamic_url import build_dynamic_url
from utils.access_control import can_edit_qr
from utils.qr_generator import generate_qr_png
from utils.qr_config import get_qr_style
from utils.encryption import encrypt_qr_content

router = APIRouter(prefix="/qr", tags=["QR-Codes"])

templates = Jinja2Templates(directory="templates")

QR_DIR = Path("static/generated_qr")
QR_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# ✅ FORMULAR
# =============================================================================
@router.get("/new", response_class=HTMLResponse)
def new_form(request: Request) -> HTMLResponse:
    """Zeigt das universelle QR-Erstellformular (du kannst dir die Felder dynamisch einblenden)."""
    return templates.TemplateResponse("qr_new_universal_form.html", {"request": request})


# =============================================================================
# ✅ Content-Builder für ALLE 13 Typen
#   Wir nutzen 5 generische Felder (f1..f5). Je Typ interpretieren wir sie.
#   Später kannst du die Felder natürlich per Formular/JS sauber benennen.
# =============================================================================
def build_content(qr_type: str,
                  f1: Optional[str],
                  f2: Optional[str],
                  f3: Optional[str],
                  f4: Optional[str],
                  f5: Optional[str]) -> Dict[str, Any]:
    """
    Erzeugt den content_json passend zum QR-Typ.
    Unterstützt: url, vcard, pdf, wifi, email, sms, tel, social, event, geo, payment, multilink, product
    """

    content: Dict[str, Any] = {
        "raw": {"field1": f1, "field2": f2, "field3": f3, "field4": f4, "field5": f5}
    }

    t = qr_type.lower()

    if t == "url":
        content["url"] = f1

    elif t == "vcard":
        # f1=Vorname, f2=Nachname, f3=Tel, f4=E-Mail, f5=Firma (optional)
        given, family, phone, email, org = f1 or "", f2 or "", f3 or "", f4 or "", f5 or ""
        vcard_text = (
            "BEGIN:VCARD\n"
            "VERSION:3.0\n"
            f"N:{family};{given};;;\n"
            f"FN:{given} {family}\n"
            f"ORG:{org}\n" if org else ""
        )
        if phone:
            vcard_text += f"TEL;TYPE=cell:{phone}\n"
        if email:
            vcard_text += f"EMAIL;TYPE=internet:{email}\n"
        vcard_text += "END:VCARD\n"
        content["vcard"] = {
            "given": given, "family": family, "phone": phone, "email": email, "org": org,
            "vcard_text": vcard_text
        }

    elif t == "pdf":
        # f1 = PDF-Dateipfad (bereits hochgeladen/gespeichert)
        content["pdf_path"] = f1

    elif t == "wifi":
        # f1=SSID, f2=Password, f3=Encryption(WEP|WPA|nopass)
        content["wifi"] = {
            "ssid": f1 or "",
            "password": f2 or "",
            "encryption": (f3 or "WPA").upper(),
        }

    elif t == "email":
        # f1=to, f2=subject, f3=body
        to, subj, body = f1 or "", f2 or "", f3 or ""
        content["mailto"] = f"mailto:{to}?subject={subj}&body={body}"

    elif t == "sms":
        # f1=phone, f2=message
        phone, msg = f1 or "", f2 or ""
        content["sms"] = f"sms:{phone}?body={msg}"

    elif t in ("tel", "phone"):
        # f1=phone
        content["tel"] = f"tel:{f1 or ''}"

    elif t == "social":
        # f1=platform (facebook, instagram, …), f2=url
        content["social"] = {"platform": f1 or "", "url": f2 or ""}

    elif t == "event":
        # f1=SUMMARY, f2=DTSTART(YYYYMMDDThhmmssZ), f3=DTEND, f4=LOCATION, f5=DESCRIPTION
        summary, dtstart, dtend, loc, desc = f1 or "", f2 or "", f3 or "", f4 or "", f5 or ""
        ics = (
            "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Ouhud QR//EN\nBEGIN:VEVENT\n"
            f"SUMMARY:{summary}\n"
            f"DTSTART:{dtstart}\n" if dtstart else ""
        )
        if dtend:
            ics += f"DTEND:{dtend}\n"
        if loc:
            ics += f"LOCATION:{loc}\n"
        if desc:
            ics += f"DESCRIPTION:{desc}\n"
        ics += "END:VEVENT\nEND:VCALENDAR\n"
        content["event"] = {"summary": summary, "dtstart": dtstart, "dtend": dtend, "location": loc, "description": desc, "ics": ics}

    elif t == "geo":
        # f1=lat, f2=lon
        content["geo"] = {"lat": f1, "lon": f2}

    elif t == "payment":
        # f1 = payment_url (z.B. Stripe Checkout), optional weitere Felder
        content["payment_url"] = f1

    elif t == "multilink":
        # f1 = public_html (fertig gerenderte HTML-Seite) ODER f2 = öffentliche URL
        if f1 and f1.strip().startswith("<"):
            content["public_html"] = f1
        if f2:
            content["public_url"] = f2

    elif t == "product":
        # f1=Product URL, f2=Name, f3=Preis, f4=Bild-URL, f5=Beschreibung
        content["product"] = {
            "product_url": f1, "name": f2, "price": f3, "image_url": f4, "description": f5
        }

    # Unbekannt: wir speichern nur raw, damit nichts verloren geht.
    return content

# =============================================================================
# ✅ CREATE – universell für ALLE QR-Typen
# =============================================================================
@router.post("/create", response_class=HTMLResponse)
async def create_qr(
    request: Request,
    db: Session = Depends(get_db),

    qr_type: str = Form(...),
    style: str = Form("ouhud"),

    field1: Optional[str] = Form(None),
    field2: Optional[str] = Form(None),
    field3: Optional[str] = Form(None),
    field4: Optional[str] = Form(None),
    field5: Optional[str] = Form(None),
) -> HTMLResponse:

    # -----------------------------------------------------------
    # ✅ Basisdaten
    # -----------------------------------------------------------
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Nicht eingeloggt")
    slug = uuid.uuid4().hex[:10]

    # -----------------------------------------------------------
    # ✅ Inhalte je Typ erzeugen
    # -----------------------------------------------------------
    content_json = build_content(qr_type, field1, field2, field3, field4, field5)
    
    # 🔐 Verschlüsseln der Inhalte für Privatschutz
    encrypted = encrypt_qr_content(content_json)

    # ✅ Dynamische URL
    dynamic_url = build_dynamic_url(request, slug)

    # -----------------------------------------------------------
    # ✅ QR-Code erzeugen
    # -----------------------------------------------------------
    style_conf = get_qr_style(style)

    def normalize_qr_result(result: Any) -> bytes:
        """Konvertiert dict/bytes zu echten bytes."""
        if isinstance(result, (bytes, bytearray)):
            return bytes(result)
        if isinstance(result, dict) and "bytes" in result:
            return result["bytes"]
        raise TypeError(f"Invalid QR result type: {type(result)}")

    result = generate_qr_png(
        payload=dynamic_url,
        size=600,
        fg=style_conf["fg"],
        bg=style_conf["bg"],
        gradient=style_conf.get("gradient"),
        frame_color=style_conf.get("frame_color"),
        module_style=style_conf.get("module_style"),
        eye_style=style_conf.get("eye_style"),
    )

    qr_bytes = normalize_qr_result(result)

    # -----------------------------------------------------------
    # ✅ Bild speichern
    # -----------------------------------------------------------
    qr_file = QR_DIR / f"{qr_type}_{slug}.png"
    with open(qr_file, "wb") as f:
        f.write(qr_bytes)

    # -----------------------------------------------------------
    # ✅ In DB speichern
    # -----------------------------------------------------------
    qr = QRCode(
        user_id=user_id,
        slug=slug,
        type=qr_type.lower(),
        encrypted_content=encrypted,  # 🔐 Verschlüsselte Inhalte speichern
        dynamic_url=dynamic_url,
        image_path=str(qr_file),
        style=style,
        title=f"{qr_type.upper()} QR",
    )
    db.add(qr)
    db.commit()
    db.refresh(qr)

    # -----------------------------------------------------------
    # ✅ Base64 für Preview
    # -----------------------------------------------------------
    qr_base64 = base64.b64encode(qr_bytes).decode("utf-8")

    return templates.TemplateResponse(
        "qr_create_result.html",
        {
            "request": request,
            "qr": qr,
            "qr_image": qr_base64,
            "dynamic_url": dynamic_url,
        },
    )


# =============================================================================
# ✅ UPDATE – universell
# =============================================================================
@router.post("/update-by-id/{qr_id}", response_class=HTMLResponse)
async def update_qr(
    request: Request,
    qr_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    field1: Optional[str] = Form(None),
    field2: Optional[str] = Form(None),
    field3: Optional[str] = Form(None),
    field4: Optional[str] = Form(None),
    field5: Optional[str] = Form(None),
) -> HTMLResponse:

    qr = db.query(QRCode).filter(QRCode.id == qr_id).first()
    if not qr:
        raise HTTPException(404, "QR nicht gefunden")
    if not can_edit_qr(db, user.id, qr):
        raise HTTPException(403, "Keine Berechtigung")

    # 🔐 Inhalte verschlüsseln und speichern
    content_json = build_content(qr.type, field1, field2, field3, field4, field5)
    qr.set_data(content_json)  # 🔐 Automatische Verschlüsselung
    db.commit()
    db.refresh(qr)

    return HTMLResponse("<h3>✅ QR-Code erfolgreich aktualisiert</h3>")
