# =============================================================================
# 💳 routes/billing_stripe.py
# -----------------------------------------------------------------------------
# Professionelle Stripe-Integration für Ouhud QR
# Funktionen:
#   - Checkout-Session erstellen (Basic / Pro / Business)
#   - Erfolgsseite nach Zahlung
#   - Abbruchseite bei Storno
#   - Webhook für automatische Abo-Aktualisierung
# -----------------------------------------------------------------------------
# Autor: Hamza Mehmalat
# Projekt: Ouhud QR
# =============================================================================

import os
import stripe
from fastapi import APIRouter, Request, status, Depends
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from database import get_db
from models.user import User   # ✅ optional, für spätere Webhook-Verknüpfung
from utils.app_url import resolve_app_base_url

# ✅ 1. .env laden (mit STRIPE_SECRET_KEY, STRIPE_PUBLIC_KEY)
load_dotenv()

# ✅ 2. Router konfigurieren
router = APIRouter(prefix="/billing", tags=["Stripe Billing"])

# ✅ 3. Stripe initialisieren
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
# =============================================================================
# 💳 Stripe Preis-IDs (Testmodus)
# =============================================================================
PRICE_IDS = {
    "basic": "price_1SQDqOR6SWNPwRZI6Sl4lba8",     # Ouhud QR Basic – 4,99 €
    "pro": "price_1SQDowR6SWNPwRZIDimGg1hT",       # Ouhud QR Pro – 14,99 €
    "business": "price_1SQDqtR6SWNPwRZImG9Pnhmw",  # Ouhud QR Business – 29,99 €
}

# =============================================================================
# 💳 4. Checkout starten
# =============================================================================
@router.get("/checkout/{plan_name}")
async def create_checkout_session(request: Request, plan_name: str):
    """
    Erstellt eine Stripe-Checkout-Session für das gewählte Abo.
    """
    plan_name = plan_name.lower().strip()
    price_id = PRICE_IDS.get(plan_name)

    if not price_id:
        print(f"[❌ FEHLER] Unbekannter Plan: {plan_name}")
        return RedirectResponse("/settings/billing?error=invalid_plan", status_code=status.HTTP_303_SEE_OTHER)

    domain_url = os.getenv("STRIPE_DOMAIN", "").strip().rstrip("/") or resolve_app_base_url(request)

    try:
        # 🔹 Stripe Session erzeugen
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            customer_email=request.session.get("user_email", "demo@ouhud.com"),
            success_url=f"{domain_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{domain_url}/billing/cancel",
        )
        print(f"[✅ INFO] Stripe Checkout erstellt → {session.url}")
        return RedirectResponse(session.url, status_code=status.HTTP_303_SEE_OTHER)

    except Exception as e:
        print(f"[⚠️ FEHLER] Stripe-Checkout fehlgeschlagen: {e}")
        return RedirectResponse("/settings/billing?error=stripe_error", status_code=status.HTTP_303_SEE_OTHER)


# =============================================================================
# ✅ 5. Erfolgreiche Zahlung
# =============================================================================
@router.get("/success", response_class=HTMLResponse)
def payment_success(request: Request):
    """
    Wird nach erfolgreicher Zahlung angezeigt.
    """
    return """
    <section style="font-family:system-ui, sans-serif; text-align:center; margin-top:100px;">
        <div style="display:inline-block; padding:40px; border-radius:20px; background:#f8fafc; box-shadow:0 4px 12px rgba(0,0,0,0.1);">
            <h1 style="color:#0d2a78;">✅ Zahlung erfolgreich!</h1>
            <p style="color:#1e293b; margin-top:10px;">Dein Abonnement wurde erfolgreich aktiviert.</p>
            <a href="/dashboard" style="display:inline-block; margin-top:25px; padding:10px 25px;
               background-color:#2563eb; color:white; text-decoration:none; border-radius:8px; font-weight:500;">
               Zum Dashboard
            </a>
        </div>
    </section>
    """


# =============================================================================
# ❌ 6. Abgebrochene Zahlung
# =============================================================================
@router.get("/cancel", response_class=HTMLResponse)
def payment_cancel(request: Request):
    """
    Wird angezeigt, wenn der Benutzer die Zahlung abbricht.
    """
    return """
    <section style="font-family:system-ui, sans-serif; text-align:center; margin-top:100px;">
        <div style="display:inline-block; padding:40px; border-radius:20px; background:#fff5f5; box-shadow:0 4px 12px rgba(0,0,0,0.1);">
            <h1 style="color:#b91c1c;">❌ Zahlung abgebrochen</h1>
            <p style="color:#374151; margin-top:10px;">Die Zahlung wurde nicht abgeschlossen.</p>
            <a href="/settings/billing" style="display:inline-block; margin-top:25px; padding:10px 25px;
               background-color:#0d2a78; color:white; text-decoration:none; border-radius:8px; font-weight:500;">
               Zurück zu den Einstellungen
            </a>
        </div>
    </section>
    """
# =============================================================================
# 🪝 7. Stripe Webhook – verarbeitet Zahlungsereignisse sicher
# =============================================================================
from fastapi.responses import JSONResponse
from database import get_db
from models.user import User
from sqlalchemy.orm import Session

@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Stripe ruft diesen Endpunkt auf, wenn ein Zahlungsereignis auftritt:
    z. B. erfolgreiche Zahlung, abgebrochene Zahlung, Rechnung erstellt etc.
    """
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        # ✅ Webhook-Event validieren
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=webhook_secret
        )
        print(f"[STRIPE WEBHOOK] Ereignis empfangen: {event['type']}")

    except stripe.error.SignatureVerificationError as e:
        print(f"[❌ Ungültige Signatur] {e}")
        return JSONResponse(status_code=400, content={"error": "Invalid signature"})

    except Exception as e:
        print(f"[❌ Fehler beim Verarbeiten des Webhooks] {e}")
        return JSONResponse(status_code=400, content={"error": str(e)})

    # -------------------------------------------------------------------------
    # 💳 1. Erfolgreiche Zahlung → Benutzer-Abo aktivieren
    # -------------------------------------------------------------------------
    if event["type"] == "checkout.session.completed":
        session_data = event["data"]["object"]
        customer_email = session_data.get("customer_email")

        print(f"[✅ Zahlung erfolgreich] Kunde: {customer_email}")

        # Benutzer anhand der E-Mail finden und Plan updaten
        if customer_email:
            user = db.query(User).filter(User.email == customer_email).first()
            if user:
                user.plan = "pro"  # oder 'business' / je nach Preis-ID
                db.commit()
                print(f"[🔄 Benutzer aktualisiert] {user.email} → Plan: {user.plan}")
            else:
                print(f"[⚠️ Kein Benutzer gefunden für {customer_email}]")

    # -------------------------------------------------------------------------
    # ⚠️ 2. Zahlung fehlgeschlagen
    # -------------------------------------------------------------------------
    elif event["type"] == "invoice.payment_failed":
        print("[⚠️ Zahlung fehlgeschlagen]")

    # -------------------------------------------------------------------------
    # 🧾 3. Abo gekündigt
    # -------------------------------------------------------------------------
    elif event["type"] == "customer.subscription.deleted":
        sub = event["data"]["object"]
        email = sub.get("customer_email")
        print(f"[ℹ️ Abo gekündigt] Kunde: {email}")

    return JSONResponse(status_code=200, content={"status": "success"})
