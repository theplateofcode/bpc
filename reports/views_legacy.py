# reports/views_legacy.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict, Iterable, Tuple
from itertools import chain
from collections import defaultdict

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render

from bookings.models import Booking
from payments.models import PaymentReceived
from suppliers.models import Supplier
from services.models import ServiceList, Hotel, Transfer, SightSeeing, Ticket, Visa, Insurance, Passport
from clients.models import Client

User = get_user_model()

ZERO = Decimal("0")


# ---------------------------
# Access control (match your owner report policy)
# ---------------------------
def superuser_only(user):
    return user.is_superuser


# ---------------------------
# Helpers
# ---------------------------
def to_decimal(val) -> Decimal:
    try:
        return Decimal(str(val or 0))
    except Exception:
        return ZERO


def is_cash_mode_name(name: str) -> bool:
    return (name or "").strip().lower() == "cash"


def is_cash_mode(mode) -> bool:
    if not mode:
        return False
    return is_cash_mode_name(getattr(mode, "name", "") or "")


SERVICE_MODEL_MAP = {
    "hotel": Hotel,
    "transfer": Transfer,
    "sightseeing": SightSeeing,
    "ticket": Ticket,
    "visa": Visa,
    "insurance": Insurance,
    "passport": Passport,
}

SERVICE_LABELS = {
    "hotel": "Hotel",
    "transfer": "Transfer",
    "sightseeing": "Sightseeing",
    "ticket": "Ticket",
    "visa": "Visa",
    "insurance": "Insurance",
    "passport": "Passport",
}


def _svc_code(service_obj) -> str:
    return (
        (getattr(service_obj, "code", "") or getattr(service_obj, "name", "") or "")
        .strip()
        .lower()
        .replace(" ", "")
    )


def iter_booking_service_rows(booking_id: int):
    """
    Yields normalized rows from service tables for this booking:
    {
      "service_code": "hotel",
      "service_name": "Hotel",
      "purchase_amount": Decimal,
      "mode_name": "Cash" or "Non-Cash",
      "supplier_id": <int or None>,
    }
    """
    # Only purchase and mode are required for legacy purchase-cashflow split
    # (No sales attribution here, since legacy payments were booking-level.)
    for code, model in SERVICE_MODEL_MAP.items():
        qs = model.objects.filter(booking_id=booking_id).values(
            "purchase_amount", "mode__name", "supplier_id"
        )
        for r in qs:
            yield {
                "service_code": code,
                "service_name": SERVICE_LABELS.get(code, code.title()),
                "purchase_amount": to_decimal(r.get("purchase_amount")),
                "mode_name": r.get("mode__name") or "",
                "supplier_id": r.get("supplier_id"),
            }


def booking_purchase_totals(booking_id: int) -> Tuple[Decimal, Decimal, Decimal]:
    """
    Purchase totals derived from service tables (supplier-side).
    Returns: (purchase_total, purchase_cash, purchase_non_cash)
    """
    total = ZERO
    cash = ZERO
    for row in iter_booking_service_rows(booking_id):
        amt = row["purchase_amount"]
        total += amt
        if is_cash_mode_name(row["mode_name"]):
            cash += amt
    non_cash = total - cash
    return total, cash, non_cash


def booking_sales_totals_from_payments(booking_id: int) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
    """
    LEGACY sales: approved PaymentReceived per booking, ignoring service.
    Returns: (sales_total, sales_cash, sales_non_cash, discount_total)
    """
    qs = (
        PaymentReceived.objects
        .filter(booking_id=booking_id, approved=True)
        .select_related("mode")
    )

    sales_total = ZERO
    sales_cash = ZERO
    discount_total = ZERO

    for p in qs:
        amt = to_decimal(getattr(p, "amount", 0))
        sales_total += amt
        if is_cash_mode(p.mode):
            sales_cash += amt
        discount_total += to_decimal(getattr(p, "discount", 0))

    sales_non_cash = sales_total - sales_cash
    return sales_total, sales_cash, sales_non_cash, discount_total


def booking_matches_supplier(booking_id: int, supplier_id: int) -> bool:
    if not supplier_id:
        return True
    for row in iter_booking_service_rows(booking_id):
        if row["supplier_id"] == int(supplier_id):
            return True
    return False


# ---------------------------
# Pages
# ---------------------------
@user_passes_test(superuser_only)
def owner_legacy_reports(request):
    # Your file is: reports/templates/owner_reports/legacy.html
    return render(request, "owner_reports/legacy.html")


# ---------------------------
# Filters (dropdown data)
# ---------------------------
@user_passes_test(superuser_only)
def report_filters_data_legacy(request):
    # Services list (keep for UI even if legacy report doesn't allocate sales by service)
    services = list(ServiceList.objects.all().order_by("name").values_list("name", flat=True))

    # Employees: booking creators (legacy = booking-wise)
    employees_qs = User.objects.filter(
        id__in=Booking.objects.exclude(created_by__isnull=True).values_list("created_by_id", flat=True).distinct()
    ).order_by("first_name", "username")
    employees = [{"id": u.id, "name": (u.get_full_name() or u.username)} for u in employees_qs]

    # Years/months from Booking.booking_date (not service dates)
    years = list(
        Booking.objects
        .exclude(booking_date__isnull=True)
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
        "services": services,
        "employees": employees,
        "years": years,
        "months": months,
        "clients": clients,
        "suppliers": suppliers,
    })


# ---------------------------
# Filtered Report (Cards + summaries)
# LEGACY = BOOKING-WISE. We do NOT attribute booking-level sales to services.
# ---------------------------
@user_passes_test(superuser_only)
def filtered_legacy_report(request):
    # Keep params for UI compatibility
    # service filter is accepted but legacy logic is booking-wise;
    # we only use it for *purchase-side* filtering if you really want,
    # otherwise it will not affect sales.
    service = request.GET.get("service")      # ServiceList.name (optional)
    employee = request.GET.get("employee")    # Booking.created_by id (legacy)
    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    bookings = Booking.objects.all().select_related("client", "created_by")

    if client:
        bookings = bookings.filter(client_id=client)
    if employee:
        bookings = bookings.filter(created_by_id=employee)
    if year:
        bookings = bookings.filter(booking_date__year=year)
    if month:
        try:
            month_num = datetime.strptime(month, "%B").month
            bookings = bookings.filter(booking_date__month=month_num)
        except ValueError:
            pass

    # Supplier filter must check service tables
    if supplier:
        supplier_id = int(supplier)
        bookings = [b for b in bookings if booking_matches_supplier(b.id, supplier_id)]
    else:
        bookings = list(bookings)

    # Optional: service filter (purchase-side only).
    # If you do NOT want this behavior, delete this block.
    if service:
        # Map service.name -> service_code using ServiceList
        svc_obj = ServiceList.objects.filter(name=service).first()
        svc_code = _svc_code(svc_obj) if svc_obj else ""
        if svc_code in SERVICE_MODEL_MAP:
            filtered = []
            model = SERVICE_MODEL_MAP[svc_code]
            for b in bookings:
                if model.objects.filter(booking_id=b.id).exists():
                    filtered.append(b)
            bookings = filtered

    results = {
        "totals": {
            "sales_cash": 0.0, "sales_non_cash": 0.0,
            "purchase_cash": 0.0, "purchase_non_cash": 0.0,
            "profit_cash": 0.0, "profit_non_cash": 0.0,
            "discount": 0.0,
            "gst": 0.0, "tcs": 0.0,  # legacy: keep keys for JS compatibility
            "bookings": len(bookings),
        },
        # service_summary is not meaningful for sales in legacy; we keep purchase-only rows.
        "service_summary": {},
        # employee_summary is meaningful booking-wise
        "employee_summary": {},
    }

    # Purchase-only service summary buckets
    svc_summary = defaultdict(lambda: {
        "sales_cash": 0.0, "sales_non_cash": 0.0,           # kept as 0 to avoid fake allocation
        "purchase_cash": 0.0, "purchase_non_cash": 0.0,
        "profit_cash": 0.0, "profit_non_cash": 0.0,         # kept as 0 to avoid fake allocation
        "discount": 0.0,
        "gst": 0.0, "tcs": 0.0,
    })

    emp_summary = defaultdict(lambda: {
        "sales_cash": 0.0, "sales_non_cash": 0.0,
        "purchase_cash": 0.0, "purchase_non_cash": 0.0,
        "profit_cash": 0.0, "profit_non_cash": 0.0,
        "discount": 0.0,
        "gst": 0.0, "tcs": 0.0,
    })

    for b in bookings:
        sales_total, sales_cash, sales_non_cash, discount_total = booking_sales_totals_from_payments(b.id)
        purch_total, purch_cash, purch_non_cash = booking_purchase_totals(b.id)

        profit_cash = sales_cash - purch_cash
        profit_non_cash = sales_non_cash - purch_non_cash

        results["totals"]["sales_cash"] += float(sales_cash)
        results["totals"]["sales_non_cash"] += float(sales_non_cash)
        results["totals"]["purchase_cash"] += float(purch_cash)
        results["totals"]["purchase_non_cash"] += float(purch_non_cash)
        results["totals"]["profit_cash"] += float(profit_cash)
        results["totals"]["profit_non_cash"] += float(profit_non_cash)
        results["totals"]["discount"] += float(discount_total)

        # Employee summary (booking-wise)
        emp = b.created_by
        emp_name = (emp.get_full_name() or emp.username) if emp else "Unknown"
        emp_summary[emp_name]["sales_cash"] += float(sales_cash)
        emp_summary[emp_name]["sales_non_cash"] += float(sales_non_cash)
        emp_summary[emp_name]["purchase_cash"] += float(purch_cash)
        emp_summary[emp_name]["purchase_non_cash"] += float(purch_non_cash)
        emp_summary[emp_name]["profit_cash"] += float(profit_cash)
        emp_summary[emp_name]["profit_non_cash"] += float(profit_non_cash)
        emp_summary[emp_name]["discount"] += float(discount_total)

        # Service summary (purchase-only, NO sales attribution)
        for row in iter_booking_service_rows(b.id):
            svc_name = row["service_name"]
            amt = row["purchase_amount"]
            if is_cash_mode_name(row["mode_name"]):
                svc_summary[svc_name]["purchase_cash"] += float(amt)
            else:
                svc_summary[svc_name]["purchase_non_cash"] += float(amt)

    # finalize blocks + TOTAL rows
    results["employee_summary"] = dict(emp_summary)
    results["service_summary"] = dict(svc_summary)

    def add_total(block: Dict[str, Dict[str, float]]):
        totals = {k: 0.0 for k in [
            "sales_cash", "sales_non_cash",
            "purchase_cash", "purchase_non_cash",
            "profit_cash", "profit_non_cash",
            "discount", "gst", "tcs",
        ]}
        for v in block.values():
            for k in totals:
                totals[k] += float(v.get(k, 0.0))
        block["TOTAL"] = totals

    add_total(results["employee_summary"])
    add_total(results["service_summary"])

    return JsonResponse(results)


# ---------------------------
# Bookings Report (Client Bookings Summary) - LEGACY BOOKING-WISE
# This is what will fix "154" vs "546": no PaymentReceived gating, no BookingService gating.
# ---------------------------
@user_passes_test(superuser_only)
def bookings_report_legacy(request):
    service = request.GET.get("service")       # optional purchase-side filter only
    employee = request.GET.get("employee")     # Booking.created_by id
    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    bookings = Booking.objects.all().select_related("client", "created_by").order_by("-booking_date", "-id")

    if client:
        bookings = bookings.filter(client_id=client)
    if employee:
        bookings = bookings.filter(created_by_id=employee)
    if year:
        bookings = bookings.filter(booking_date__year=year)
    if month:
        try:
            month_num = datetime.strptime(month, "%B").month
            bookings = bookings.filter(booking_date__month=month_num)
        except ValueError:
            pass

    # supplier filter via service rows
    if supplier:
        supplier_id = int(supplier)
        bookings = [b for b in bookings if booking_matches_supplier(b.id, supplier_id)]
    else:
        bookings = list(bookings)

    # Optional service filter (purchase-side only)
    if service:
        svc_obj = ServiceList.objects.filter(name=service).first()
        svc_code = _svc_code(svc_obj) if svc_obj else ""
        if svc_code in SERVICE_MODEL_MAP:
            model = SERVICE_MODEL_MAP[svc_code]
            bookings = [b for b in bookings if model.objects.filter(booking_id=b.id).exists()]

    data = []

    for b in bookings:
        sales_total, sales_cash, sales_non_cash, discount_total = booking_sales_totals_from_payments(b.id)
        purch_total, purch_cash, purch_non_cash = booking_purchase_totals(b.id)

        profit_cash = sales_cash - purch_cash
        profit_non_cash = sales_non_cash - purch_non_cash

        # Legacy table in your JS expects services[] for modal.
        # We are booking-wise, so provide ONE synthetic row ("Booking") that is truthful.
        services_data = [{
            "service": "Booking",
            "mode": "Mixed" if (sales_cash > 0 and sales_non_cash > 0) else ("Cash" if sales_cash > 0 else "Non-Cash"),
            "sales": float(sales_total),
            "purchase": float(purch_total),
            "profit": float(profit_cash + profit_non_cash),
            "entered_by": (b.created_by.get_full_name() or b.created_by.username) if b.created_by else "—",
        }]

        data.append({
            "booking_id": b.booking_id,
            "booking_date": b.booking_date.strftime("%d-%b-%Y") if b.booking_date else "",
            "created_by": (b.created_by.get_full_name() or b.created_by.username) if b.created_by else "—",
            "client_name": (
                f"{getattr(b.client, 'first_name', '')} {getattr(b.client, 'last_name', '')}".strip()
                if b.client else "Unknown"
            ),
            "services": services_data,
            "totals": {
                "sales_cash": float(sales_cash),
                "sales_non_cash": float(sales_non_cash),
                "purchase_cash": float(purch_cash),
                "purchase_non_cash": float(purch_non_cash),
                "profit_cash": float(profit_cash),
                "profit_non_cash": float(profit_non_cash),
                "discount": float(discount_total),
                "gst": 0.0,
                "tcs": 0.0,
            },
        })

    return JsonResponse({"data": data})
