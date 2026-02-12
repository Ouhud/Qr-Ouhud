# tests/test_templates.py
from pathlib import Path

def test_templates_exist():
    base = Path("templates")

    required = [
        "base.html",
        "dashboard.html",
        "login.html",
        "register.html",

        # URL-QR
        "qr_url.html",
        "qr_edit.html",
        "qr_list.html",

        # Multi-Link
        "qr_multilink.html",

        # Passwort
        

        # PDF / Image / Event / Geo etc.
        # (falls gewünscht, können wir weitere hinzufügen)
    ]

    missing = [f for f in required if not (base / f).exists()]
    assert not missing, f"❌ Fehlende Templates: {missing}"