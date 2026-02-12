from __future__ import annotations

import base64
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models.feedback_entry import FeedbackEntry
from models.qrcode import QRCode
from routes.qr.logo_utils import save_qr_logo
from utils.qr_design import resolve_design
from utils.qr_generator import generate_qr_png

router = APIRouter(prefix="/qr/feedback", tags=["Feedback QR"])
templates = Jinja2Templates(directory="templates")
QR_DIR = Path("static/generated_qr")
QR_DIR.mkdir(parents=True, exist_ok=True)


def _build_dynamic_url(request: Request, slug: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    if "127.0.0.1" in base_url or "localhost" in base_url:
        return f"{base_url}/d/{slug}"
    app_domain = os.getenv("APP_DOMAIN", "").rstrip("/")
    return f"{(app_domain or base_url)}/d/{slug}"


@router.get("/", response_class=HTMLResponse)
def show_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("qr_feedback_form.html", {"request": request})


@router.post("/generate", response_class=HTMLResponse)
async def generate_feedback_qr(
    request: Request,
    question: str = Form("Wie zufrieden sind Sie?"),
    low_label: str = Form("Sehr unzufrieden"),
    high_label: str = Form("Sehr zufrieden"),
    title: str = Form(""),
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
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Nicht eingeloggt")
    slug = uuid.uuid4().hex[:10]
    dynamic_url = _build_dynamic_url(request, slug)
    logo_fs_path, logo_public_path = save_qr_logo(logo, slug, "feedback_logo")

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
    qr_file = QR_DIR / f"feedback_{slug}.png"
    with open(qr_file, "wb") as f:
        f.write(qr_bytes)

    qr = QRCode(
        user_id=user_id,
        slug=slug,
        type="feedback",
        dynamic_url=dynamic_url,
        image_path=str(qr_file),
        logo_path=logo_public_path,
        style=design.style,
        color_fg=design.fg,
        color_bg=design.bg,
        qr_size=design.qr_size,
        frame_style=design.frame_style,
        title=title or "NPS Feedback",
    )
    qr.set_data(
        {
            "question": question,
            "low_label": low_label,
            "high_label": high_label,
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
    db.add(qr)
    db.commit()
    db.refresh(qr)

    qr_image = base64.b64encode(qr_bytes).decode("utf-8")
    return templates.TemplateResponse(
        "qr_feedback_result.html",
        {"request": request, "qr": qr, "qr_image": qr_image, "dynamic_url": dynamic_url},
    )


@router.get("/v/{slug}", response_class=HTMLResponse)
def view_feedback_page(request: Request, slug: str, db: Session = Depends(get_db)) -> HTMLResponse:
    qr = db.query(QRCode).filter(QRCode.slug == slug, QRCode.type == "feedback").first()
    if not qr:
        raise HTTPException(404, "Feedback-QR nicht gefunden")
    data = qr.get_data() or {}
    return templates.TemplateResponse("qr_feedback_view.html", {"request": request, "qr": qr, "data": data})


@router.post("/submit/{slug}")
def submit_feedback(
    slug: str,
    score: int = Form(...),
    comment: str = Form(""),
    db: Session = Depends(get_db),
):
    qr = db.query(QRCode).filter(QRCode.slug == slug, QRCode.type == "feedback").first()
    if not qr:
        raise HTTPException(404, "Feedback-QR nicht gefunden")
    if score < 1 or score > 10:
        raise HTTPException(400, "Score muss zwischen 1 und 10 liegen")

    fb = FeedbackEntry(qr_id=qr.id, score=score, comment=comment.strip() or None, source="qr")
    db.add(fb)
    db.commit()
    return RedirectResponse(f"/qr/feedback/v/{slug}?submitted=1", status_code=303)
