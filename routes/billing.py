# =============================================================================
# 💳 routes/billing.py – Stripe-Integration (Ouhud QR)
# =============================================================================
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models.plan import Plan
from models.user import User
from routes.auth import get_current_user
from utils.billing_access import is_billing_exempt_user
from utils.app_url import resolve_app_base_url

# ---------------------------------------------------------------------------
# 🔧 Router & Stripe-Konfiguration
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/billing", tags=["Billing"])

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_DOMAIN = os.getenv("STRIPE_DOMAIN", "").rstrip("/")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

PRICE_IDS: dict[str, str] = {
    "basic": os.getenv("STRIPE_PRICE_BASIC", "").strip(),
    "pro": os.getenv("STRIPE_PRICE_PRO", "").strip(),
    "business": os.getenv("STRIPE_PRICE_BUSINESS", "").strip(),
}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _ts_to_datetime(value: Any) -> Optional[datetime]:
    try:
        if value is None:
            return None
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except Exception:
        return None


def _plan_by_name(db: Session, plan_name: str) -> Optional[Plan]:
    normalized = _normalize_text(plan_name).lower()
    if not normalized:
        return None
    return db.query(Plan).filter(func.lower(Plan.name) == normalized).first()


def _stripe_domain(request: Request) -> str:
    if STRIPE_DOMAIN:
        return STRIPE_DOMAIN
    return resolve_app_base_url(request)


def _plan_from_price_id(db: Session, price_id: str) -> Optional[Plan]:
    normalized_price = _normalize_text(price_id)
    if not normalized_price:
        return None
    for plan_name, configured_price in PRICE_IDS.items():
        if configured_price and configured_price == normalized_price:
            return _plan_by_name(db, plan_name)
    return None


def _find_user_by_customer_id(db: Session, customer_id: Any) -> Optional[User]:
    cid = _normalize_text(customer_id)
    if not cid:
        return None
    try:
        customer = stripe.Customer.retrieve(cid)
        customer_email = _normalize_text(getattr(customer, "email", None) or customer.get("email"))
    except Exception:
        customer_email = ""
    if not customer_email:
        return None
    return db.query(User).filter(User.email == customer_email).first()


def _find_user_for_event(db: Session, payload_obj: dict[str, Any]) -> Optional[User]:
    metadata = payload_obj.get("metadata") or {}
    user_id_raw = _normalize_text(metadata.get("user_id"))
    if user_id_raw.isdigit():
        user = db.query(User).filter(User.id == int(user_id_raw)).first()
        if user:
            return user

    customer_details = payload_obj.get("customer_details") or {}
    email_candidates = [
        payload_obj.get("customer_email"),
        customer_details.get("email"),
        metadata.get("email"),
    ]
    for candidate in email_candidates:
        email = _normalize_text(candidate)
        if not email:
            continue
        user = db.query(User).filter(User.email == email).first()
        if user:
            return user

    return _find_user_by_customer_id(db, payload_obj.get("customer"))


def _apply_plan_update(user: User, plan: Optional[Plan], status_value: str, period_end: Any) -> None:
    if is_billing_exempt_user(user):
        user.plan_status = "active"
        return
    if plan:
        user.plan_id = plan.id
    user.plan_status = status_value or "active"
    user.plan_expiry = _ts_to_datetime(period_end) or user.plan_expiry


def _sync_user_from_checkout_session(db: Session, user: User, session_id: str) -> bool:
    """
    Synchronisiert den Benutzerplan direkt aus einer Stripe Checkout Session.
    Liefert True, wenn ein Update durchgeführt wurde.
    """
    sid = _normalize_text(session_id)
    if not sid or not stripe.api_key:
        return False

    session = stripe.checkout.Session.retrieve(sid, expand=["subscription"])
    metadata = getattr(session, "metadata", None) or session.get("metadata") or {}
    session_email = _normalize_text(
        getattr(session, "customer_email", None)
        or (getattr(session, "customer_details", None) or {}).get("email")
        or session.get("customer_email")
        or (session.get("customer_details") or {}).get("email")
    )
    metadata_user_id = _normalize_text(
        metadata.get("user_id")
        or (getattr(session, "client_reference_id", None) or session.get("client_reference_id"))
    )

    # Sicherheitscheck: Session muss zum eingeloggten Benutzer gehören
    if metadata_user_id and str(user.id) != metadata_user_id:
        return False
    if session_email and _normalize_text(user.email) != session_email:
        return False

    plan: Optional[Plan] = None

    plan_id_raw = _normalize_text(metadata.get("plan_id"))
    if plan_id_raw.isdigit():
        plan = db.query(Plan).filter(Plan.id == int(plan_id_raw)).first()
    if not plan:
        plan = _plan_by_name(db, _normalize_text(metadata.get("plan_name")))

    # Fallback über Line Items / Price ID
    if not plan:
        try:
            line_items = stripe.checkout.Session.list_line_items(sid, limit=10)
            items = getattr(line_items, "data", []) or line_items.get("data", [])
            if items:
                first_item = items[0]
                price_obj = getattr(first_item, "price", None) or first_item.get("price") or {}
                price_id = _normalize_text(getattr(price_obj, "id", None) or price_obj.get("id"))
                plan = _plan_from_price_id(db, price_id)
        except Exception:
            pass

    sub_status = "active"
    period_end = None
    subscription_id = _normalize_text(
        getattr(session, "subscription", None) or session.get("subscription")
    )
    if subscription_id:
        try:
            subscription = stripe.Subscription.retrieve(subscription_id)
            sub_status = _normalize_text(
                getattr(subscription, "status", None) or subscription.get("status")
            ) or "active"
            period_end = (
                getattr(subscription, "current_period_end", None)
                or subscription.get("current_period_end")
            )
            if not plan:
                items = getattr(subscription, "items", None) or subscription.get("items") or {}
                lines = getattr(items, "data", None) or items.get("data", [])
                if lines:
                    first_line = lines[0]
                    price_obj = getattr(first_line, "price", None) or first_line.get("price") or {}
                    price_id = _normalize_text(getattr(price_obj, "id", None) or price_obj.get("id"))
                    plan = _plan_from_price_id(db, price_id)
        except Exception:
            pass

    _apply_plan_update(user, plan, sub_status, period_end)
    db.commit()
    db.refresh(user)
    return True


# ---------------------------------------------------------------------------
# 💼 Billing Übersicht auf die Settings-Seite weiterleiten
# ---------------------------------------------------------------------------
@router.get("/")
def billing_overview() -> RedirectResponse:
    return RedirectResponse("/settings/billing", status_code=303)


# ---------------------------------------------------------------------------
# 🧭 Upgrade auf ausgewählten Plan
# ---------------------------------------------------------------------------
@router.get("/upgrade/{plan_name}")
def billing_upgrade(
    plan_name: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Erstellt eine Stripe-Checkout-Session für den gewählten Plan."""
    if is_billing_exempt_user(user):
        return RedirectResponse("/settings/billing?msg=owner_exempt", status_code=303)

    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe API Key fehlt")

    plan = _plan_by_name(db, plan_name)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan nicht gefunden")
    if float(plan.price or 0) <= 0:
        raise HTTPException(status_code=400, detail="Dieser Plan kann nicht online gebucht werden")

    normalized_plan_name = _normalize_text(plan.name).lower()
    configured_price_id = PRICE_IDS.get(normalized_plan_name, "")

    line_item: dict[str, Any]
    if configured_price_id:
        line_item = {"price": configured_price_id, "quantity": 1}
    else:
        line_item = {
            "price_data": {
                "currency": "eur",
                "product_data": {
                    "name": f"Ouhud QR – {plan.name}",
                    "description": plan.description or "Abo-Upgrade",
                },
                "unit_amount": int(float(plan.price) * 100),
                "recurring": {"interval": "month"},
            },
            "quantity": 1,
        }

    subscription_data: dict[str, Any] = {}
    free_months = int(getattr(plan, "free_months", 0) or 0)
    if free_months > 0:
        subscription_data["trial_period_days"] = free_months * 30

    try:
        domain = _stripe_domain(request)
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer_email=str(user.email),
            client_reference_id=str(user.id),
            metadata={
                "user_id": str(user.id),
                "email": str(user.email),
                "plan_id": str(plan.id),
                "plan_name": normalized_plan_name,
            },
            line_items=[line_item],
            subscription_data=subscription_data or None,
            allow_promotion_codes=True,
            success_url=f"{domain}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{domain}/billing/cancelled",
        )
        checkout_url = getattr(session, "url", None)
        if not isinstance(checkout_url, str):
            raise HTTPException(status_code=500, detail="Stripe-URL fehlt")
        return RedirectResponse(checkout_url, status_code=303)
    except Exception as exc:
        print(f"[Stripe Error] Checkout fehlgeschlagen: {exc}")
        raise HTTPException(status_code=500, detail="Stripe-Checkout konnte nicht erstellt werden")


@router.get("/success")
def billing_success(
    session_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RedirectResponse:
    # Für echte Käufe sofort synchronisieren (Webhook bleibt als Backup aktiv).
    if session_id and not is_billing_exempt_user(user):
        try:
            synced = _sync_user_from_checkout_session(db, user, session_id)
            if synced:
                return RedirectResponse("/settings/billing?status=success&sync=1", status_code=303)
        except Exception as exc:
            print(f"[Stripe Sync] Checkout-Sync fehlgeschlagen: {exc}")
            return RedirectResponse("/settings/billing?status=success&sync=0", status_code=303)

    return RedirectResponse("/settings/billing?status=success", status_code=303)


@router.get("/cancelled")
def billing_cancelled() -> RedirectResponse:
    return RedirectResponse("/settings/billing?status=cancelled", status_code=303)


@router.get("/pay-now")
def billing_pay_now(user: User = Depends(get_current_user)) -> RedirectResponse:
    if is_billing_exempt_user(user):
        return RedirectResponse("/settings/billing?msg=owner_exempt", status_code=303)

    plan_name = _normalize_text(getattr(getattr(user, "plan", None), "name", ""))
    if not plan_name:
        return RedirectResponse("/settings/billing?error=no_plan", status_code=303)
    return RedirectResponse(f"/billing/upgrade/{plan_name.lower()}", status_code=303)


# ---------------------------------------------------------------------------
# 🧭 Kündigung (Subscription Cancel)
# ---------------------------------------------------------------------------
@router.get("/cancel")
def billing_cancel(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Markiert das Abo zur Kündigung (period end), falls Stripe-Abo vorhanden."""
    if is_billing_exempt_user(user):
        return RedirectResponse("/settings/billing?msg=owner_exempt", status_code=303)

    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe API Key fehlt")

    try:
        customers = stripe.Customer.list(email=user.email, limit=1)
        customer_data = getattr(customers, "data", []) or customers.get("data", [])
        customer_id = ""
        if customer_data:
            first_customer = customer_data[0]
            customer_id = _normalize_text(getattr(first_customer, "id", None) or first_customer.get("id"))

        if customer_id:
            subscriptions = stripe.Subscription.list(customer=customer_id, status="all", limit=20)
            sub_data = getattr(subscriptions, "data", []) or subscriptions.get("data", [])
            for subscription in sub_data:
                sub_id = _normalize_text(getattr(subscription, "id", None) or subscription.get("id"))
                sub_status = _normalize_text(
                    getattr(subscription, "status", None) or subscription.get("status")
                )
                if sub_id and sub_status in {"trialing", "active", "past_due", "unpaid"}:
                    stripe.Subscription.modify(sub_id, cancel_at_period_end=True)
                    break

        user.plan_status = "cancel_pending"
        db.commit()
        return RedirectResponse("/settings/billing?msg=cancelled", status_code=303)
    except Exception as exc:
        print(f"[Stripe Error] Kündigung fehlgeschlagen: {exc}")
        raise HTTPException(status_code=500, detail="Kündigung über Stripe fehlgeschlagen")


# ---------------------------------------------------------------------------
# 🔔 Stripe Webhook (Subscription Events)
# ---------------------------------------------------------------------------
@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not WEBHOOK_SECRET:
        return JSONResponse(status_code=500, content={"error": "WEBHOOK_SECRET fehlt"})

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, WEBHOOK_SECRET)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Invalid payload"})
    except stripe.error.SignatureVerificationError:
        return JSONResponse(status_code=400, content={"error": "Invalid signature"})

    event_type = _normalize_text(event.get("type"))
    data = event.get("data", {}).get("object", {}) or {}

    if event_type == "checkout.session.completed":
        user = _find_user_for_event(db, data)
        if user:
            metadata = data.get("metadata") or {}
            plan = None
            plan_id_raw = _normalize_text(metadata.get("plan_id"))
            if plan_id_raw.isdigit():
                plan = db.query(Plan).filter(Plan.id == int(plan_id_raw)).first()
            if not plan:
                plan = _plan_by_name(db, _normalize_text(metadata.get("plan_name")))

            subscription_id = _normalize_text(data.get("subscription"))
            sub_status = "active"
            period_end = None
            if subscription_id:
                try:
                    subscription = stripe.Subscription.retrieve(subscription_id)
                    sub_status = _normalize_text(
                        getattr(subscription, "status", None) or subscription.get("status")
                    ) or "active"
                    period_end = (
                        getattr(subscription, "current_period_end", None)
                        or subscription.get("current_period_end")
                    )
                    if not plan:
                        items = getattr(subscription, "items", None) or subscription.get("items") or {}
                        lines = getattr(items, "data", None) or items.get("data", [])
                        if lines:
                            first_line = lines[0]
                            price_obj = getattr(first_line, "price", None) or first_line.get("price") or {}
                            price_id = _normalize_text(
                                getattr(price_obj, "id", None) or price_obj.get("id")
                            )
                            plan = _plan_from_price_id(db, price_id)
                except Exception as exc:
                    print(f"[WEBHOOK] Subscription konnte nicht geladen werden: {exc}")

            _apply_plan_update(user, plan, sub_status, period_end)
            db.commit()

    elif event_type in {"customer.subscription.updated", "customer.subscription.deleted"}:
        user = _find_user_for_event(db, data)
        if user:
            sub_status = _normalize_text(data.get("status"))
            period_end = data.get("current_period_end")
            items = data.get("items") or {}
            lines = items.get("data", [])
            plan = None
            if lines:
                first_line = lines[0]
                price_obj = first_line.get("price") or {}
                price_id = _normalize_text(price_obj.get("id"))
                plan = _plan_from_price_id(db, price_id)

            if event_type == "customer.subscription.deleted":
                sub_status = "cancelled"

            _apply_plan_update(user, plan, sub_status or "active", period_end)
            db.commit()

    return JSONResponse(status_code=200, content={"status": "ok"})


# ---------------------------------------------------------------------------
# ✅ Testverbindung zu Stripe
# ---------------------------------------------------------------------------
@router.get("/test")
def test_billing_connection() -> dict[str, str]:
    if not stripe.api_key:
        return {"status": "error", "message": "STRIPE_SECRET_KEY fehlt."}
    try:
        balance = stripe.Balance.retrieve()
        return {"status": "ok", "balance": str(balance)}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
