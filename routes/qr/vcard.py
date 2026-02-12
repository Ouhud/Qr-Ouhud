# routes/qr/vcard.py
# =============================================================================
# 🚀 vCard QR-Code Routes (Ouhud QR)
# 🔐 Alle Inhalte werden AES-256-GCM verschlüsselt für Privatschutz
# =============================================================================

from __future__ import annotations
import os
import uuid
import base64
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models.qrcode import QRCode
from routes.auth import get_current_user
from routes.utils import normalize_url
from utils.access_control import can_edit_qr
from utils.qr_design import resolve_design
from utils.qr_generator import generate_qr_png

router = APIRouter(prefix="/qr/vcard", tags=["vCard QR"])

templates = Jinja2Templates(directory="templates")

QR_DIR = Path("static/generated_qr")
QR_DIR.mkdir(parents=True, exist_ok=True)
LOGO_DIR = Path("static/logos")
LOGO_DIR.mkdir(parents=True, exist_ok=True)


def _save_logo(upload: UploadFile | None, slug: str, prefix: str = "vcard_logo") -> tuple[Optional[str], Optional[str]]:
    """Speichert ein hochgeladenes Bild und gibt (filesystem_path, public_path) zurück."""
    if not upload or not upload.filename:
        return None, None

    ext = Path(upload.filename).suffix.lower() or ".png"
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        return None, None

    filename = f"{prefix}_{slug}{ext}"
    fs_path = LOGO_DIR / filename
    with open(fs_path, "wb") as f:
        f.write(upload.file.read())

    public_path = f"/static/logos/{filename}"
    return str(fs_path), public_path

def _build_dynamic_url(request: Request, slug: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    if "127.0.0.1" in base_url or "localhost" in base_url:
        return f"{base_url}/d/{slug}"
    app_domain = os.getenv("APP_DOMAIN", "").rstrip("/")
    return f"{(app_domain or base_url)}/d/{slug}"


# =============================================================================
# 🔗 VIEW & EDIT ROUTES (Dynamic QR Support)
# =============================================================================

@router.get("/v/{slug}", response_class=HTMLResponse)
def view_vcard(request: Request, slug: str, db: Session = Depends(get_db)) -> HTMLResponse:
    """Zeigt die vCard-Daten an (View-Modus)."""
    qr = db.query(QRCode).filter(QRCode.slug == slug, QRCode.type == "vcard").first()
    if not qr:
        raise HTTPException(404, "vCard nicht gefunden")
    
    vcard_data = qr.get_data() or {}  # 🔐 Automatisch entschlüsselt
    return templates.TemplateResponse(
        "vcard.html",
        {"request": request, "mode": "view", "qr": qr, "vcard": vcard_data}
    )


@router.get("/edit/{slug}", response_class=HTMLResponse)
def edit_vcard_form(
    request: Request,
    slug: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> HTMLResponse:
    """Zeigt das vCard-Bearbeitungsformular."""
    qr = db.query(QRCode).filter(QRCode.slug == slug, QRCode.type == "vcard").first()
    if not qr:
        raise HTTPException(404, "vCard nicht gefunden")
    if not can_edit_qr(db, user.id, qr):
        raise HTTPException(403, "Keine Berechtigung")
    
    vcard_data = qr.get_data() or {}  # 🔐 Automatisch entschlüsselt
    return templates.TemplateResponse(
        "vcard.html",
        {"request": request, "mode": "edit", "qr": qr, "vcard": vcard_data}
    )


@router.get("/{slug}.vcf")
def download_vcard(slug: str, db: Session = Depends(get_db)):
    """Download vCard as .vcf file."""
    from fastapi.responses import FileResponse
    
    qr = db.query(QRCode).filter(QRCode.slug == slug, QRCode.type == "vcard").first()
    if not qr:
        raise HTTPException(404, "vCard nicht gefunden")
    
    vcard_data = qr.get_data() or {}  # 🔐 Automatisch entschlüsselt
    vcard_text = vcard_data.get("vcard_text") or vcard_data.get("vcard", "")
    
    if not vcard_text:
        first_name = vcard_data.get("first_name", "")
        last_name = vcard_data.get("last_name", "")
        org = vcard_data.get("org", "")
        title = vcard_data.get("title", "")
        phone = vcard_data.get("phone", "")
        email = vcard_data.get("email", "")
        website = vcard_data.get("website", "")
        
        vcard_text = (
            "BEGIN:VCARD\n"
            "VERSION:3.0\n"
            f"N:{last_name};{first_name};;;\n"
            f"FN:{first_name} {last_name}\n"
        )
        if org:
            vcard_text += f"ORG:{org}\n"
        if title:
            vcard_text += f"TITLE:{title}\n"
        if phone:
            vcard_text += f"TEL;TYPE=cell:{phone}\n"
        if email:
            vcard_text += f"EMAIL;TYPE=internet:{email}\n"
        if website:
            vcard_text += f"URL:{website}\n"
        vcard_text += "END:VCARD\n"
    
    path = f"/tmp/vcard_{slug}.vcf"
    with open(path, "w", encoding="utf-8") as f:
        f.write(vcard_text)
    
    return FileResponse(path, filename=f"{slug}.vcf", media_type="text/vcard")


# =============================================================================
# ✅ FORM ROUTES
# =============================================================================

@router.get("/", response_class=HTMLResponse)
def show_form(request: Request) -> HTMLResponse:
    """Zeigt das vCard Formular."""
    return templates.TemplateResponse("vcard.html", {"request": request, "mode": "form"})


@router.get("/new", response_class=HTMLResponse)
def new_form_redirect(request: Request) -> HTMLResponse:
    """Redirect to /qr/vcard/ for backwards compatibility."""
    return templates.TemplateResponse("vcard.html", {"request": request, "mode": "form"})


@router.post("/create", response_class=HTMLResponse)
async def create_vcard_qr(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    org: str = Form(""),
    title: str = Form(""),
    email: str = Form(...),
    phone: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    zip_code: str = Form(""),
    country: str = Form(""),
    website: str = Form(""),
    facebook: str = Form(""),
    instagram: str = Form(""),
    linkedin: str = Form(""),
    xing: str = Form(""),
    whatsapp: str = Form(""),
    apple_wallet_url: str = Form(""),
    google_wallet_url: str = Form(""),
    style: str = Form("modern"),
    fg_color: str = Form("#0D2A78"),
    bg_color: str = Form("#FFFFFF"),
    module_style: Optional[str] = Form(None),
    eye_style: Optional[str] = Form(None),
    qr_size: Optional[int] = Form(None),
    output_preset: Optional[str] = Form(None),
    export_format: Optional[str] = Form(None),
    frame_style: Optional[str] = Form(None),
    logo_scale: Optional[int] = Form(None),
    logo_bg_mode: Optional[str] = Form(None),
    safe_mode: Optional[str] = Form(None),
    profile_image: Optional[UploadFile] = File(None),
    qr_logo: Optional[UploadFile] = File(None),
    logo: Optional[UploadFile] = File(None),  # Backward compatibility
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Erstellt einen vCard QR-Code mit Designoptionen."""
    
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Nicht eingeloggt")
    slug = uuid.uuid4().hex[:10]
    
    # vCard Text generieren
    vcard_text = (
        "BEGIN:VCARD\n"
        "VERSION:3.0\n"
        f"N:{last_name};{first_name};;;\n"
        f"FN:{first_name} {last_name}\n"
    )
    if org:
        vcard_text += f"ORG:{org}\n"
    if title:
        vcard_text += f"TITLE:{title}\n"
    if phone:
        vcard_text += f"TEL;TYPE=cell:{phone}\n"
    if email:
        vcard_text += f"EMAIL;TYPE=internet:{email}\n"
    if website:
        vcard_text += f"URL:{website}\n"
    
    # Adresse hinzufügen
    addr_parts = []
    if address:
        addr_parts.append(address)
    if city:
        addr_parts.append(city)
    if zip_code:
        addr_parts.append(zip_code)
    if country:
        addr_parts.append(country)
    
    if addr_parts:
        vcard_text += f"ADR:;;{';;'.join(addr_parts)};;;;\n"
    
    vcard_text += "END:VCARD\n"
    
    # Dynamische URL
    dynamic_url = _build_dynamic_url(request, slug)
    
    # Profilbild und QR-Logo getrennt speichern
    profile_fs_path, profile_public_path = _save_logo(profile_image, slug, "vcard_profile")
    qr_logo_upload = qr_logo or logo
    qr_logo_fs_path, qr_logo_public_path = _save_logo(qr_logo_upload, slug, "vcard_qr_logo")
    
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
        logo_path=qr_logo_fs_path,
        frame_style=design.frame_style,
        logo_scale=design.logo_scale,
        logo_bg_mode=design.logo_bg_mode,
        quiet_zone=design.quiet_zone,
        dpi=design.dpi,
    )
    
    qr_bytes = result if isinstance(result, bytes) else result.get("bytes", b"")
    
    # Bild speichern
    qr_file = QR_DIR / f"vcard_{slug}.png"
    with open(qr_file, "wb") as f:
        f.write(qr_bytes)
    
    # Daten für Verschlüsselung vorbereiten
    vcard_data = {
        "vcard": vcard_text,
        "vcard_text": vcard_text,
        "first_name": first_name,
        "last_name": last_name,
        "org": org,
        "title": title,
        "email": email,
        "phone": phone,
        "address": address,
        "city": city,
        "zip_code": zip_code,
        "country": country,
        "website": website,
        "facebook": facebook,
        "instagram": instagram,
        "linkedin": linkedin,
        "xing": xing,
        "whatsapp": whatsapp,
        "apple_wallet_url": normalize_url(apple_wallet_url) if apple_wallet_url else "",
        "google_wallet_url": normalize_url(google_wallet_url) if google_wallet_url else "",
        "profile_image_path": profile_public_path,
        "qr_logo_path": qr_logo_public_path,
        "logo_path": qr_logo_public_path,
        "design": {
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
        },
    }
    
    # Temporäres QR-Objekt erstellen um Daten zu verschlüsseln
    temp_qr = QRCode()
    temp_qr.set_data(vcard_data)
    encrypted_content = temp_qr.encrypted_content
    
    # In DB speichern
    qr = QRCode(
        user_id=user_id,
        slug=slug,
        type="vcard",
        encrypted_content=encrypted_content,  # 🔐 Verschlüsselt
        dynamic_url=dynamic_url,
        image_path=str(qr_file),
        logo_path=qr_logo_public_path,
        style=design.style,
        color_fg=design.fg,
        color_bg=design.bg,
        qr_size=design.qr_size,
        frame_style=design.frame_style,
        title=f"{first_name} {last_name}",
    )
    db.add(qr)
    db.commit()
    db.refresh(qr)
    
    # Base64 für Preview
    qr_base64 = base64.b64encode(qr_bytes).decode("utf-8")
    
    return templates.TemplateResponse(
        "vcard_result.html",
        {
            "request": request,
            "qr": qr,
            "qr_image": qr_base64,
            "dynamic_url": dynamic_url,
            "vcard": vcard_data,
        },
    )


@router.post("/update/{qr_id}", response_class=HTMLResponse)
async def update_vcard_qr(
    request: Request,
    qr_id: int,
    first_name: str = Form(...),
    last_name: str = Form(...),
    org: str = Form(""),
    title: str = Form(""),
    email: str = Form(...),
    phone: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    zip_code: str = Form(""),
    country: str = Form(""),
    website: str = Form(""),
    facebook: str = Form(""),
    instagram: str = Form(""),
    linkedin: str = Form(""),
    xing: str = Form(""),
    whatsapp: str = Form(""),
    apple_wallet_url: str = Form(""),
    google_wallet_url: str = Form(""),
    profile_image: Optional[UploadFile] = File(None),
    qr_logo: Optional[UploadFile] = File(None),
    logo: Optional[UploadFile] = File(None),  # Backward compatibility
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> HTMLResponse:
    """
    Aktualisiert die vCard-Daten eines dynamischen QR-Codes.
    Das QR-Bild bleibt UNVERÄNDERT - es zeigt immer auf /d/{slug}
    🔐 Daten werden verschlüsselt gespeichert.
    """
    qr = db.query(QRCode).filter(QRCode.id == qr_id, QRCode.type == "vcard").first()
    if not qr:
        raise HTTPException(404, "QR nicht gefunden")
    if not can_edit_qr(db, user.id, qr):
        raise HTTPException(403, "Keine Berechtigung")
    
    # vCard Text aktualisieren
    vcard_text = (
        "BEGIN:VCARD\n"
        "VERSION:3.0\n"
        f"N:{last_name};{first_name};;;\n"
        f"FN:{first_name} {last_name}\n"
    )
    if org:
        vcard_text += f"ORG:{org}\n"
    if title:
        vcard_text += f"TITLE:{title}\n"
    if phone:
        vcard_text += f"TEL;TYPE=cell:{phone}\n"
    if email:
        vcard_text += f"EMAIL;TYPE=internet:{email}\n"
    if website:
        vcard_text += f"URL:{website}\n"
    
    # Adresse hinzufügen
    addr_parts = []
    if address:
        addr_parts.append(address)
    if city:
        addr_parts.append(city)
    if zip_code:
        addr_parts.append(zip_code)
    if country:
        addr_parts.append(country)
    
    if addr_parts:
        vcard_text += f"ADR:;;{';;'.join(addr_parts)};;;;\n"
    
    vcard_text += "END:VCARD\n"
    
    existing_data = qr.get_data() or {}

    # Optional: neues Profilbild hochladen
    profile_public_path = existing_data.get("profile_image_path", "")
    if profile_image and profile_image.filename:
        _, new_profile_public = _save_logo(profile_image, qr.slug, "vcard_profile")
        if new_profile_public:
            profile_public_path = new_profile_public

    # Optional: neues QR-Logo hochladen
    qr_logo_public_path = existing_data.get("qr_logo_path") or qr.logo_path
    qr_logo_upload = qr_logo or logo
    if qr_logo_upload and qr_logo_upload.filename:
        _, new_qr_logo_public = _save_logo(qr_logo_upload, qr.slug, "vcard_qr_logo")
        if new_qr_logo_public:
            qr_logo_public_path = new_qr_logo_public
            qr.logo_path = new_qr_logo_public

    # Daten verschlüsselt speichern
    qr.set_data({
        "vcard": vcard_text,
        "vcard_text": vcard_text,
        "first_name": first_name,
        "last_name": last_name,
        "org": org,
        "title": title,
        "email": email,
        "phone": phone,
        "address": address,
        "city": city,
        "zip_code": zip_code,
        "country": country,
        "website": website,
        "facebook": facebook,
        "instagram": instagram,
        "linkedin": linkedin,
        "xing": xing,
        "whatsapp": whatsapp,
        "apple_wallet_url": normalize_url(apple_wallet_url) if apple_wallet_url else "",
        "google_wallet_url": normalize_url(google_wallet_url) if google_wallet_url else "",
        "profile_image_path": profile_public_path,
        "qr_logo_path": qr_logo_public_path,
        "logo_path": qr_logo_public_path,
    })  # 🔐 Verschlüsselt
    qr.title = f"{first_name} {last_name}"
    
    db.commit()
    db.refresh(qr)
    
    return RedirectResponse(url=f"/qr/vcard/v/{qr.slug}?updated=1", status_code=303)
