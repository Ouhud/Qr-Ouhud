from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from utils.qr_config import QR_THEMES, get_qr_style

PRESET_EXPORT_CONFIG = {
    "web": {"size": 600, "dpi": 144, "quiet_zone": 4},
    "print": {"size": 1200, "dpi": 300, "quiet_zone": 6},
    "sticker": {"size": 900, "dpi": 300, "quiet_zone": 6},
    "poster": {"size": 1800, "dpi": 300, "quiet_zone": 8},
}


@dataclass
class QRDesign:
    style: str
    fg: str
    bg: str
    module_style: str
    eye_style: str
    qr_size: int
    output_preset: str
    export_format: str
    frame_style: str
    logo_scale: int
    logo_bg_mode: str
    quiet_zone: int
    dpi: int
    contrast_ratio: float
    warnings: list[str]
    safe_mode: bool
    safe_mode_applied: bool


def _normalize_size(raw_size: Any, output_preset: str) -> int:
    fallback = PRESET_EXPORT_CONFIG.get(str(output_preset or "").strip().lower(), PRESET_EXPORT_CONFIG["web"])["size"]
    try:
        size = int(raw_size or fallback)
    except (TypeError, ValueError):
        size = fallback
    return max(200, min(size, 2000))


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    raw = str(value or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return (13, 42, 120)
    try:
        return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
    except ValueError:
        return (13, 42, 120)


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def comp(v: int) -> float:
        x = v / 255.0
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * comp(r) + 0.7152 * comp(g) + 0.0722 * comp(b)


def _contrast_ratio(fg: str, bg: str) -> float:
    l1 = _relative_luminance(_hex_to_rgb(fg))
    l2 = _relative_luminance(_hex_to_rgb(bg))
    light = max(l1, l2)
    dark = min(l1, l2)
    return (light + 0.05) / (dark + 0.05)


def resolve_design(
    *,
    style: str,
    fg_color: str | None = None,
    bg_color: str | None = None,
    module_style: str | None = None,
    eye_style: str | None = None,
    qr_size: int | None = None,
    output_preset: str | None = None,
    export_format: str | None = None,
    frame_style: str | None = None,
    logo_scale: int | None = None,
    logo_bg_mode: str | None = None,
    safe_mode: str | bool | None = None,
) -> QRDesign:
    style_key = str(style or "modern").strip().lower() or "modern"
    if style_key != "custom" and style_key not in QR_THEMES:
        style_key = "classic"
    conf = get_qr_style(style_key)

    output = str(output_preset or "web").strip().lower()
    output = output if output in PRESET_EXPORT_CONFIG else "web"
    export = str(export_format or "png").strip().lower()
    preset_cfg = PRESET_EXPORT_CONFIG[output]
    # Preset styles must stay deterministic.
    # Only when style == "custom" we accept manual color/module/eye overrides.
    if style_key == "custom":
        fg = str(fg_color or conf["fg"])
        bg = str(bg_color or conf["bg"])
        module = str(module_style or conf.get("module_style") or "square")
        eye = str(eye_style or conf.get("eye_style") or "square")
    else:
        fg = str(conf["fg"])
        bg = str(conf["bg"])
        module = str(conf.get("module_style") or "square")
        eye = str(conf.get("eye_style") or "square")
    qr_px = _normalize_size(qr_size, output)
    quiet_zone = max(2, min(int(preset_cfg["quiet_zone"]), 12))
    dpi = max(72, min(int(preset_cfg["dpi"]), 600))
    safe_raw = str(safe_mode).strip().lower() if safe_mode is not None else ""
    safe_enabled = safe_raw in {"1", "true", "yes", "on"} if safe_mode is not None else False
    safe_applied = False

    contrast = _contrast_ratio(fg, bg)

    if safe_enabled:
        if contrast < 4.5:
            bg_l = _relative_luminance(_hex_to_rgb(bg))
            fg = "#111111" if bg_l > 0.5 else "#FFFFFF"
            contrast = _contrast_ratio(fg, bg)
            safe_applied = True
        if contrast < 4.5:
            fg = "#0D2A78"
            bg = "#FFFFFF"
            contrast = _contrast_ratio(fg, bg)
            safe_applied = True
        if module == "thin-line" and qr_px < 700:
            module = "square"
            safe_applied = True
        if quiet_zone < 4:
            quiet_zone = 4
            safe_applied = True

    warnings: list[str] = []
    if contrast < 4.5:
        warnings.append(f"Low contrast ({contrast:.2f}:1). Recommended >= 4.5:1.")
    if module == "thin-line" and qr_px < 700:
        warnings.append("Thin-line modules at small size can reduce scan reliability.")
    if quiet_zone < 4:
        warnings.append("Quiet zone below 4 modules can break scanner detection.")
    if str(frame_style or "none").strip().lower() == "floating":
        warnings.append("Floating CTA frame is decorative; test on low-end cameras.")
    if safe_enabled and safe_applied:
        warnings.append("Safe mode auto-corrected risky settings for better scan reliability.")

    resolved = QRDesign(
        style=style_key,
        fg=fg,
        bg=bg,
        module_style=module,
        eye_style=eye,
        qr_size=qr_px,
        output_preset=output,
        export_format=export if export in {"png", "svg", "pdf", "zip"} else "png",
        frame_style=str(frame_style or "none").strip().lower(),
        logo_scale=max(8, min(int(logo_scale or 20), 20)),
        logo_bg_mode=str(logo_bg_mode or "auto-white").strip().lower(),
        quiet_zone=quiet_zone,
        dpi=dpi,
        contrast_ratio=contrast,
        warnings=warnings,
        safe_mode=safe_enabled,
        safe_mode_applied=safe_applied,
    )
    return resolved
