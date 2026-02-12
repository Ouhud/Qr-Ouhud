# =============================================================================
# QR-Code Generator – Ouhud QR
# ----------------------------------------------------------------------------
# Server-side rendering for PNG/SVG/PDF with style, frame and logo safety.
# =============================================================================

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Dict, Optional, Tuple, Union
import logging
import os
import time

import qrcode
import qrcode.image.styledpil
import qrcode.image.styles.colormasks as mask
import qrcode.image.styles.moduledrawers as mod
from qrcode.constants import ERROR_CORRECT_H
from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageOps

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DEFAULT_FG = "#0D2A78"
DEFAULT_BG = "#FFFFFF"


def _normalize_hex(value: str, fallback: str) -> str:
    raw = str(value or "").strip()
    if raw.startswith("#") and len(raw) in {4, 7}:
        return raw
    return fallback


def _build_qr(payload: str, quiet_zone: int = 4) -> qrcode.QRCode:
    border = max(2, min(int(quiet_zone or 4), 12))
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_H,
        box_size=10,
        border=border,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    return qr


def _module_drawer(module_style: str):
    style = str(module_style or "square").strip().lower()
    return {
        "square": mod.SquareModuleDrawer(),
        "rounded": mod.RoundedModuleDrawer(),
        "dots": mod.CircleModuleDrawer(),
        "soft": mod.GappedSquareModuleDrawer(),
        "squircle": mod.RoundedModuleDrawer(),
        "thin-line": mod.VerticalBarsDrawer(),
    }.get(style, mod.SquareModuleDrawer())


def _draw_eye_overlays(img: Image.Image, qr: qrcode.QRCode, fg: str, bg: str, eye_style: str) -> None:
    style = str(eye_style or "square").strip().lower()
    if style in {"", "square"}:
        return

    matrix_size = len(qr.get_matrix())
    if matrix_size <= 0:
        return

    module_px = max(1, img.width // matrix_size)
    border = qr.border
    eye_modules = 7
    eye_px = eye_modules * module_px

    origins = [
        (border * module_px, border * module_px),
        ((matrix_size - border - eye_modules) * module_px, border * module_px),
        (border * module_px, (matrix_size - border - eye_modules) * module_px),
    ]

    draw = ImageDraw.Draw(img)
    inset_outer = max(1, module_px)
    inset_inner = max(2, 2 * module_px)

    for ox, oy in origins:
        outer = [ox, oy, ox + eye_px, oy + eye_px]
        middle = [ox + inset_outer, oy + inset_outer, ox + eye_px - inset_outer, oy + eye_px - inset_outer]
        inner = [ox + inset_inner, oy + inset_inner, ox + eye_px - inset_inner, oy + eye_px - inset_inner]

        if style == "rounded":
            radius = max(6, module_px * 2)
            draw.rounded_rectangle(outer, radius=radius, outline=fg, width=max(2, module_px))
            draw.rounded_rectangle(middle, radius=max(4, radius - module_px), fill=bg)
            draw.rounded_rectangle(inner, radius=max(3, radius - (2 * module_px)), fill=fg)
        elif style == "ring":
            draw.ellipse(outer, outline=fg, width=max(2, module_px))
            draw.ellipse(middle, fill=bg)
            draw.ellipse(inner, fill=fg)
        elif style == "target":
            draw.rounded_rectangle(outer, radius=max(4, module_px), outline=fg, width=max(2, module_px))
            draw.rounded_rectangle(middle, radius=max(3, module_px), fill=bg)
            draw.ellipse(inner, fill=fg)
        elif style == "dots":
            draw.rounded_rectangle(outer, radius=max(4, module_px), outline=fg, width=max(2, module_px))
            draw.rounded_rectangle(middle, radius=max(3, module_px), fill=bg)
            cx = (inner[0] + inner[2]) // 2
            cy = (inner[1] + inner[3]) // 2
            r = max(2, module_px)
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fg)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    raw = str(hex_color or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return (13, 42, 120)
    try:
        return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    except ValueError:
        return (13, 42, 120)


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def conv(v: int) -> float:
        x = v / 255.0
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * conv(r) + 0.7152 * conv(g) + 0.0722 * conv(b)


def _contrast_ratio(fg: str, bg: str) -> float:
    l1 = _relative_luminance(_hex_to_rgb(fg))
    l2 = _relative_luminance(_hex_to_rgb(bg))
    light = max(l1, l2)
    dark = min(l1, l2)
    return (light + 0.05) / (dark + 0.05)


def _apply_logo(
    img: Image.Image,
    logo_path: Optional[str],
    size: int,
    logo_scale: int,
    logo_bg_mode: str,
    logo_position: str,
) -> Image.Image:
    if not logo_path or not os.path.exists(logo_path):
        return img

    try:
        logo = Image.open(logo_path).convert("RGBA")
    except Exception as exc:
        logger.warning("Logo load failed: %s", exc)
        return img

    if logo_position == "background":
        bg_logo = logo.resize(img.size, Image.Resampling.LANCZOS)
        bg_logo.putalpha(170)
        return Image.alpha_composite(bg_logo, img)

    scale = max(8, min(int(logo_scale or 20), 20))
    logo_size = max(36, int(size * (scale / 100)))
    logo = logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)

    pos_x = (img.width - logo_size) // 2
    pos_y = (img.height - logo_size) // 2

    mode = str(logo_bg_mode or "auto-white").strip().lower()
    if mode in {"auto-white", "blur"}:
        plate_pad = max(8, logo_size // 9)
        plate_box = (
            pos_x - plate_pad,
            pos_y - plate_pad,
            pos_x + logo_size + plate_pad,
            pos_y + logo_size + plate_pad,
        )

        if mode == "blur":
            crop = img.crop(plate_box).filter(ImageFilter.GaussianBlur(radius=max(4, logo_size // 10)))
            overlay = Image.new("RGBA", crop.size, (255, 255, 255, 75))
            crop = Image.alpha_composite(crop, overlay)
            img.alpha_composite(crop, dest=(plate_box[0], plate_box[1]))

        badge = Image.new("RGBA", (plate_box[2] - plate_box[0], plate_box[3] - plate_box[1]), (0, 0, 0, 0))
        badge_draw = ImageDraw.Draw(badge)
        badge_draw.rounded_rectangle(
            [0, 0, badge.width - 1, badge.height - 1],
            radius=max(10, logo_size // 5),
            fill=(255, 255, 255, 235),
            outline=(0, 0, 0, 28),
            width=1,
        )
        img.alpha_composite(badge, dest=(plate_box[0], plate_box[1]))

    img.alpha_composite(logo, dest=(pos_x, pos_y))
    return img


def _apply_frame(img: Image.Image, frame_style: str, frame_text: Optional[str], fg: str, bg: str) -> Image.Image:
    style = str(frame_style or "none").strip().lower()
    if style in {"", "none"}:
        return img

    text = (frame_text or "Scan me").strip() or "Scan me"
    font = ImageFont.load_default()

    if style == "corner":
        canvas = ImageOps.expand(img, border=18, fill=bg)
        draw = ImageDraw.Draw(canvas)
        label_w, label_h = draw.textbbox((0, 0), text, font=font)[2:4]
        tag_w = label_w + 22
        tag_h = label_h + 14
        draw.rounded_rectangle([8, 8, 8 + tag_w, 8 + tag_h], radius=10, fill=fg)
        draw.text((19, 14), text, fill=bg, font=font)
        return canvas

    if style == "floating":
        pad = 28
        canvas = ImageOps.expand(img, border=pad, fill=bg)
        draw = ImageDraw.Draw(canvas)
        bubble = 66
        bx = canvas.width - bubble - 10
        by = canvas.height - bubble - 10
        draw.ellipse([bx, by, bx + bubble, by + bubble], fill=fg)
        draw.text((bx + 13, by + 26), "SCAN", fill=bg, font=font)
        return canvas

    # default: pill
    bottom_pad = 78
    canvas = Image.new("RGBA", (img.width, img.height + bottom_pad), bg)
    canvas.paste(img, (0, 0))
    draw = ImageDraw.Draw(canvas)
    label_w, label_h = draw.textbbox((0, 0), text, font=font)[2:4]
    pill_w = label_w + 40
    pill_h = label_h + 18
    x1 = (canvas.width - pill_w) // 2
    y1 = img.height + 16
    draw.rounded_rectangle([x1, y1, x1 + pill_w, y1 + pill_h], radius=pill_h // 2, fill=fg)
    draw.text((x1 + 20, y1 + 9), text, fill=bg, font=font)
    return canvas


def _svg_eye_overlay(style: str, x: int, y: int, s: int, fg: str, bg: str) -> str:
    if style == "rounded":
        r = max(3, s // 6)
        return (
            f'<rect x="{x}" y="{y}" width="{s}" height="{s}" rx="{r}" ry="{r}" fill="none" stroke="{fg}" stroke-width="2" />'
            f'<rect x="{x + s//6}" y="{y + s//6}" width="{(s*2)//3}" height="{(s*2)//3}" rx="{max(2, r//2)}" ry="{max(2, r//2)}" fill="{bg}" />'
            f'<rect x="{x + s//3}" y="{y + s//3}" width="{s//3}" height="{s//3}" rx="{max(2, r//3)}" ry="{max(2, r//3)}" fill="{fg}" />'
        )
    if style == "ring":
        c = x + (s // 2)
        r = s // 2
        return (
            f'<circle cx="{c}" cy="{y + r}" r="{r}" fill="none" stroke="{fg}" stroke-width="2" />'
            f'<circle cx="{c}" cy="{y + r}" r="{(r*2)//3}" fill="{bg}" />'
            f'<circle cx="{c}" cy="{y + r}" r="{max(2, r//3)}" fill="{fg}" />'
        )
    if style == "target":
        c = x + (s // 2)
        r = s // 2
        return (
            f'<rect x="{x}" y="{y}" width="{s}" height="{s}" rx="6" ry="6" fill="none" stroke="{fg}" stroke-width="2" />'
            f'<circle cx="{c}" cy="{y + r}" r="{(r*2)//3}" fill="{bg}" />'
            f'<circle cx="{c}" cy="{y + r}" r="{max(2, r//3)}" fill="{fg}" />'
        )
    if style == "dots":
        c = x + (s // 2)
        r = s // 2
        return (
            f'<rect x="{x}" y="{y}" width="{s}" height="{s}" rx="6" ry="6" fill="none" stroke="{fg}" stroke-width="2" />'
            f'<rect x="{x + s//6}" y="{y + s//6}" width="{(s*2)//3}" height="{(s*2)//3}" rx="4" ry="4" fill="{bg}" />'
            f'<circle cx="{c}" cy="{y + r}" r="{max(2, r//3)}" fill="{fg}" />'
        )
    return ""


def _generate_svg_bytes(
    payload: str,
    size: int,
    fg: str,
    bg: str,
    module_style: str,
    eye_style: str,
    frame_style: str,
    frame_text: Optional[str],
    quiet_zone: int = 4,
) -> bytes:
    qr = _build_qr(payload, quiet_zone=quiet_zone)
    matrix = qr.get_matrix()
    n = len(matrix)
    pad = 12
    cell = max(2, size // max(1, n))
    qr_w = n * cell

    frame_extra = 86 if frame_style in {"pill", "floating"} else 34 if frame_style == "corner" else 0
    width = qr_w + (pad * 2)
    height = qr_w + (pad * 2) + frame_extra

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="{bg}" />',
        f'<rect x="{pad}" y="{pad}" width="{qr_w}" height="{qr_w}" fill="{bg}" />',
    ]

    mod_style = str(module_style or "square").lower()
    for y, row in enumerate(matrix):
        for x, on in enumerate(row):
            if not on:
                continue
            px = pad + (x * cell)
            py = pad + (y * cell)
            if mod_style == "dots":
                r = max(1, cell // 2)
                parts.append(f'<circle cx="{px + r}" cy="{py + r}" r="{r}" fill="{fg}" />')
            elif mod_style in {"rounded", "squircle", "soft"}:
                rx = max(1, cell // (4 if mod_style == "rounded" else 3))
                parts.append(
                    f'<rect x="{px}" y="{py}" width="{cell}" height="{cell}" rx="{rx}" ry="{rx}" fill="{fg}" />'
                )
            elif mod_style == "thin-line":
                line = max(1, cell // 3)
                inset = (cell - line) // 2
                parts.append(
                    f'<rect x="{px + inset}" y="{py + inset}" width="{line}" height="{line}" fill="{fg}" />'
                )
            else:
                parts.append(f'<rect x="{px}" y="{py}" width="{cell}" height="{cell}" fill="{fg}" />')

    eye = str(eye_style or "square").strip().lower()
    if eye in {"rounded", "ring", "target"}:
        eye_px = cell * 7
        origins = [
            (pad + (qr.border * cell), pad + (qr.border * cell)),
            (pad + ((n - qr.border - 7) * cell), pad + (qr.border * cell)),
            (pad + (qr.border * cell), pad + ((n - qr.border - 7) * cell)),
        ]
        for ox, oy in origins:
            parts.append(_svg_eye_overlay(eye, ox, oy, eye_px, fg, bg))

    if frame_style == "corner":
        text = (frame_text or "Scan me").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts.append(f'<rect x="10" y="10" width="88" height="26" rx="8" ry="8" fill="{fg}" />')
        parts.append(f'<text x="18" y="27" fill="{bg}" font-size="12" font-family="Arial, sans-serif">{text}</text>')
    elif frame_style == "floating":
        cy = height - 42
        cx = width - 42
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="28" fill="{fg}" />')
        parts.append(f'<text x="{cx - 16}" y="{cy + 4}" fill="{bg}" font-size="10" font-family="Arial, sans-serif">SCAN</text>')
    elif frame_style == "pill":
        text = (frame_text or "Scan me").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        y = height - 52
        parts.append(f'<rect x="{(width // 2) - 62}" y="{y}" width="124" height="34" rx="17" ry="17" fill="{fg}" />')
        parts.append(f'<text x="{(width // 2) - 28}" y="{y + 21}" fill="{bg}" font-size="13" font-family="Arial, sans-serif">{text}</text>')

    parts.append("</svg>")
    return "".join(parts).encode("utf-8")


def _to_pdf_bytes(png_bytes: bytes, dpi: int = 300) -> bytes:
    with Image.open(BytesIO(png_bytes)).convert("RGB") as img:
        out = BytesIO()
        img.save(out, format="PDF", resolution=float(max(72, min(int(dpi or 300), 600))))
        return out.getvalue()


def generate_qr_png(
    payload: str,
    size: int = 600,
    fg: str = DEFAULT_FG,
    bg: str = DEFAULT_BG,
    logo_path: Optional[str] = None,
    module_style: str = "square",
    eye_style: str = "square",
    frame_text: Optional[str] = None,
    frame_color: str = "#4F46E5",
    gradient: Optional[Tuple[str, str]] = None,
    logo_position: str = "center",
    filename: Optional[str] = None,
    frame_style: str = "none",
    logo_scale: int = 20,
    logo_bg_mode: str = "auto-white",
    quiet_zone: int = 4,
    dpi: int = 300,
) -> Dict[str, Union[str, bytes]]:
    """
    Generates QR as PNG and also returns server-side SVG/PDF bytes.
    Returns: {'path', 'bytes', 'svg_bytes', 'pdf_bytes'}
    """

    safe_fg = _normalize_hex(fg, DEFAULT_FG)
    safe_bg = _normalize_hex(bg, DEFAULT_BG)

    qr = _build_qr(payload, quiet_zone=quiet_zone)

    if gradient and len(gradient) == 2:
        start_rgb = ImageColor.getrgb(gradient[0])
        end_rgb = ImageColor.getrgb(gradient[1])
        color_mask = mask.RadialGradiantColorMask(center_color=start_rgb, edge_color=end_rgb)
    else:
        color_mask = mask.SolidFillColorMask(
            front_color=ImageColor.getrgb(safe_fg),
            back_color=ImageColor.getrgb(safe_bg),
        )

    img = qr.make_image(
        image_factory=qrcode.image.styledpil.StyledPilImage,
        module_drawer=_module_drawer(module_style),
        color_mask=color_mask,
    ).convert("RGBA")

    _draw_eye_overlays(img, qr, safe_fg, safe_bg, eye_style)

    img = img.resize((size, size), Image.Resampling.NEAREST)
    img = ImageOps.expand(img, border=8, fill=safe_bg)

    img = _apply_logo(
        img=img,
        logo_path=logo_path,
        size=size,
        logo_scale=logo_scale,
        logo_bg_mode=logo_bg_mode,
        logo_position=logo_position,
    )

    if frame_text and frame_style in {"none", ""}:
        # Backward compatibility for old text-only frame behavior.
        frame_style = "pill"

    if frame_style not in {"", "none"}:
        img = _apply_frame(
            img=img,
            frame_style=frame_style,
            frame_text=frame_text,
            fg=_normalize_hex(frame_color, safe_fg),
            bg=safe_bg,
        )

    output_dir = Path("static/generated_qr")
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = filename or f"qr_{int(time.time())}.png"
    file_path = output_dir / filename

    png_buffer = BytesIO()
    img.save(png_buffer, format="PNG")
    png_bytes = png_buffer.getvalue()

    img.save(file_path, format="PNG")

    svg_bytes = _generate_svg_bytes(
        payload=payload,
        size=size,
        fg=safe_fg,
        bg=safe_bg,
        module_style=module_style,
        eye_style=eye_style,
        frame_style=frame_style,
        frame_text=frame_text,
        quiet_zone=quiet_zone,
    )
    pdf_bytes = _to_pdf_bytes(png_bytes, dpi=dpi)
    contrast = _contrast_ratio(safe_fg, safe_bg)
    quality_warnings: list[str] = []
    if contrast < 4.5:
        quality_warnings.append(f"Low contrast ({contrast:.2f}:1). Recommended >= 4.5:1.")
    if int(quiet_zone or 4) < 4:
        quality_warnings.append("Quiet zone below 4 modules can reduce scan reliability.")
    if str(module_style or "").strip().lower() == "thin-line" and int(size or 0) < 700:
        quality_warnings.append("Thin-line modules with small size can be hard to scan.")
    if int(logo_scale or 20) > 20:
        quality_warnings.append("Logo size above 20% is unsafe and has been clamped.")

    logger.info("QR-Code gespeichert unter: %s", file_path)
    return {
        "path": str(file_path),
        "bytes": png_bytes,
        "svg_bytes": svg_bytes,
        "pdf_bytes": pdf_bytes,
        "contrast_ratio": contrast,
        "quality_warnings": quality_warnings,
    }
