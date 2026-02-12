"""
utils/qr_config.py
────────────────────────────────────────────
Globale QR-Code-Design- und Stilkonfiguration
für das Ouhud-QR-System.

Definiert alle Designstile (Farben, Formen, Gradients, Logos)
für QR-Codes, die in der gesamten Anwendung verwendet werden.

Autor: Ouhud GmbH (Hamza Mehmalat)
────────────────────────────────────────────
"""

from typing import Dict, Any

# ─────────────────────────────────────────────
# 🎨 STANDARDDESIGN (Basis)
# ─────────────────────────────────────────────
QR_DEFAULT_STYLE: Dict[str, Any] = {
    "size": 600,
    "fg": "#0D2A78",
    "bg": "#FFFFFF",
    "gradient": ("#2563EB", "#F472B6"),
    "frame_color": "#4F46E5",
    "module_style": "square",
    "eye_style": "square",
    "logo_position": "center",
    "frame_text": None,
    "error_correction": "H",
}

# ─────────────────────────────────────────────
# 🪄 THEMES – Alle Designvarianten
# ─────────────────────────────────────────────
QR_THEMES: Dict[str, Dict[str, Any]] = {
    "classic": {
        "fg": "#000000",
        "bg": "#FFFFFF",
        "gradient": None,
        "frame_color": "#000000",
        "module_style": "square",
        "eye_style": "square",
        "frame_text": "Classic",
    },
    "modern": {
        "fg": "#0D2A78",
        "bg": "#FFFFFF",
        "gradient": ("#2563EB", "#F472B6"),
        "frame_color": "#4F46E5",
        "module_style": "rounded",
        "eye_style": "dots",
        "frame_text": "Modern",
    },
    "rounded": {
        "fg": "#0D2A78",
        "bg": "#F8FAFC",
        "gradient": None,
        "frame_color": "#1E3A8A",
        "module_style": "rounded",
        "eye_style": "rounded",
        "frame_text": "Rounded",
    },
    "dots": {
        "fg": "#2563EB",
        "bg": "#E0E7FF",
        "gradient": None,
        "frame_color": "#3B82F6",
        "module_style": "dots",
        "eye_style": "square",
        "frame_text": "Dots",
    },
    "soft": {
        "fg": "#4F46E5",
        "bg": "#EEF2FF",
        "gradient": None,
        "frame_color": "#4F46E5",
        "module_style": "soft",
        "eye_style": "rounded",
        "frame_text": "Soft",
    },
    "gradient": {
        "fg": "#7C3AED",
        "bg": "#E0E7FF",
        "gradient": ("#7C3AED", "#C084FC"),
        "frame_color": "#7C3AED",
        "module_style": "rounded",
        "eye_style": "rounded",
        "frame_text": "Gradient Modern",
    },
    "premium": {
        "fg": "#D4AF37",
        "bg": "#FFFBEA",
        "gradient": None,
        "frame_color": "#B8860B",
        "module_style": "soft",
        "eye_style": "rounded",
        "frame_text": "Premium Gold",
    },
    "neon": {
        "fg": "#22D3EE",
        "bg": "#0F172A",
        "gradient": ("#06B6D4", "#67E8F9"),
        "frame_color": "#22D3EE",
        "module_style": "dots",
        "eye_style": "square",
        "frame_text": "Neon Glow",
    },
    "dark": {
        "fg": "#FFFFFF",
        "bg": "#0D0D0D",
        "gradient": None,
        "frame_color": "#000000",
        "module_style": "square",
        "eye_style": "square",
        "frame_text": "Dark Mode",
    },
    "ouhud": {
        "fg": "#0D2A78",
        "bg": "#FFFFFF",
        "gradient": ("#2563EB", "#9333EA"),
        "frame_color": "#6366F1",
        "module_style": "rounded",
        "eye_style": "dots",
        "logo_position": "center",
        "frame_text": "Ouhud QR",
    },
    "sunset": {
        "fg": "#F97316",
        "bg": "#FFF7ED",
        "gradient": ("#FB7185", "#F59E0B"),
        "frame_color": "#F97316",
        "module_style": "rounded",
        "eye_style": "rounded",
        "frame_text": "Sunset",
    },
    "ocean": {
        "fg": "#0EA5E9",
        "bg": "#E0F2FE",
        "gradient": ("#0EA5E9", "#22D3EE"),
        "frame_color": "#0EA5E9",
        "module_style": "dots",
        "eye_style": "square",
        "frame_text": "Ocean",
    },
    "forest": {
        "fg": "#15803D",
        "bg": "#ECFDF5",
        "gradient": ("#16A34A", "#22C55E"),
        "frame_color": "#15803D",
        "module_style": "rounded",
        "eye_style": "rounded",
        "frame_text": "Forest",
    },
    "rose": {
        "fg": "#BE185D",
        "bg": "#FFF1F2",
        "gradient": ("#EC4899", "#F472B6"),
        "frame_color": "#BE185D",
        "module_style": "rounded",
        "eye_style": "rounded",
        "frame_text": "Rose Gold",
    },
    "3d_pro": {
        "fg": "#0D2A78",
        "bg": "#F8FAFC",
        "gradient": ("#1E40AF", "#93C5FD"),
        "frame_color": "#1E3A8A",
        "module_style": "square",
        "eye_style": "square",
        "frame_text": "3D Pro",
    },
    "metallic": {
        "fg": "#5F5F5F",
        "bg": "#F9F9F9",
        "gradient": ("#9CA3AF", "#E5E7EB"),
        "frame_color": "#6B7280",
        "module_style": "square",
        "eye_style": "square",
        "frame_text": "Metallic",
    },
    "glass": {
        "fg": "#0D2A78",
        "bg": "#E6F0FF",
        "gradient": ("#60A5FA", "#E0F2FE"),
        "frame_color": "#3B82F6",
        "module_style": "rounded",
        "eye_style": "rounded",
        "frame_text": "Glass",
    },
    "futuristic": {
        "fg": "#00FFFF",
        "bg": "#0A0A0A",
        "gradient": ("#22D3EE", "#6366F1"),
        "frame_color": "#22D3EE",
        "module_style": "dots",
        "eye_style": "square",
        "frame_text": "Futuristic",
    },
    "holo": {
        "fg": "#FF99FF",
        "bg": "#E6E6FF",
        "gradient": ("#00FFFF", "#FF00FF"),
        "frame_color": "#A855F7",
        "module_style": "rounded",
        "eye_style": "rounded",
        "frame_text": "Holo",
    },
    # Brand-kits (Design-System Phase 1)
    "minimal_pro": {
        "fg": "#0F172A",
        "bg": "#FFFFFF",
        "gradient": None,
        "frame_color": "#0F172A",
        "module_style": "rounded",
        "eye_style": "square",
        "frame_text": "Minimal Pro",
    },
    "glass_modern": {
        "fg": "#1D4ED8",
        "bg": "#F8FAFC",
        "gradient": ("#93C5FD", "#E0F2FE"),
        "frame_color": "#2563EB",
        "module_style": "rounded",
        "eye_style": "rounded",
        "frame_text": "Glass Modern",
    },
    "dark_luxury": {
        "fg": "#F8FAFC",
        "bg": "#0B1020",
        "gradient": ("#334155", "#0F172A"),
        "frame_color": "#94A3B8",
        "module_style": "square",
        "eye_style": "ring",
        "frame_text": "Dark Luxury",
    },
    "neon_tech": {
        "fg": "#22D3EE",
        "bg": "#020617",
        "gradient": ("#22D3EE", "#6366F1"),
        "frame_color": "#22D3EE",
        "module_style": "dots",
        "eye_style": "target",
        "frame_text": "Neon Tech",
    },
    "mono_clean": {
        "fg": "#000000",
        "bg": "#FFFFFF",
        "gradient": None,
        "frame_color": "#000000",
        "module_style": "square",
        "eye_style": "square",
        "frame_text": "Mono Clean",
    },
}

# ─────────────────────────────────────────────
# 🧠 FUNKTION: Design abrufen
# ─────────────────────────────────────────────
def get_qr_style(style_name: str = "modern") -> Dict[str, Any]:
    """
    Gibt das gewünschte QR-Design als Dictionary zurück.
    Wenn das angegebene Theme nicht existiert, wird automatisch
    das Standard-Design verwendet.
    """
    style = QR_THEMES.get(style_name, {})
    return {
        **QR_DEFAULT_STYLE,
        **style,
        "logo_position": style.get("logo_position", "center"),
        "meta": {"author": "Ouhud GmbH", "version": "1.0"},
    }
