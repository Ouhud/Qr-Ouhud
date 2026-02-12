# routes/qr/pdf.py
# =============================================================================
# 🚀 PDF QR-Code Routes (Ouhud QR)
# 🔐 Alle Inhalte werden AES-256-GCM verschlüsselt für Privatschutz
# =============================================================================

from __future__ import annotations
import uuid
import base64
from pathlib import Path
from typing import Optional

import os

from fastapi import APIRouter, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models.qrcode import QRCode
from routes.auth import get_current_user
from routes.qr.logo_utils import save_qr_logo
from utils.access_control import can_edit_qr
from utils.qr_generator import generate_qr_png
from utils.qr_design import resolve_design

router = APIRouter(prefix="/qr/pdf", tags=["PDF QR"])

templates = Jinja2Templates(directory="templates")

QR_DIR = Path("static/generated_qr")
PDF_DIR = Path("static/uploads/pdfs")
QR_DIR.mkdir(parents=True, exist_ok=True)
PDF_DIR.mkdir(parents=True, exist_ok=True)

def _build_dynamic_url(request: Request, slug: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    # Wenn lokal getestet wird, nutze immer die aktuelle Base-URL
    if "127.0.0.1" in base_url or "localhost" in base_url:
        return f"{base_url}/d/{slug}"
    app_domain = os.getenv("APP_DOMAIN", "").rstrip("/")
    return f"{(app_domain or base_url)}/d/{slug}"


@router.get("/", response_class=HTMLResponse)
def show_form(request: Request) -> HTMLResponse:
    """Zeigt das PDF QR-Formular."""
    return templates.TemplateResponse(
        "qr_pdf_form.html",
        {"request": request, "qr": None, "qr_data": {}, "mode": "create"},
    )


@router.get("/edit/{slug}", response_class=HTMLResponse)
def edit_pdf_qr(
    request: Request,
    slug: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> HTMLResponse:
    """Zeigt das PDF QR-Bearbeitungsformular."""
    qr = db.query(QRCode).filter(QRCode.slug == slug, QRCode.type == "pdf").first()
    if not qr:
        raise HTTPException(404, "PDF-QR nicht gefunden")
    if not can_edit_qr(db, user.id, qr):
        raise HTTPException(403, "Keine Berechtigung")
    
    qr_data = qr.get_data() or {}
    return templates.TemplateResponse(
        "qr_pdf_form.html",
        {"request": request, "qr": qr, "qr_data": qr_data, "mode": "edit"},
    )


@router.post("/generate", response_class=HTMLResponse)
async def create_pdf_qr(
    request: Request,
    title: str = Form(""),
    file: UploadFile = File(...),
    logo: Optional[UploadFile] = File(None),
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
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Erstellt einen PDF QR-Code."""
    
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Nicht eingeloggt")
    slug = uuid.uuid4().hex[:10]
    logo_fs_path, logo_public_path = save_qr_logo(logo, slug, "pdf_logo")
    
    # PDF speichern
    file_ext = file.filename.split(".")[-1] if file.filename else "pdf"
    pdf_filename = f"{slug}.{file_ext}"
    pdf_path = PDF_DIR / pdf_filename
    
    content = await file.read()
    with open(pdf_path, "wb") as f:
        f.write(content)
    
    # Dynamische URL
    dynamic_url = _build_dynamic_url(request, slug)
    
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
    qr_file = QR_DIR / f"pdf_{slug}.png"
    with open(qr_file, "wb") as f:
        f.write(qr_bytes)
    
    # Temporäres QR-Objekt erstellen um Daten zu verschlüsseln
    temp_qr = QRCode()
    temp_qr.set_data(
        {
            "pdf_path": str(pdf_path),
            "title": title,
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
    encrypted_content = temp_qr.encrypted_content
    
    # In DB speichern
    qr = QRCode(
        user_id=user_id,
        slug=slug,
        type="pdf",
        encrypted_content=encrypted_content,  # 🔐 Verschlüsselt
        dynamic_url=dynamic_url,
        image_path=str(qr_file),
        logo_path=logo_public_path,
        style=design.style,
        color_fg=design.fg,
        color_bg=design.bg,
        qr_size=design.qr_size,
        frame_style=design.frame_style,
        title=title or f"PDF: {file.filename}",
    )
    db.add(qr)
    db.commit()
    db.refresh(qr)
    
    # Base64 für Preview
    qr_base64 = base64.b64encode(qr_bytes).decode("utf-8")
    
    return templates.TemplateResponse(
        "qr_pdf_result.html",
        {"request": request, "qr": qr, "qr_image": qr_base64, "dynamic_url": dynamic_url},
    )


@router.post("/update/{qr_id}", response_class=HTMLResponse)
async def update_pdf_qr(
    request: Request,
    qr_id: int,
    title: str = Form(""),
    file: UploadFile = File(None),
    style: str = Form("modern"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> HTMLResponse:
    """Aktualisiert einen PDF QR-Code. 🔐 Daten werden verschlüsselt gespeichert."""
    qr = db.query(QRCode).filter(QRCode.id == qr_id, QRCode.type == "pdf").first()
    if not qr:
        raise HTTPException(404, "QR nicht gefunden")
    if not can_edit_qr(db, user.id, qr):
        raise HTTPException(403, "Keine Berechtigung")
    
    # Bestehende Daten abrufen und aktualisieren
    existing_data = qr.get_data() or {}  # 🔐 Entschlüsseln
    
    # Daten aktualisieren
    existing_data["title"] = title
    qr.title = title
    qr.style = style
    
    # Optional: Neue PDF-Datei hochladen
    if file and file.filename:
        file_ext = file.filename.split(".")[-1] if file.filename else "pdf"
        pdf_filename = f"{qr.slug}.{file_ext}"
        pdf_path = PDF_DIR / pdf_filename
        
        content = await file.read()
        with open(pdf_path, "wb") as f:
            f.write(content)
        existing_data["pdf_path"] = str(pdf_path)
    
    # Daten verschlüsselt speichern
    qr.set_data(existing_data)  # 🔐 Verschlüsseln
    
    db.commit()
    db.refresh(qr)
    
    return templates.TemplateResponse(
        "qr_pdf_form.html",
        {
            "request": request,
            "qr": qr,
            "qr_data": existing_data,
            "mode": "edit",
            "message": "✅ PDF-QR wurde aktualisiert!",
        },
    )
