# routes/qr/payment.py
# =============================================================================
# 🚀 Payment QR-Code Routes (Ouhud QR)
# =============================================================================

from __future__ import annotations
import uuid
import base64
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models.qrcode import QRCode
from routes.qr.dynamic_url import build_dynamic_url
from routes.qr.logo_utils import save_qr_logo
from utils.qr_generator import generate_qr_png
from utils.qr_design import resolve_design

router = APIRouter(prefix="/qr/payment", tags=["Payment QR"])

templates = Jinja2Templates(directory="templates")

QR_DIR = Path("static/generated_qr")
QR_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_amount(value: str) -> str:
    raw = (value or "").strip().replace(",", ".")
    if not raw:
        return ""
    try:
        return f"{float(raw):.2f}"
    except ValueError:
        return ""


def _build_epc_payload(
    recipient: str,
    iban: str,
    amount: str,
    currency: str,
    purpose: str,
) -> str:
    """
    Einfaches EPC/SCT-Format (SEPA-QR-Text).
    """
    clean_iban = re.sub(r"\\s+", "", (iban or "").upper())
    norm_amount = _normalize_amount(amount)
    ccy = (currency or "EUR").upper()
    amount_line = f"{ccy}{norm_amount}" if norm_amount else ""

    lines = [
        "BCD",
        "002",
        "1",
        "SCT",
        "",  # BIC optional
        (recipient or "").strip(),
        clean_iban,
        amount_line,
        "",  # Purpose Code optional
        (purpose or "").strip(),
        "",  # Ref optional
    ]
    return "\n".join(lines)


@router.get("/", response_class=HTMLResponse)
def show_form(request: Request) -> HTMLResponse:
    """Zeigt das Payment QR-Formular."""
    return templates.TemplateResponse("qr_payment.html", {"request": request})


@router.post("/generate", response_class=HTMLResponse)
async def create_payment_qr(
    request: Request,
    payment_url: str = Form(""),
    title: str = Form(""),
    description: str = Form(""),
    amount: str = Form(""),
    currency: str = Form("EUR"),
    recipient: str = Form(""),
    iban: str = Form(""),
    purpose: str = Form(""),
    style: str = Form("ouhud"),
    fg_color: Optional[str] = Form(None),
    bg_color: Optional[str] = Form(None),
    module_style: Optional[str] = Form(None),
    eye_style: Optional[str] = Form(None),
    qr_size: Optional[int] = Form(None),
    output_preset: Optional[str] = Form(None),
    export_format: Optional[str] = Form(None),
    frame_style: Optional[str] = Form(None),
    logo_scale: Optional[int] = Form(None),
    logo_bg_mode: Optional[str] = Form(None),
    safe_mode: Optional[str] = Form(None),
    logo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Erstellt einen Payment QR-Code."""
    
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Nicht eingeloggt")
    slug = uuid.uuid4().hex[:10]
    logo_fs_path, logo_public_path = save_qr_logo(logo, slug, "payment_logo")
    
    payment_url = (payment_url or "").strip()
    recipient = (recipient or "").strip()
    iban = (iban or "").strip()
    purpose = (purpose or "").strip()
    norm_amount = _normalize_amount(amount)

    # Wenn kein Payment-Link vorhanden ist, versuche EPC-Daten zu bauen
    epc_payload = ""
    if not payment_url and recipient and iban:
        epc_payload = _build_epc_payload(recipient, iban, norm_amount, currency, purpose)

    if not payment_url and not epc_payload:
        raise HTTPException(
            status_code=400,
            detail="Bitte entweder eine Payment-URL oder Empfänger + IBAN angeben.",
        )

    # Dynamische URL
    dynamic_url = build_dynamic_url(request, slug)
    
    # QR-Code generieren
    design = resolve_design(
        style=style,
        fg_color=fg_color,
        bg_color=bg_color,
        module_style=module_style,
        eye_style=eye_style,
        qr_size=qr_size,
        output_preset=output_preset,
        export_format=export_format,
        frame_style=frame_style,
        logo_scale=logo_scale,
        logo_bg_mode=logo_bg_mode,
        safe_mode=safe_mode,
    )
    result = generate_qr_png(
        payload=dynamic_url,
        size=design.qr_size,
        fg=design.fg,
        bg=design.bg,
        module_style=design.module_style,
        eye_style=design.eye_style,
        logo_path=logo_fs_path,
        frame_style=design.frame_style,
        logo_scale=design.logo_scale,
        logo_bg_mode=design.logo_bg_mode,
        quiet_zone=design.quiet_zone,
        dpi=design.dpi,
    )
    
    qr_bytes = result if isinstance(result, bytes) else result.get("bytes", b"")
    
    # Bild speichern
    qr_file = QR_DIR / f"payment_{slug}.png"
    with open(qr_file, "wb") as f:
        f.write(qr_bytes)
    
    # In DB speichern
    display_title = (title or "").strip() or (f"SEPA Zahlung: {recipient}" if recipient else "Payment")

    qr = QRCode(
        user_id=user_id,
        slug=slug,
        type="payment",
        dynamic_url=dynamic_url,
        image_path=str(qr_file),
        logo_path=logo_public_path,
        style=design.style,
        color_fg=design.fg,
        color_bg=design.bg,
        qr_size=design.qr_size,
        frame_style=design.frame_style,
        title=display_title,
    )
    qr.set_data(
        {
            "payment_url": payment_url,
            "recipient": recipient,
            "iban": iban,
            "purpose": purpose,
            "epc_payload": epc_payload,
            "title": display_title,
            "description": description,
            "amount": norm_amount,
            "currency": currency,
            "logo_path": logo_public_path,
            "design": {
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
            },
        }
    )
    db.add(qr)
    db.commit()
    db.refresh(qr)
    
    # Base64 für Preview
    qr_base64 = base64.b64encode(qr_bytes).decode("utf-8")
    
    return templates.TemplateResponse(
        "qr_payment_result.html",
        {
            "request": request,
            "qr": qr,
            "qr_image": qr_base64,
            "dynamic_url": dynamic_url,
            "payment_url": payment_url,
            "recipient": recipient,
            "iban": iban,
            "amount": norm_amount,
            "currency": currency,
            "purpose": purpose,
        },
    )
