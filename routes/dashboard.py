# =============================================================================
# 📊 routes/dashboard.py
# -----------------------------------------------------------------------------
# Dashboard-Routenmodul für eingeloggte Benutzer:
#   • Zeigt persönliche QR-Code-Statistiken
#   • Diagramme (Scans, Typen, Geräte, Nutzung)
#   • Letzte Scans (aktuell Demo, später dynamisch)
# -----------------------------------------------------------------------------
# Autor: Mohamad Hamza Mehmalat
# Projekt: Ouhud QR
# =============================================================================

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from typing import List
from datetime import date, datetime, timedelta, timezone, time
import calendar

from database import get_db
from models.user import User
from models.qrcode import QRCode
from models.qr_scan import QRScan
from models.qr_conversion import QRConversion
from models.lead_capture import LeadCapture
from models.feedback_entry import FeedbackEntry
from models.coupon_redemption import CouponRedemption
from routes.auth import get_current_user  # Für Session-Authentifizierung
from utils.billing_access import is_billing_exempt_user

# -------------------------------------------------------------------------
# ⚙️ Router & Template Setup
# -------------------------------------------------------------------------
router = APIRouter(prefix="/dashboard", tags=["Dashboard"])
templates = Jinja2Templates(directory="templates")
TEST_IPS = {"127.0.0.1", "::1", "localhost"}
PLAN_LIMITS = {
    "basic": 10,
    "pro": 50,
    "business": 250,
    "enterprise": 999999,
}


def _detect_device_label(scan: QRScan) -> str:
    ua = ((getattr(scan, "user_agent", None) or getattr(scan, "device", "") or "")).lower()
    if not ua:
        return "Andere"
    if "iphone" in ua or "ipad" in ua or "ios" in ua:
        return "iPhone/iPad"
    if "android" in ua:
        return "Android"
    if "windows" in ua or "macintosh" in ua or "mac os" in ua or "linux" in ua:
        return "Desktop"
    if "bot" in ua or "spider" in ua or "crawler" in ua or "curl/" in ua:
        return "Bot/Tool"
    return "Andere"


def _to_utc(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _plan_usage(user: User, total_qrcodes: int) -> tuple[str, str, int, int, int, bool, str, str]:
    """
    Liefert:
    (plan_name, plan_display_name, qr_limit, qr_usage, qr_remaining, qr_unlimited, qr_limit_display, qr_remaining_display)
    basierend auf echtem Benutzer-Plan.
    Fallback: Basic mit Limit 10.
    """
    current_plan = getattr(user, "plan", None)
    plan_name = getattr(current_plan, "name", None) or "Basic"
    plan_key = str(plan_name).strip().lower()

    if plan_key in PLAN_LIMITS:
        qr_limit = PLAN_LIMITS[plan_key]
    else:
        qr_limit = int(getattr(current_plan, "qr_limit", PLAN_LIMITS["basic"]) or PLAN_LIMITS["basic"])

    qr_usage = total_qrcodes
    qr_remaining = max(qr_limit - qr_usage, 0)
    qr_unlimited = False
    plan_display_name = plan_name
    qr_limit_display = str(qr_limit)
    qr_remaining_display = str(qr_remaining)

    if is_billing_exempt_user(user):
        plan_display_name = f"{plan_name} (Intern frei)"
        qr_unlimited = True
        qr_limit_display = "Unbegrenzt"
        qr_remaining_display = "Unbegrenzt"

    return (
        plan_name,
        plan_display_name,
        qr_limit,
        qr_usage,
        qr_remaining,
        qr_unlimited,
        qr_limit_display,
        qr_remaining_display,
    )


# -------------------------------------------------------------------------
# 📊 Dashboard-Hauptseite
# -------------------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Zeigt das Dashboard mit Statistiken, Diagrammen und QR-Code-Übersicht."""

    # 🔒 Sicherheitsprüfung: nur eingeloggte Benutzer
    if not user:
        return RedirectResponse("/auth/login", status_code=303)
    lang = getattr(getattr(request, "state", None), "lang", "de")

    # 📦 QR-Codes des aktuellen Benutzers laden
    qr_codes: List[QRCode] = db.query(QRCode).filter(QRCode.user_id == user.id).all()

    range_key = (request.query_params.get("range") or "7d").lower()
    allowed_ranges = {"7d", "30d", "6m"}
    if range_key not in allowed_ranges:
        range_key = "7d"
    include_test = (request.query_params.get("include_test") or "").lower() in {"1", "true", "yes"}

    # 🧮 Basisstatistiken berechnen
    total_qrcodes = len(qr_codes)

    # Echte Scans aus der Datenbank laden
    qr_ids = [qr.id for qr in qr_codes]
    qr_map = {qr.id: qr for qr in qr_codes}
    all_scans: List[QRScan] = []
    total_scans = 0
    scans_today = 0

    now_utc = datetime.now(timezone.utc)
    today = now_utc.date()
    start_today = datetime.combine(today, time.min, tzinfo=timezone.utc)
    end_today = start_today + timedelta(days=1)

    if qr_ids:
        scan_query = db.query(QRScan).filter(QRScan.qr_id.in_(qr_ids))
        if not include_test:
            scan_query = (
                scan_query
                .filter(or_(QRScan.location.is_(None), ~QRScan.location.in_(TEST_IPS)))
                .filter(or_(QRScan.user_agent.is_(None), ~QRScan.user_agent.ilike("curl/%")))
                .filter(or_(QRScan.user_agent.is_(None), ~QRScan.user_agent.ilike("%postmanruntime%")))
                .filter(or_(QRScan.user_agent.is_(None), ~QRScan.user_agent.ilike("%insomnia%")))
                .filter(or_(QRScan.user_agent.is_(None), ~QRScan.user_agent.ilike("%httpie/%")))
            )

        total_scans = (
            scan_query.with_entities(func.count(QRScan.id)).scalar()
            or 0
        )
        scans_today = (
            scan_query.with_entities(func.count(QRScan.id))
            .filter(
                QRScan.timestamp >= start_today,
                QRScan.timestamp < end_today,
            )
            .scalar()
            or 0
        )
        all_scans = scan_query.all()
    
    active_qr_codes = len([q for q in qr_codes if q.active])

    # 📂 QR-Code-Aufschlüsselung nach Typ
    stats = {
        "gesamt": total_qrcodes,
        "url": len([q for q in qr_codes if getattr(q, "type", "") == "url"]),
        "vcard": len([q for q in qr_codes if getattr(q, "type", "") == "vcard"]),
        "pdf": len([q for q in qr_codes if getattr(q, "type", "") == "pdf"]),
        "image": len([q for q in qr_codes if getattr(q, "type", "") == "image"]),
        "wifi": len([q for q in qr_codes if getattr(q, "type", "") == "wifi"]),
        "email": len([q for q in qr_codes if getattr(q, "type", "") == "email"]),
        "sms": len([q for q in qr_codes if getattr(q, "type", "") == "sms"]),
    }

    # 📈 Echte Scan-Daten aus der Datenbank (nach Zeitraum)
    chart_labels: list[str] = []
    scans_per_period: list[int] = []
    filtered_scans: list[QRScan] = []
    if lang == "en":
        range_title = "Last 7 days"
    elif lang == "ar":
        range_title = "آخر 7 أيام"
    else:
        range_title = "Letzte 7 Tage"
    period_start = datetime.combine(today - timedelta(days=6), time.min, tzinfo=timezone.utc)
    period_end = now_utc

    if range_key == "7d":
        from_date = today - timedelta(days=6)
        start_range = datetime.combine(from_date, time.min, tzinfo=timezone.utc)
        period_start = start_range
        filtered_scans = (
            [s for s in all_scans if (_to_utc(s.timestamp) or start_range) >= start_range]
        )
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            chart_labels.append(d.strftime("%a"))
            scans_per_period.append(
                len([s for s in filtered_scans if (_to_utc(s.timestamp) or start_range).date() == d])
            )
        if lang == "en":
            range_title = "Last 7 days"
        elif lang == "ar":
            range_title = "آخر 7 أيام"
        else:
            range_title = "Letzte 7 Tage"
    elif range_key == "30d":
        from_date = today - timedelta(days=29)
        start_range = datetime.combine(from_date, time.min, tzinfo=timezone.utc)
        period_start = start_range
        filtered_scans = (
            [s for s in all_scans if (_to_utc(s.timestamp) or start_range) >= start_range]
        )
        for i in range(29, -1, -1):
            d = today - timedelta(days=i)
            chart_labels.append(d.strftime("%d.%m"))
            scans_per_period.append(
                len([s for s in filtered_scans if (_to_utc(s.timestamp) or start_range).date() == d])
            )
        if lang == "en":
            range_title = "Last 30 days"
        elif lang == "ar":
            range_title = "آخر 30 يومًا"
        else:
            range_title = "Letzte 30 Tage"
    else:  # 6m
        current = today.replace(day=1)
        months: list[tuple[int, int]] = []
        for _ in range(6):
            months.append((current.year, current.month))
            if current.month == 1:
                current = current.replace(year=current.year - 1, month=12)
            else:
                current = current.replace(month=current.month - 1)
        months = list(reversed(months))

        first_year, first_month = months[0]
        from_date = date(first_year, first_month, 1)
        start_range = datetime.combine(from_date, time.min, tzinfo=timezone.utc)
        period_start = start_range
        filtered_scans = (
            [s for s in all_scans if (_to_utc(s.timestamp) or start_range) >= start_range]
        )
        for y, m in months:
            chart_labels.append(f"{calendar.month_abbr[m]} {str(y)[2:]}")
            scans_per_period.append(
                len(
                    [
                        s
                        for s in filtered_scans
                        if (_to_utc(s.timestamp) or start_range).year == y
                        and (_to_utc(s.timestamp) or start_range).month == m
                    ]
                )
            )
        if lang == "en":
            range_title = "Last 6 months"
        elif lang == "ar":
            range_title = "آخر 6 أشهر"
        else:
            range_title = "Letzte 6 Monate"
    
    # QR-Typ-Verteilung
    qr_type_labels = []
    qr_type_counts = []
    type_stats = {}
    for qr in qr_codes:
        qr_type = getattr(qr, "type", "unknown")
        type_stats[qr_type] = type_stats.get(qr_type, 0) + 1
    
    for qr_type, count in type_stats.items():
        qr_type_labels.append(qr_type.upper())
        qr_type_counts.append(count)
    
    # Geräte-Verteilung aus Scans (im gewählten Zeitraum)
    device_labels = []
    device_counts = []
    device_stats = {}
    for scan in filtered_scans:
        label = _detect_device_label(scan)
        if label == "Bot/Tool":
            continue
        device_stats[label] = device_stats.get(label, 0) + 1

    order = ["iPhone/iPad", "Android", "Desktop", "Andere"]
    for label in order:
        count = device_stats.get(label, 0)
        if count > 0:
            if label == "Andere":
                if lang == "en":
                    device_labels.append("Other")
                elif lang == "ar":
                    device_labels.append("أخرى")
                else:
                    device_labels.append("Andere")
            else:
                device_labels.append(label)
            device_counts.append(count)

    if not device_labels:
        if lang == "en":
            device_labels = ["No data"]
        elif lang == "ar":
            device_labels = ["لا توجد بيانات"]
        else:
            device_labels = ["Keine Daten"]
        device_counts = [1]

    # ---------------------------------------------------------------------
    # 🔝 Top 10 QR-Codes (aktueller Zeitraum vs. Vorzeitraum)
    # ---------------------------------------------------------------------
    top_qr_labels: list[str] = []
    top_qr_current: list[int] = []
    top_qr_previous: list[int] = []
    top_qr_delta_pct: list[float] = []

    current_counts: dict[int, int] = {}
    for s in filtered_scans:
        current_counts[s.qr_id] = current_counts.get(s.qr_id, 0) + 1

    previous_counts: dict[int, int] = {}
    if qr_ids:
        duration = period_end - period_start
        previous_start = period_start - duration
        previous_end = period_start
        prev_query = (
            db.query(QRScan)
            .filter(QRScan.qr_id.in_(qr_ids))
            .filter(QRScan.timestamp >= previous_start, QRScan.timestamp < previous_end)
        )
        if not include_test:
            prev_query = (
                prev_query
                .filter(or_(QRScan.location.is_(None), ~QRScan.location.in_(TEST_IPS)))
                .filter(or_(QRScan.user_agent.is_(None), ~QRScan.user_agent.ilike("curl/%")))
                .filter(or_(QRScan.user_agent.is_(None), ~QRScan.user_agent.ilike("%postmanruntime%")))
                .filter(or_(QRScan.user_agent.is_(None), ~QRScan.user_agent.ilike("%insomnia%")))
                .filter(or_(QRScan.user_agent.is_(None), ~QRScan.user_agent.ilike("%httpie/%")))
            )
        for s in prev_query.all():
            previous_counts[s.qr_id] = previous_counts.get(s.qr_id, 0) + 1

    total_counts: dict[int, int] = {}
    for s in all_scans:
        total_counts[s.qr_id] = total_counts.get(s.qr_id, 0) + 1

    ranked_qr_ids = sorted(current_counts.keys(), key=lambda qid: current_counts[qid], reverse=True)[:10]
    if not ranked_qr_ids:
        ranked_qr_ids = sorted(total_counts.keys(), key=lambda qid: total_counts[qid], reverse=True)[:10]

    for qid in ranked_qr_ids:
        qr_obj = qr_map.get(qid)
        if not qr_obj:
            continue
        label = f"{qr_obj.slug} ({(qr_obj.type or '').upper()})"
        cur = int(current_counts.get(qid, 0))
        prev = int(previous_counts.get(qid, 0))
        if prev > 0:
            delta = round(((cur - prev) / prev) * 100.0, 1)
        elif cur > 0:
            delta = 100.0
        else:
            delta = 0.0
        top_qr_labels.append(label)
        top_qr_current.append(cur)
        top_qr_previous.append(prev)
        top_qr_delta_pct.append(delta)

    # ---------------------------------------------------------------------
    # 🔥 Heatmap: Wochentag × Stunde
    # ---------------------------------------------------------------------
    if lang == "en":
        heatmap_day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    elif lang == "ar":
        heatmap_day_labels = ["الاث", "الثل", "الأر", "الخ", "الجم", "السب", "الأح"]
    else:
        heatmap_day_labels = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    heatmap_counts: dict[tuple[int, int], int] = {}
    for s in filtered_scans:
        ts = _to_utc(s.timestamp)
        if ts is None:
            continue
        key = (ts.weekday(), ts.hour)
        heatmap_counts[key] = heatmap_counts.get(key, 0) + 1
    heatmap_points = [
        {"x": hour, "y": weekday, "v": count}
        for (weekday, hour), count in sorted(heatmap_counts.items())
    ]
    heatmap_max = max([p["v"] for p in heatmap_points], default=1)

    # ---------------------------------------------------------------------
    # 🧭 Conversion-Funnel (Scans → Visits → Conversions)
    # ---------------------------------------------------------------------
    scans_stage = len(filtered_scans)
    visits_stage = scans_stage
    conversions_stage = 0
    conversion_rate_label = "0%"

    if qr_ids:
        visit_events = (
            db.query(func.count(QRConversion.id))
            .filter(QRConversion.qr_id.in_(qr_ids))
            .filter(QRConversion.created_at >= period_start, QRConversion.created_at < period_end)
            .filter(QRConversion.event_type == "visit")
            .scalar()
            or 0
        )
        conversion_events = (
            db.query(func.count(QRConversion.id))
            .filter(QRConversion.qr_id.in_(qr_ids))
            .filter(QRConversion.created_at >= period_start, QRConversion.created_at < period_end)
            .filter(QRConversion.event_type != "visit")
            .scalar()
            or 0
        )
        lead_conversions = (
            db.query(func.count(LeadCapture.id))
            .filter(LeadCapture.qr_id.in_(qr_ids))
            .filter(LeadCapture.created_at >= period_start, LeadCapture.created_at < period_end)
            .scalar()
            or 0
        )
        feedback_conversions = (
            db.query(func.count(FeedbackEntry.id))
            .filter(FeedbackEntry.qr_id.in_(qr_ids))
            .filter(FeedbackEntry.created_at >= period_start, FeedbackEntry.created_at < period_end)
            .scalar()
            or 0
        )
        coupon_conversions = (
            db.query(func.count(CouponRedemption.id))
            .filter(CouponRedemption.qr_id.in_(qr_ids))
            .filter(CouponRedemption.redeemed_at >= period_start, CouponRedemption.redeemed_at < period_end)
            .scalar()
            or 0
        )

        visits_stage = max(scans_stage, int(visit_events))
        raw_conversions = int(conversion_events + lead_conversions + feedback_conversions + coupon_conversions)
        conversions_stage = min(raw_conversions, visits_stage)

    if visits_stage > 0:
        rate = conversions_stage / visits_stage
        if rate == 0:
            conversion_rate_label = "0%"
        elif rate < 0.01:
            conversion_rate_label = "<1%"
        else:
            conversion_rate_label = f"{round(rate * 100, 1)}%"

    # ---------------------------------------------------------------------
    # 📦 Tariflimit-Berechnung (echter Abo-Plan)
    # ---------------------------------------------------------------------
    (
        plan_name,
        plan_display_name,
        qr_limit,
        qr_usage,
        qr_remaining,
        qr_unlimited,
        qr_limit_display,
        qr_remaining_display,
    ) = _plan_usage(user, total_qrcodes)

    if qr_unlimited:
        qr_usage_percent = 0
        if lang == "en":
            qr_usage_percent_label = "Internal free"
        elif lang == "ar":
            qr_usage_percent_label = "مجاني داخلي"
        else:
            qr_usage_percent_label = "Intern frei"
    elif qr_limit > 0:
        ratio = qr_usage / qr_limit
        qr_usage_percent = int(round(min(ratio, 1) * 100))
        if qr_usage > 0 and qr_usage_percent == 0:
            qr_usage_percent = 1
        if ratio == 0:
            qr_usage_percent_label = "0%"
        elif ratio < 0.01:
            qr_usage_percent_label = "<1%"
        else:
            qr_usage_percent_label = f"{qr_usage_percent}%"
    else:
        qr_usage_percent = 0
        qr_usage_percent_label = "0%"

    # 🕒 Letzte Scans (aus gefiltertem Zeitraum)
    recent_scans = []
    for scan in sorted(filtered_scans, key=lambda s: s.timestamp, reverse=True)[:25]:
        qr = qr_map.get(scan.qr_id)
        scan_device = (getattr(scan, "device", "-") or "-").strip()
        if scan_device and len(scan_device) > 32:
            scan_device = scan_device[:32] + "..."
        recent_scans.append({
            "date": scan.timestamp.strftime("%d.%m.%Y %H:%M"),
            "type": getattr(qr, "type", "unknown") if qr else "unknown",
            "location": getattr(scan, "location", "-"),
            "device": scan_device,
            "slug": getattr(qr, "slug", "-") if qr else "-",
        })

    # ---------------------------------------------------------------------
    # 🎨 Template rendern
    # ---------------------------------------------------------------------
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "title": "📊 Ouhud QR – Dashboard",
            "user": user,
            "qr_codes": qr_codes,
            "qr_stats": stats,
            "total_qrcodes": total_qrcodes,
            "total_scans": total_scans,
            "active_qr_codes": active_qr_codes,
            "scans_today": scans_today,
            "chart_labels": chart_labels,
            "scans_per_period": scans_per_period,
            "range_key": range_key,
            "range_title": range_title,
            "qr_type_labels": qr_type_labels,
            "qr_type_counts": qr_type_counts,
            "device_labels": device_labels,
            "device_counts": device_counts,
            "recent_scans": recent_scans,
            "plan_name": plan_name,
            "plan_display_name": plan_display_name,
            "qr_limit": qr_limit,
            "qr_usage": qr_usage,
            "qr_remaining": qr_remaining,
            "qr_unlimited": qr_unlimited,
            "qr_limit_display": qr_limit_display,
            "qr_remaining_display": qr_remaining_display,
            "qr_usage_percent": qr_usage_percent,
            "qr_usage_percent_label": qr_usage_percent_label,
            "top_qr_labels": top_qr_labels,
            "top_qr_current": top_qr_current,
            "top_qr_previous": top_qr_previous,
            "top_qr_delta_pct": top_qr_delta_pct,
            "heatmap_day_labels": heatmap_day_labels,
            "heatmap_points": heatmap_points,
            "heatmap_max": heatmap_max,
            "funnel_labels": ["Scans", "Visits", "Conversions"],
            "funnel_values": [scans_stage, visits_stage, conversions_stage],
            "conversion_rate_label": conversion_rate_label,
        },
    )
