# reports/views_legacy.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict, Tuple

from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render

from bookings.models import Booking, BookingService
from payments.models import PaymentReceived
from services.models import (
    ServiceList,
    Hotel, Transfer, SightSeeing, Ticket, Visa, Insurance, Passport
)

# If your Client/Supplier are in different apps, change imports accordingly
from clients.models import Client
from suppliers.models import Supplier


# ---------------------------
# Access control (Owner/Admin)
# ---------------------------
def is_owner_or_admin(user):
    return user.is_authenticated and getattr(user, "role", "") in ["OWNER", "ADMIN"]


# ---------------------------
# Helpers
# ---------------------------
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


SERVICE_MODEL_MAP = {
    "hotel": Hotel,
    "transfer": Transfer,
    "sightseeing": SightSeeing,
    "ticket": Ticket,
    "visa": Visa,
    "insurance": Insurance,
    "passport": Passport,
}


def _svc_code(service_obj) -> str:
    return (
        (getattr(service_obj, "code", "") or getattr(service_obj, "name", "") or "")
        .strip()
        .lower()
        .replace(" ", "")
    )


# ---------------------------
# Purchase totals (supplier-side service tables)
# ---------------------------
def _svc_purchase_totals(booking_id: int, service_code: str) -> Tuple[Decimal, Decimal, Decimal]:
    model = SERVICE_MODEL_MAP.get(service_code)
    if not model:
        return ZERO, ZERO, ZERO

    total = to_decimal(model.objects.filter(booking_id=booking_id).aggregate(s=Sum("purchase_amount"))["s"])
    cash = to_decimal(
        model.objects.filter(booking_id=booking_id, mode__name__iexact="Cash").aggregate(s=Sum("purchase_amount"))["s"]
    )
    non_cash = total - cash
    return total, cash, non_cash


# ---------------------------
# Sales totals (customer-side: approved PaymentReceived cashflow)
# ---------------------------
def _svc_sales_totals_from_payments(booking_id: int, service_id: int) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
    qs = (
        PaymentReceived.objects
        .filter(booking_id=booking_id, service_id=service_id, approved=True)
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
        if is_cash_mode(p.mode):
            sales_cash += amt
        discount_total += to_decimal(getattr(p, "discount", 0))

    sales_non_cash = sales_total - sales_cash
    return sales_total, sales_cash, sales_non_cash, discount_total


# ---------------------------
# Pages
# ---------------------------
@login_required
@user_passes_test(is_owner_or_admin)
def owner_legacy_reports(request):
    # Template lives under reports/templates/reports/...
    return render(request, "owner_reports_legacy.html")


@login_required
@user_passes_test(is_owner_or_admin)
def report_filters_data_legacy(request):
    services = list(ServiceList.objects.all().order_by("name").values_list("name", flat=True))

    # employees from BookingService.assigned_to
    user_ids = (
        BookingService.objects
        .exclude(assigned_to__isnull=True)
        .values_list("assigned_to_id", flat=True)
        .distinct()
    )
    # if your User model is custom, keep it simple by using BookingService.assigned_to directly in UI;
    # otherwise you can import get_user_model() and build names.
    from django.contrib.auth import get_user_model
    User = get_user_model()
    employees_qs = User.objects.filter(id__in=user_ids).order_by("first_name", "username")
    employees = [{"id": u.id, "name": (u.get_full_name() or u.username)} for u in employees_qs]

    years = list(
        Booking.objects
        .exclude(booking_date__isnull=True)
        .dates("booking_date", "year")
        .values_list("year", flat=True)
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


@login_required
@user_passes_test(is_owner_or_admin)
def filtered_legacy_report(request):
    service = request.GET.get("service")      # ServiceList.name
    employee = request.GET.get("employee")    # BookingService.assigned_to id
    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    assignments = (
        BookingService.objects
        .select_related("booking", "booking__client", "service", "assigned_to")
        .filter(
            booking_id__in=PaymentReceived.objects.filter(approved=True)
            .values_list("booking_id", flat=True).distinct()
        )
    )

    if year:
        assignments = assignments.filter(booking__booking_date__year=year)
    if month:
        try:
            month_num = datetime.strptime(month, "%B").month
            assignments = assignments.filter(booking__booking_date__month=month_num)
        except ValueError:
            pass
    if employee:
        assignments = assignments.filter(assigned_to_id=employee)
    if client:
        assignments = assignments.filter(booking__client_id=client)
    if service:
        assignments = assignments.filter(service__name=service)

    results = {
        "totals": {
            "sales_cash": 0.0, "sales_non_cash": 0.0,
            "purchase_cash": 0.0, "purchase_non_cash": 0.0,
            "profit_cash": 0.0, "profit_non_cash": 0.0,
            "discount": 0.0,
            "gst": 0.0, "tcs": 0.0,  # keep for JS compatibility
            "bookings": 0,
        },
        "service_summary": {},
        "employee_summary": {},
    }

    seen_booking_ids = set()

    for a in assignments:
        booking = a.booking
        svc = a.service
        code = _svc_code(svc)

        # supplier filter (only if the underlying model has supplier_id)
        model = SERVICE_MODEL_MAP.get(code)
        if supplier and model:
            if not model.objects.filter(booking_id=booking.id, supplier_id=supplier).exists():
                continue

        sales_total, sales_cash, sales_non_cash, discount_total = _svc_sales_totals_from_payments(
            booking_id=booking.id,
            service_id=svc.id,
        )
        if sales_total <= 0:
            continue

        seen_booking_ids.add(booking.id)

        _, purch_cash, purch_non_cash = _svc_purchase_totals(booking.id, code)

        profit_cash = sales_cash - purch_cash
        profit_non_cash = sales_non_cash - purch_non_cash

        # totals
        results["totals"]["sales_cash"] += float(sales_cash)
        results["totals"]["sales_non_cash"] += float(sales_non_cash)
        results["totals"]["purchase_cash"] += float(purch_cash)
        results["totals"]["purchase_non_cash"] += float(purch_non_cash)
        results["totals"]["profit_cash"] += float(profit_cash)
        results["totals"]["profit_non_cash"] += float(profit_non_cash)
        results["totals"]["discount"] += float(discount_total)

        # service summary
        sname = svc.name
        sdata = results["service_summary"].setdefault(sname, {
            "sales_cash": 0.0, "sales_non_cash": 0.0,
            "purchase_cash": 0.0, "purchase_non_cash": 0.0,
            "profit_cash": 0.0, "profit_non_cash": 0.0,
            "discount": 0.0,
            "gst": 0.0, "tcs": 0.0,
        })
        sdata["sales_cash"] += float(sales_cash)
        sdata["sales_non_cash"] += float(sales_non_cash)
        sdata["purchase_cash"] += float(purch_cash)
        sdata["purchase_non_cash"] += float(purch_non_cash)
        sdata["profit_cash"] += float(profit_cash)
        sdata["profit_non_cash"] += float(profit_non_cash)
        sdata["discount"] += float(discount_total)

        # employee summary
        emp = a.assigned_to
        emp_name = (emp.get_full_name() or emp.username) if emp else "Unassigned"
        edata = results["employee_summary"].setdefault(emp_name, {
            "sales_cash": 0.0, "sales_non_cash": 0.0,
            "purchase_cash": 0.0, "purchase_non_cash": 0.0,
            "profit_cash": 0.0, "profit_non_cash": 0.0,
            "discount": 0.0,
            "gst": 0.0, "tcs": 0.0,
        })
        edata["sales_cash"] += float(sales_cash)
        edata["sales_non_cash"] += float(sales_non_cash)
        edata["purchase_cash"] += float(purch_cash)
        edata["purchase_non_cash"] += float(purch_non_cash)
        edata["profit_cash"] += float(profit_cash)
        edata["profit_non_cash"] += float(profit_non_cash)
        edata["discount"] += float(discount_total)

    results["totals"]["bookings"] = len(seen_booking_ids)

    def add_total(block: Dict):
        totals = {k: 0.0 for k in [
            "sales_cash", "sales_non_cash",
            "purchase_cash", "purchase_non_cash",
            "profit_cash", "profit_non_cash",
            "discount", "gst", "tcs",
        ]}
        for v in block.values():
            for k in totals:
                totals[k] += v.get(k, 0.0)
        block["TOTAL"] = totals

    add_total(results["service_summary"])
    add_total(results["employee_summary"])

    return JsonResponse(results)


@login_required
@user_passes_test(is_owner_or_admin)
def bookings_report_legacy(request):
    service = request.GET.get("service")
    employee = request.GET.get("employee")
    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    bookings = (
        Booking.objects
        .filter(
            id__in=PaymentReceived.objects.filter(approved=True)
            .values_list("booking_id", flat=True).distinct()
        )
        .select_related("client", "created_by")
        .order_by("-booking_date", "-id")
    )

    if year:
        bookings = bookings.filter(booking_date__year=year)
    if month:
        try:
            month_num = datetime.strptime(month, "%B").month
            bookings = bookings.filter(booking_date__month=month_num)
        except ValueError:
            pass
    if client:
        bookings = bookings.filter(client_id=client)

    data = []

    for booking in bookings:
        bs_qs = BookingService.objects.filter(booking_id=booking.id).select_related("service", "assigned_to")

        if employee:
            bs_qs = bs_qs.filter(assigned_to_id=employee)
        if service:
            bs_qs = bs_qs.filter(service__name=service)

        services_data = []

        book_sales_cash = ZERO
        book_sales_non_cash = ZERO
        book_purchase_cash = ZERO
        book_purchase_non_cash = ZERO
        book_profit_cash = ZERO
        book_profit_non_cash = ZERO
        book_discount = ZERO

        for bs in bs_qs:
            svc = bs.service
            code = _svc_code(svc)

            model = SERVICE_MODEL_MAP.get(code)
            if supplier and model:
                if not model.objects.filter(booking_id=booking.id, supplier_id=supplier).exists():
                    continue

            sales_total, sales_cash, sales_non_cash, discount_total = _svc_sales_totals_from_payments(
                booking_id=booking.id,
                service_id=svc.id,
            )
            if sales_total <= 0:
                continue

            _, purch_cash, purch_non_cash = _svc_purchase_totals(booking.id, code)

            profit_cash = sales_cash - purch_cash
            profit_non_cash = sales_non_cash - purch_non_cash
            profit_total = profit_cash + profit_non_cash

            # label
            if sales_cash > 0 and sales_non_cash > 0:
                mode_label = "Mixed"
            elif sales_cash > 0:
                mode_label = "Cash"
            else:
                mode_label = "Non-Cash"

            services_data.append({
                "service": svc.name,
                "mode": mode_label,

                # fields your JS already expects in the modal
                "sales": float(sales_cash + sales_non_cash),
                "purchase": float(purch_cash + purch_non_cash),
                "profit": float(profit_total),

                # optional splits (safe to keep)
                "sales_cash": float(sales_cash),
                "sales_non_cash": float(sales_non_cash),
                "purchase_cash": float(purch_cash),
                "purchase_non_cash": float(purch_non_cash),
                "profit_cash": float(profit_cash),
                "profit_non_cash": float(profit_non_cash),

                "discount": float(discount_total),
                "entered_by": (booking.created_by.get_full_name() or booking.created_by.username) if booking.created_by else "—",
            })

            book_sales_cash += sales_cash
            book_sales_non_cash += sales_non_cash
            book_purchase_cash += purch_cash
            book_purchase_non_cash += purch_non_cash
            book_profit_cash += profit_cash
            book_profit_non_cash += profit_non_cash
            book_discount += discount_total

        if not services_data:
            continue

        data.append({
            "booking_id": booking.booking_id,
            "booking_date": booking.booking_date.strftime("%d-%b-%Y") if booking.booking_date else "",
            "created_by": (booking.created_by.get_full_name() or booking.created_by.username) if booking.created_by else "—",
            "client_name": (
                f"{booking.client.first_name} {booking.client.last_name}".strip()
                if booking.client else "Unknown"
            ),
            "services": services_data,
            "totals": {
                "sales_cash": float(book_sales_cash),
                "sales_non_cash": float(book_sales_non_cash),
                "purchase_cash": float(book_purchase_cash),
                "purchase_non_cash": float(book_purchase_non_cash),
                "profit_cash": float(book_profit_cash),
                "profit_non_cash": float(book_profit_non_cash),
                "discount": float(book_discount),

                # legacy keeps keys so your JS doesn’t break
                "gst": 0.0,
                "tcs": 0.0,
            },
        })

    return JsonResponse({"data": data})
