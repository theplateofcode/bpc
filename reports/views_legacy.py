# reports/views_legacy.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional, Tuple, Dict

from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render

from bookings.models import Booking
from payments.models import PaymentReceived
from services.models import Hotel, Transfer, SightSeeing, Ticket, Visa, Insurance, Passport
from clients.models import Client
from suppliers.models import Supplier

User = get_user_model()

ZERO = Decimal("0")


def to_decimal(val) -> Decimal:
    try:
        return Decimal(str(val or 0))
    except Exception:
        return ZERO


def is_cash_mode(mode) -> bool:
    if not mode:
        return False
    return (getattr(mode, "name", "") or "").strip().lower() == "cash"


SERVICE_MODELS = (
    Hotel,
    Transfer,
    SightSeeing,
    Ticket,
    Visa,
    Insurance,
    Passport,
)


def _legacy_only_booking_qs() -> "Booking.objects":
    """
    Legacy-only booking definition:
    - Has at least 1 PaymentReceived with service IS NULL (legacy style)
    - Has NO PaymentReceived with service IS NOT NULL (new style)
    """
    legacy_ids = (
        PaymentReceived.objects
        .filter(service__isnull=True)
        .values_list("booking_id", flat=True)
        .distinct()
    )
    non_legacy_ids = (
        PaymentReceived.objects
        .filter(service__isnull=False)
        .values_list("booking_id", flat=True)
        .distinct()
    )

    return (
        Booking.objects
        .filter(id__in=legacy_ids)
        .exclude(id__in=non_legacy_ids)
    )


def _legacy_sales_totals(booking_id: int) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
    """
    Sales for legacy = sum of approved PaymentReceived.amount where service IS NULL.
    Splits into cash/non-cash by payment mode.
    Returns: total, cash, non_cash, discount_total
    """
    qs = (
        PaymentReceived.objects
        .filter(booking_id=booking_id, service__isnull=True, approved=True)
        .select_related("mode")
    )

    total = ZERO
    cash = ZERO
    discount = ZERO

    for p in qs:
        amt = to_decimal(getattr(p, "amount", 0))
        total += amt
        if is_cash_mode(getattr(p, "mode", None)):
            cash += amt
        discount += to_decimal(getattr(p, "discount", 0))

    non_cash = total - cash
    return total, cash, non_cash, discount


def _purchase_totals(booking_id: int, supplier_id: Optional[int] = None) -> Tuple[Decimal, Decimal, Decimal]:
    """
    Purchase totals = sum of purchase_amount across all service tables for this booking.
    Splits into cash/non-cash by service.mode.
    If supplier_id provided, include only records where supplier_id matches (when model has supplier_id).
    """
    total = ZERO
    cash = ZERO

    for مدل in SERVICE_MODELS:
        qs = مدل.objects.filter(booking_id=booking_id)

        # supplier filter (only if model has supplier_id field)
        if supplier_id and hasattr(مدل, "supplier_id"):
            qs = qs.filter(supplier_id=supplier_id)

        t = to_decimal(qs.aggregate(s=Sum("purchase_amount"))["s"])
        c = to_decimal(qs.filter(mode__name__iexact="Cash").aggregate(s=Sum("purchase_amount"))["s"])

        total += t
        cash += c

    non_cash = total - cash
    return total, cash, non_cash


# ---------------------------
# Page
# ---------------------------
@login_required
def owner_legacy_reports(request):
    # Put your template at: reports/templates/owner_reports/legacy.html
    return render(request, "owner_reports_legacy.html")


# ---------------------------
# Filters (dropdown data) - Legacy page
# ---------------------------
@login_required
def report_filters_data_legacy(request):
    # employees = booking.created_by on legacy bookings
    legacy_bookings = _legacy_only_booking_qs()

    employee_ids = (
        legacy_bookings
        .exclude(created_by__isnull=True)
        .values_list("created_by_id", flat=True)
        .distinct()
    )
    employees_qs = User.objects.filter(id__in=employee_ids).order_by("first_name", "username")
    employees = [{"id": u.id, "name": (u.get_full_name() or u.username)} for u in employees_qs]

    # .dates() already yields date objects, so the .values_list("year") that
    # used to be chained here raised FieldError -- "year" is not a field --
    # and this endpoint returned HTTP 500 on every call. The line below was
    # always the intended conversion.
    years = list(
        legacy_bookings
        .exclude(booking_date__isnull=True)
        .dates("booking_date", "year")
    )
    years = [d.year for d in years]

    months = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]

    client_ids = legacy_bookings.values_list("client_id", flat=True).distinct()
    clients = [{
        "id": c.id,
        "name": f"{getattr(c, 'first_name', '')} {getattr(c, 'last_name', '')}".strip() or str(c)
    } for c in Client.objects.filter(id__in=client_ids).order_by("first_name", "last_name")]

    suppliers = [{
        "id": s.id,
        "name": getattr(s, "name", None) or str(s)
    } for s in Supplier.objects.all().order_by("name")]

    return JsonResponse({
        "employees": employees,
        "years": years,
        "months": months,
        "clients": clients,
        "suppliers": suppliers,
    })


# ---------------------------
# Cards totals (Legacy booking-wise)
# ---------------------------
@login_required
def filtered_legacy_report(request):
    employee = request.GET.get("employee")  # Booking.created_by id
    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    bookings = (
        _legacy_only_booking_qs()
        .select_related("client", "created_by")
        .order_by("-booking_date", "-id")
    )

    if employee:
        bookings = bookings.filter(created_by_id=employee)
    if client:
        bookings = bookings.filter(client_id=client)
    if year:
        bookings = bookings.filter(booking_date__year=year)
    if month:
        try:
            month_num = datetime.strptime(month, "%B").month
            bookings = bookings.filter(booking_date__month=month_num)
        except ValueError:
            pass

    supplier_id = int(supplier) if supplier else None

    totals = {
        "sales_cash": 0.0, "sales_non_cash": 0.0,
        "purchase_cash": 0.0, "purchase_non_cash": 0.0,
        "profit_cash": 0.0, "profit_non_cash": 0.0,
        "discount": 0.0,
        "bookings": 0,
    }

    count = 0

    for b in bookings:
        # Sales = approved legacy payments only (service NULL)
        _, s_cash, s_non, disc = _legacy_sales_totals(b.id)

        # Purchase = supplier/service tables
        _, p_cash, p_non = _purchase_totals(b.id, supplier_id=supplier_id)

        profit_cash = s_cash - p_cash
        profit_non = s_non - p_non

        totals["sales_cash"] += float(s_cash)
        totals["sales_non_cash"] += float(s_non)
        totals["purchase_cash"] += float(p_cash)
        totals["purchase_non_cash"] += float(p_non)
        totals["profit_cash"] += float(profit_cash)
        totals["profit_non_cash"] += float(profit_non)
        totals["discount"] += float(disc)

        count += 1

    totals["bookings"] = count

    return JsonResponse({"totals": totals})


# ---------------------------
# Bookings table (Legacy booking-wise)
# ---------------------------
@login_required
def bookings_report_legacy(request):
    employee = request.GET.get("employee")
    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    bookings = (
        _legacy_only_booking_qs()
        .select_related("client", "created_by")
        .order_by("-booking_date", "-id")
    )

    if employee:
        bookings = bookings.filter(created_by_id=employee)
    if client:
        bookings = bookings.filter(client_id=client)
    if year:
        bookings = bookings.filter(booking_date__year=year)
    if month:
        try:
            month_num = datetime.strptime(month, "%B").month
            bookings = bookings.filter(booking_date__month=month_num)
        except ValueError:
            pass

    supplier_id = int(supplier) if supplier else None

    data = []

    for b in bookings:
        _, s_cash, s_non, disc = _legacy_sales_totals(b.id)
        _, p_cash, p_non = _purchase_totals(b.id, supplier_id=supplier_id)

        profit_cash = s_cash - p_cash
        profit_non = s_non - p_non

        data.append({
            "booking_id": b.booking_id,
            "booking_date": b.booking_date.strftime("%d-%b-%Y") if b.booking_date else "",
            "created_by": (b.created_by.get_full_name() or b.created_by.username) if b.created_by else "—",
            "client_name": (
                f"{b.client.first_name} {b.client.last_name}".strip()
                if b.client else "Unknown"
            ),
            "totals": {
                "sales_cash": float(s_cash),
                "sales_non_cash": float(s_non),
                "purchase_cash": float(p_cash),
                "purchase_non_cash": float(p_non),
                "profit_cash": float(profit_cash),
                "profit_non_cash": float(profit_non),
                "discount": float(disc),
            }
        })

    return JsonResponse({"data": data})