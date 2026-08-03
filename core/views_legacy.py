# reports/views_legacy.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict, Tuple, List

from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Q
from django.http import JsonResponse
from django.shortcuts import render

from bookings.models import Booking, BookingService
from payments.models import PaymentReceived
from services.models import Hotel, Transfer, SightSeeing, Ticket, Visa, Insurance, Passport
from clients.models import Client
from suppliers.models import Supplier


ZERO = Decimal("0")


def to_decimal(val) -> Decimal:
    try:
        return Decimal(str(val or 0))
    except Exception:
        return ZERO


def is_cash_mode(mode) -> bool:
    if not mode or not getattr(mode, "name", None):
        return False
    return (mode.name or "").strip().lower() == "cash"


SERVICE_MODEL_MAP = {
    "hotel": Hotel,
    "transfer": Transfer,
    "sightseeing": SightSeeing,
    "ticket": Ticket,
    "visa": Visa,
    "insurance": Insurance,
    "passport": Passport,
}

# Optional labels for UI / modal breakdown
SERVICE_LABELS = {
    "hotel": "Hotel",
    "transfer": "Transfer",
    "sightseeing": "Sightseeing",
    "ticket": "Ticket",
    "visa": "Visa",
    "insurance": "Insurance",
    "passport": "Passport",
}


# ---------------------------
# Legacy rules (CRITERIA)
# ---------------------------
def booking_is_pure_legacy(booking_id: int) -> bool:
    """
    PURE legacy:
      - has approved legacy payments (service IS NULL)
      - AND has NO approved service-linked payments (service IS NOT NULL)
    """
    has_legacy = PaymentReceived.objects.filter(
        booking_id=booking_id, approved=True, service__isnull=True
    ).exists()
    if not has_legacy:
        return False

    has_new = PaymentReceived.objects.filter(
        booking_id=booking_id, approved=True, service__isnull=False
    ).exists()
    return not has_new


def legacy_sales_from_payments(booking_id: int) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
    """
    Sales = sum(amount) from approved legacy payments (service NULL)
    Discount = sum(discount) from the same rows
    Split sales by cash/non-cash using payment.mode
    """
    qs = (
        PaymentReceived.objects
        .filter(booking_id=booking_id, approved=True, service__isnull=True)
        .select_related("mode")
    )
    if not qs.exists():
        return ZERO, ZERO, ZERO, ZERO

    sales_total = ZERO
    sales_cash = ZERO
    discount_total = ZERO

    for p in qs:
        amt = to_decimal(getattr(p, "amount", 0))
        sales_total += amt
        if is_cash_mode(getattr(p, "mode", None)):
            sales_cash += amt
        discount_total += to_decimal(getattr(p, "discount", 0))

    sales_non_cash = sales_total - sales_cash
    return sales_total, sales_cash, sales_non_cash, discount_total


def purchase_totals_from_services(booking_id: int) -> Tuple[Decimal, Decimal, Decimal, List[Dict]]:
    """
    Purchase = sum(purchase_amount) across ALL service tables for this booking.
    Split cash/non-cash by each service row's mode.
    Also returns a breakdown list for modal.
    """
    purchase_total = ZERO
    purchase_cash = ZERO
    breakdown: List[Dict] = []

    for code, model in SERVICE_MODEL_MAP.items():
        rows = model.objects.filter(booking_id=booking_id).select_related("mode")

        svc_total = ZERO
        svc_cash = ZERO

        for obj in rows:
            amt = to_decimal(getattr(obj, "purchase_amount", 0))
            svc_total += amt
            if is_cash_mode(getattr(obj, "mode", None)):
                svc_cash += amt

        if svc_total > 0:
            svc_non_cash = svc_total - svc_cash
            breakdown.append({
                "service": SERVICE_LABELS.get(code, code),
                "purchase_cash": float(svc_cash),
                "purchase_non_cash": float(svc_non_cash),
                "purchase_total": float(svc_total),
            })

        purchase_total += svc_total
        purchase_cash += svc_cash

    purchase_non_cash = purchase_total - purchase_cash
    return purchase_total, purchase_cash, purchase_non_cash, breakdown


def passes_supplier_filter(booking_id: int, supplier_id: str) -> bool:
    """
    Supplier filter for legacy:
    Keep booking if ANY service table has a row with supplier_id for that booking.
    """
    if not supplier_id:
        return True

    for _, model in SERVICE_MODEL_MAP.items():
        # If some models don't have supplier_id, this can raise FieldError.
        # If your schema is consistent, you're fine. If not, comment out supplier filtering for those.
        try:
            if model.objects.filter(booking_id=booking_id, supplier_id=supplier_id).exists():
                return True
        except Exception:
            # model doesn't have supplier_id or other mismatch
            continue

    return False


# ---------------------------
# Page
# Template location: core/templates/staff_legacy_profit.html
# ---------------------------
@login_required
def staff_legacy_reports(request):
    return render(request, "staff_legacy_profit.html")


# ---------------------------
# Filters (dropdown data)
# ---------------------------
@login_required
def staff_legacy_filters_data(request):
    user = request.user

    # Base booking set: only bookings related to this staff and pure-legacy
    base = (
        Booking.objects
        .filter(
            Q(created_by=user) |
            Q(id__in=BookingService.objects.filter(assigned_to=user).values_list("booking_id", flat=True))
        )
        .distinct()
    )

    legacy_ids = (
        PaymentReceived.objects
        .filter(approved=True, service__isnull=True)
        .values_list("booking_id", flat=True)
        .distinct()
    )
    new_ids = (
        PaymentReceived.objects
        .filter(approved=True, service__isnull=False)
        .values_list("booking_id", flat=True)
        .distinct()
    )

    # pure legacy ids = legacy_ids - new_ids
    base = base.filter(id__in=legacy_ids).exclude(id__in=new_ids)

    # years from booking_date
    # Same defect as reports/views_legacy.py: .dates() yields date objects, so
    # chaining .values_list("year") raised FieldError and this endpoint
    # returned HTTP 500 on every call.
    years = list(
        base.exclude(booking_date__isnull=True)
        .dates("booking_date", "year")
    )
    years = [d.year for d in years]

    months = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]

    clients = [{
        "id": c.id,
        "name": f"{getattr(c, 'first_name', '')} {getattr(c, 'last_name', '')}".strip() or str(c)
    } for c in Client.objects.all().order_by("first_name", "last_name")]

    suppliers = [{
        "id": s.id,
        "name": getattr(s, "name", None) or str(s)
    } for s in Supplier.objects.all().order_by("name")]

    return JsonResponse({
        "years": years,
        "months": months,
        "clients": clients,
        "suppliers": suppliers,
    })


# ---------------------------
# Summary (cards only) - booking-wise legacy
# ---------------------------
@login_required
def staff_legacy_summary(request):
    user = request.user

    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    bookings = (
        Booking.objects
        .filter(
            Q(created_by=user) |
            Q(id__in=BookingService.objects.filter(assigned_to=user).values_list("booking_id", flat=True))
        )
        .select_related("client", "created_by")
        .distinct()
    )

    # pure legacy constraint
    legacy_ids = PaymentReceived.objects.filter(approved=True, service__isnull=True).values_list("booking_id", flat=True).distinct()
    new_ids = PaymentReceived.objects.filter(approved=True, service__isnull=False).values_list("booking_id", flat=True).distinct()
    bookings = bookings.filter(id__in=legacy_ids).exclude(id__in=new_ids)

    if year:
        bookings = bookings.filter(booking_date__year=year)
    if month:
        try:
            bookings = bookings.filter(booking_date__month=datetime.strptime(month, "%B").month)
        except ValueError:
            pass
    if client:
        bookings = bookings.filter(client_id=client)

    totals = {
        "sales_cash": 0.0, "sales_non_cash": 0.0,
        "purchase_cash": 0.0, "purchase_non_cash": 0.0,
        "profit_cash": 0.0, "profit_non_cash": 0.0,
        "discount": 0.0,
        "bookings": 0,
    }

    seen = 0

    for b in bookings:
        if supplier and not passes_supplier_filter(b.id, supplier):
            continue

        sales_total, sales_cash, sales_non_cash, discount_total = legacy_sales_from_payments(b.id)
        if sales_total <= 0:
            continue

        purch_total, purch_cash, purch_non_cash, _ = purchase_totals_from_services(b.id)

        profit_cash = sales_cash - purch_cash
        profit_non_cash = sales_non_cash - purch_non_cash

        totals["sales_cash"] += float(sales_cash)
        totals["sales_non_cash"] += float(sales_non_cash)
        totals["purchase_cash"] += float(purch_cash)
        totals["purchase_non_cash"] += float(purch_non_cash)
        totals["profit_cash"] += float(profit_cash)
        totals["profit_non_cash"] += float(profit_non_cash)
        totals["discount"] += float(discount_total)

        seen += 1

    totals["bookings"] = seen
    return JsonResponse({"totals": totals})


# ---------------------------
# Bookings table (booking-wise legacy + modal breakdown)
# ---------------------------
@login_required
def staff_legacy_bookings(request):
    user = request.user

    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    bookings = (
        Booking.objects
        .filter(
            Q(created_by=user) |
            Q(id__in=BookingService.objects.filter(assigned_to=user).values_list("booking_id", flat=True))
        )
        .select_related("client", "created_by")
        .order_by("-booking_date", "-id")
        .distinct()
    )

    # pure legacy constraint
    legacy_ids = PaymentReceived.objects.filter(approved=True, service__isnull=True).values_list("booking_id", flat=True).distinct()
    new_ids = PaymentReceived.objects.filter(approved=True, service__isnull=False).values_list("booking_id", flat=True).distinct()
    bookings = bookings.filter(id__in=legacy_ids).exclude(id__in=new_ids)

    if year:
        bookings = bookings.filter(booking_date__year=year)
    if month:
        try:
            bookings = bookings.filter(booking_date__month=datetime.strptime(month, "%B").month)
        except ValueError:
            pass
    if client:
        bookings = bookings.filter(client_id=client)

    data = []

    for b in bookings:
        if supplier and not passes_supplier_filter(b.id, supplier):
            continue

        sales_total, sales_cash, sales_non_cash, discount_total = legacy_sales_from_payments(b.id)
        if sales_total <= 0:
            continue

        purch_total, purch_cash, purch_non_cash, breakdown = purchase_totals_from_services(b.id)

        profit_cash = sales_cash - purch_cash
        profit_non_cash = sales_non_cash - purch_non_cash

        data.append({
            "booking_id": b.booking_id,
            "booking_date": b.booking_date.strftime("%d-%b-%Y") if b.booking_date else "",
            "client_name": (
                f"{b.client.first_name} {b.client.last_name}".strip()
                if b.client else "Unknown"
            ),
            "totals": {
                "sales_cash": float(sales_cash),
                "sales_non_cash": float(sales_non_cash),
                "purchase_cash": float(purch_cash),
                "purchase_non_cash": float(purch_non_cash),
                "profit_cash": float(profit_cash),
                "profit_non_cash": float(profit_non_cash),
                "discount": float(discount_total),
            },
            # for modal
            "purchase_breakdown": breakdown,
        })

    return JsonResponse({"data": data})
