# routes/qr/event.py
# =============================================================================
# 🚀 Event/Calendar QR-Code Routes (Ouhud QR)
# =============================================================================

from __future__ import annotations
import os
import uuid
import base64
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models.qrcode import QRCode
from routes.qr.logo_utils import save_qr_logo
from utils.qr_generator import generate_qr_png
from utils.qr_design import resolve_design

router = APIRouter(prefix="/qr/event", tags=["Event QR"])

templates = Jinja2Templates(directory="templates")

QR_DIR = Path("static/generated_qr")
QR_DIR.mkdir(parents=True, exist_ok=True)


def _build_dynamic_url(request: Request, slug: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    if "127.0.0.1" in base_url or "localhost" in base_url:
        return f"{base_url}/d/{slug}"
    app_domain = os.getenv("APP_DOMAIN", "").rstrip("/")
    return f"{(app_domain or base_url)}/d/{slug}"


def _split_datetime_local(value: str) -> tuple[str, str]:
    if not value:
        return "", ""
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
    except ValueError:
        if "T" in value:
            date_part, time_part = value.split("T", 1)
            return date_part, time_part[:5]
        return value, ""


def _ics_datetime(date_str: str, time_str: str) -> str:
    if not date_str:
        return ""
    compact_date = date_str.replace("-", "")
    compact_time = (time_str or "00:00").replace(":", "")
    if len(compact_time) == 4:
        compact_time = f"{compact_time}00"
    return f"{compact_date}T{compact_time}"


@router.get("/", response_class=HTMLResponse)
def show_form(request: Request) -> HTMLResponse:
    """Zeigt das Event QR-Formular."""
    return templates.TemplateResponse("qr_event.html", {"request": request})


@router.post("/generate", response_class=HTMLResponse)
async def create_event_qr(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    location: str = Form(""),
    start: Optional[str] = Form(None),
    end: Optional[str] = Form(None),
    start_date: Optional[str] = Form(None),
    start_time: str = Form(""),
    end_date: Optional[str] = Form(None),
    end_time: str = Form(""),
    dynamicQR: Optional[str] = Form(None),
    style: str = Form("modern"),
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
    """Erstellt einen Event QR-Code (iCal Format)."""
    
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Nicht eingeloggt")
    slug = uuid.uuid4().hex[:10]
    logo_fs_path, logo_public_path = save_qr_logo(logo, slug, "event_logo")
    
    # Datum/Zeit aus datetime-local oder Fallback-Feldern auflösen
    if start:
        start_date, start_time = _split_datetime_local(start)
    if end:
        end_date, end_time = _split_datetime_local(end)
    if not start_date:
        raise HTTPException(status_code=422, detail="Startdatum fehlt")

    dtstart = _ics_datetime(start_date, start_time)
    dtend = _ics_datetime(end_date or "", end_time)
    
    # iCal Text generieren
    ics_text = (
        "BEGIN:VCALENDAR\n"
        "VERSION:2.0\n"
        "PRODID:-//Ouhud QR//EN\n"
        "BEGIN:VEVENT\n"
        f"SUMMARY:{title}\n"
    )
    if dtstart:
        ics_text += f"DTSTART:{dtstart}\n"
    if dtend:
        ics_text += f"DTEND:{dtend}\n"
    if location:
        ics_text += f"LOCATION:{location}\n"
    if description:
        ics_text += f"DESCRIPTION:{description}\n"
    ics_text += "END:VEVENT\nEND:VCALENDAR\n"
    
    # Dynamik-Option aus Formular (Checkbox)
    is_dynamic = str(dynamicQR or "0") == "1"
    dynamic_url = _build_dynamic_url(request, slug) if is_dynamic else None

    # QR-Code generieren (dynamisch = /d/{slug}, statisch = iCal-Inhalt direkt)
    payload = dynamic_url or ics_text
    
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
        payload=payload,
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
    qr_file = QR_DIR / f"event_{slug}.png"
    with open(qr_file, "wb") as f:
        f.write(qr_bytes)
    
    # In DB speichern
    qr = QRCode(
        user_id=user_id,
        slug=slug,
        type="event",
        dynamic_url=dynamic_url,
        image_path=str(qr_file),
        is_dynamic=is_dynamic,
        logo_path=logo_public_path,
        style=design.style,
        color_fg=design.fg,
        color_bg=design.bg,
        qr_size=design.qr_size,
        frame_style=design.frame_style,
        title=title,
    )
    qr.set_data(
        {
            "ics": ics_text,
            "title": title,
            "description": description,
            "location": location,
            "start_date": start_date,
            "start_time": start_time,
            "end_date": end_date,
            "end_time": end_time,
            "is_dynamic": is_dynamic,
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
        "qr_event_result.html",
        {"request": request, "qr": qr, "qr_image": qr_base64, "dynamic_url": dynamic_url, "ics": ics_text},
    )
