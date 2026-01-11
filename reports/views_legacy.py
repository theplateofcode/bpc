# reports/views_legacy.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Tuple

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render

from bookings.models import Booking
from payments.models import PaymentReceived
from services.models import Hotel, Transfer, SightSeeing, Ticket, Visa, Insurance, Passport
from clients.models import Client
from suppliers.models import Supplier

ZERO = Decimal("0")

SERVICE_MODELS = [Hotel, Transfer, SightSeeing, Ticket, Visa, Insurance, Passport]


def to_decimal(val) -> Decimal:
    try:
        return Decimal(str(val or 0))
    except Exception:
        return ZERO


def is_cash_mode(mode) -> bool:
    return bool(mode) and (getattr(mode, "name", "") or "").strip().lower() == "cash"


def legacy_payments():
    # Only legacy payments: approved and service is NULL
    return PaymentReceived.objects.filter(approved=True, service__isnull=True).select_related("mode")


def legacy_booking_sales(booking_id: int) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
    qs = legacy_payments().filter(booking_id=booking_id)
    if not qs.exists():
        return ZERO, ZERO, ZERO, ZERO

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


def legacy_booking_purchase(booking_id: int, supplier_id=None) -> Tuple[Decimal, Decimal, Decimal]:
    """
    Purchase from service tables, split by service-row mode.
    Supplier filter: keep only rows matching supplier_id (if provided).
    """
    total = ZERO
    cash = ZERO

    for model in SERVICE_MODELS:
        qs = model.objects.filter(booking_id=booking_id).select_related("mode")
        if supplier_id:
            # some models may not have supplier_id; guard
            try:
                qs = qs.filter(supplier_id=supplier_id)
            except Exception:
                continue

        for obj in qs:
            amt = to_decimal(getattr(obj, "purchase_amount", 0))
            total += amt
            mode = getattr(obj, "mode", None)
            if mode and (getattr(mode, "name", "") or "").strip().lower() == "cash":
                cash += amt

    non_cash = total - cash
    return total, cash, non_cash


@login_required
def owner_legacy_reports(request):
    return render(request, "owner_reports_legacy.html")


@login_required
def report_filters_data_legacy(request):
    legacy_booking_ids = legacy_payments().values_list("booking_id", flat=True).distinct()

    # employees = booking created_by for legacy
    from django.contrib.auth import get_user_model
    User = get_user_model()
    employee_ids = (
        Booking.objects.filter(id__in=legacy_booking_ids)
        .exclude(created_by__isnull=True)
        .values_list("created_by_id", flat=True)
        .distinct()
    )
    employees = [
        {"id": u.id, "name": (u.get_full_name() or u.username)}
        for u in User.objects.filter(id__in=employee_ids).order_by("first_name", "username")
    ]

    years = [
        d.year for d in Booking.objects.filter(id__in=legacy_booking_ids)
        .exclude(booking_date__isnull=True)
        .dates("booking_date", "year")
    ]

    months = [
        "January","February","March","April","May","June",
        "July","August","September","October","November","December"
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
        "employees": employees,
        "years": years,
        "months": months,
        "clients": clients,
        "suppliers": suppliers,
    })


@login_required
def legacy_booking_summary(request):
    employee = request.GET.get("employee")   # Booking.created_by
    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    legacy_booking_ids = legacy_payments().values_list("booking_id", flat=True).distinct()

    qs = (
        Booking.objects
        .filter(id__in=legacy_booking_ids)
        .select_related("client", "created_by")
        .order_by("-booking_date", "-id")
    )

    if year:
        qs = qs.filter(booking_date__year=year)
    if month:
        try:
            month_num = datetime.strptime(month, "%B").month
            qs = qs.filter(booking_date__month=month_num)
        except ValueError:
            pass
    if employee:
        qs = qs.filter(created_by_id=employee)
    if client:
        qs = qs.filter(client_id=client)

    data = []

    totals = {
        "sales_cash": 0.0, "sales_non_cash": 0.0,
        "purchase_cash": 0.0, "purchase_non_cash": 0.0,
        "profit_cash": 0.0, "profit_non_cash": 0.0,
        "discount": 0.0,
        "bookings": 0,
    }

    for b in qs:
        sales_total, sales_cash, sales_non_cash, discount = legacy_booking_sales(b.id)
        if sales_total <= 0:
            continue

        purch_total, purch_cash, purch_non_cash = legacy_booking_purchase(b.id, supplier_id=supplier)

        profit_cash = sales_cash - purch_cash
        profit_non_cash = sales_non_cash - purch_non_cash

        data.append({
            "booking_id": b.booking_id,
            "booking_date": b.booking_date.strftime("%d-%b-%Y") if b.booking_date else "",
            "created_by": (b.created_by.get_full_name() or b.created_by.username) if b.created_by else "—",
            "client_name": (
                f"{b.client.first_name} {b.client.last_name}".strip()
                if b.client else "Unknown"
            ),
            "sales_cash": float(sales_cash),
            "sales_non_cash": float(sales_non_cash),
            "purchase_cash": float(purch_cash),
            "purchase_non_cash": float(purch_non_cash),
            "profit_cash": float(profit_cash),
            "profit_non_cash": float(profit_non_cash),
            "discount": float(discount),
        })

        totals["sales_cash"] += float(sales_cash)
        totals["sales_non_cash"] += float(sales_non_cash)
        totals["purchase_cash"] += float(purch_cash)
        totals["purchase_non_cash"] += float(purch_non_cash)
        totals["profit_cash"] += float(profit_cash)
        totals["profit_non_cash"] += float(profit_non_cash)
        totals["discount"] += float(discount)

    totals["bookings"] = len(data)

    return JsonResponse({"totals": totals, "data": data})
