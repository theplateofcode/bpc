from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict, Tuple

from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render

from bookings.models import Booking, BookingService
from payments.models import PaymentReceived
from services.models import Hotel, Transfer, SightSeeing, Ticket, Visa, Insurance, Passport

User = get_user_model()

GST_RATE = Decimal("0.18")
TCS_RATE = Decimal("0.05")


# ---------------------------
# Small utils
# ---------------------------

def to_decimal(val) -> Decimal:
    try:
        return Decimal(str(val or 0))
    except Exception:
        return Decimal("0")


def is_cash_mode(mode) -> bool:
    if not mode or not getattr(mode, "name", None):
        return False
    return mode.name.strip().lower() == "cash"


# ---------------------------
# Service mapping
# ---------------------------

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
# Purchase totals (supplier-side) - per booking + service_code
# ---------------------------

def _svc_purchase_totals(booking_id: int, service_code: str) -> Tuple[Decimal, Decimal, Decimal]:
    model = SERVICE_MODEL_MAP.get(service_code)
    z = Decimal("0")
    if not model:
        return z, z, z

    total = model.objects.filter(booking_id=booking_id).aggregate(s=Sum("purchase_amount"))["s"] or z
    cash = (
        model.objects.filter(booking_id=booking_id, mode__name__iexact="Cash")
        .aggregate(s=Sum("purchase_amount"))["s"]
        or z
    )
    non_cash = to_decimal(total) - to_decimal(cash)
    return to_decimal(total), to_decimal(cash), to_decimal(non_cash)


# ---------------------------
# Sales totals (customer-side actuals) - per booking + service_id
# NEW SYSTEM ONLY => service_id IS NOT NULL
# ---------------------------

def _svc_sales_totals_from_payments(booking_id: int, service_id: int) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
    payments = (
        PaymentReceived.objects
        .filter(booking_id=booking_id, service_id=service_id, approved=True)
        .select_related("mode")
    )

    if not payments.exists():
        z = Decimal("0")
        return z, z, z, z

    sales_total = sum(to_decimal(p.amount) for p in payments)
    sales_cash = sum(to_decimal(p.amount) for p in payments if is_cash_mode(p.mode))
    sales_non_cash = sales_total - sales_cash
    discount_total = sum(to_decimal(p.discount) for p in payments)

    return to_decimal(sales_total), to_decimal(sales_cash), to_decimal(sales_non_cash), to_decimal(discount_total)


# ---------------------------
# GST/TCS from service rows (your rules)
# ---------------------------

def _svc_tax_totals_from_service_rows(booking_id: int, service_code: str) -> Tuple[Decimal, Decimal]:
    model = SERVICE_MODEL_MAP.get(service_code)
    z = Decimal("0")
    if not model:
        return z, z

    qs = model.objects.filter(booking_id=booking_id).select_related("mode")

    gst_total = Decimal("0")
    tcs_total = Decimal("0")

    for obj in qs:
        mode = getattr(obj, "mode", None)
        row_is_cash = bool(mode and getattr(mode, "name", "").strip().lower() == "cash")

        sales_amount = to_decimal(getattr(obj, "sales_amount", 0))
        purchase_amount = to_decimal(getattr(obj, "purchase_amount", 0))
        base_amount = sales_amount - purchase_amount

        # GST
        if service_code == "ticket":
            gst = base_amount * GST_RATE
        else:
            gst = Decimal("0") if row_is_cash else base_amount * GST_RATE

        gst_total += gst

        # TCS
        if service_code in {"hotel", "transfer", "sightseeing"}:
            travel_type = (getattr(obj, "travel_type", "") or "").strip().lower()
            is_international = travel_type == "international"
            if (not row_is_cash) and is_international:
                tcs_total += (sales_amount * TCS_RATE)

    return to_decimal(gst_total), to_decimal(tcs_total)


# ---------------------------
# Booking gate (NEW SYSTEM ONLY)
# Requires:
# - BookingService exists
# - No pending payments for those services
# - Every service has >= 1 approved payment (service_id not null)
# ---------------------------

def booking_all_services_fully_approved(booking_id: int) -> bool:
    service_ids = list(
        BookingService.objects
        .filter(booking_id=booking_id)
        .values_list("service_id", flat=True)
        .distinct()
    )
    if not service_ids:
        return False

    # any pending for any assigned service => not eligible
    if PaymentReceived.objects.filter(
        booking_id=booking_id,
        service_id__in=service_ids,
        approved=False
    ).exists():
        return False

    # each service must have at least 1 approved payment (new system)
    for sid in service_ids:
        if not PaymentReceived.objects.filter(
            booking_id=booking_id,
            service_id=sid,
            approved=True
        ).exists():
            return False

    return True


# ---------------------------
# Page
# ---------------------------

@login_required
def owner_actual_reports(request):
    return render(request, "owner_reports_actual.html")


# ---------------------------
# Filtered Report (Cards + Summaries) - NEW SYSTEM ONLY
# Employee summary is service-attributed via BookingService.assigned_to
# ---------------------------

@login_required
def filtered_actual_report(request):
    service = request.GET.get("service")      # ServiceList.name
    employee = request.GET.get("employee")    # assigned_to id
    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    # Only consider bookings that have approved NEW payments (service_id NOT NULL)
    approved_new_booking_ids = (
        PaymentReceived.objects
        .filter(approved=True, service__isnull=False)
        .values_list("booking_id", flat=True)
        .distinct()
    )

    assignments = (
        BookingService.objects
        .select_related("booking", "booking__client", "booking__created_by", "service", "assigned_to")
        .filter(booking_id__in=approved_new_booking_ids)
    )

    # Booking-level filters
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

    # Service-level filter
    if service:
        assignments = assignments.filter(service__name=service)

    results = {
        "totals": {
            "sales_cash": 0.0, "sales_non_cash": 0.0,
            "purchase_cash": 0.0, "purchase_non_cash": 0.0,
            "profit_cash": 0.0, "profit_non_cash": 0.0,
            "discount": 0.0,
            "gst": 0.0, "tcs": 0.0,
            "bookings": 0,
        },
        "service_summary": {},
        "employee_summary": {},
    }

    seen_booking_ids = set()

    for a in assignments:
        booking = a.booking
        svc = a.service
        service_code = _svc_code(svc)

        # Gate: only include bookings that are fully approved in NEW system
        if not booking_all_services_fully_approved(booking.id):
            continue

        # Supplier filter: service-table supplier
        model = SERVICE_MODEL_MAP.get(service_code)
        if supplier and model:
            if not model.objects.filter(booking_id=booking.id, supplier_id=supplier).exists():
                continue

        # Actual sales per service from NEW payments only
        sales_total, sales_cash, sales_non_cash, discount_total = _svc_sales_totals_from_payments(
            booking_id=booking.id,
            service_id=svc.id
        )
        if sales_total <= 0:
            continue

        seen_booking_ids.add(booking.id)

        # Purchase per service from service rows
        _, purch_cash, purch_non_cash = _svc_purchase_totals(booking.id, service_code)

        # Taxes per service from service rows
        gst_amt, tcs_amt = _svc_tax_totals_from_service_rows(booking.id, service_code)

        # Non-cash sales net of TCS
        sales_non_cash_net = sales_non_cash - tcs_amt

        # Rule: no GST in cash profit; GST subtract only from non-cash bucket
        profit_cash = sales_cash - purch_cash
        profit_non_cash = (sales_non_cash_net - purch_non_cash) - gst_amt

        # Totals (cards)
        results["totals"]["sales_cash"] += float(sales_cash)
        results["totals"]["sales_non_cash"] += float(sales_non_cash_net)
        results["totals"]["purchase_cash"] += float(purch_cash)
        results["totals"]["purchase_non_cash"] += float(purch_non_cash)
        results["totals"]["profit_cash"] += float(profit_cash)
        results["totals"]["profit_non_cash"] += float(profit_non_cash)
        results["totals"]["discount"] += float(discount_total)
        results["totals"]["gst"] += float(gst_amt)
        results["totals"]["tcs"] += float(tcs_amt)

        # Service summary
        sname = svc.name
        sdata = results["service_summary"].setdefault(sname, {
            "sales_cash": 0.0, "sales_non_cash": 0.0,
            "purchase_cash": 0.0, "purchase_non_cash": 0.0,
            "profit_cash": 0.0, "profit_non_cash": 0.0,
            "discount": 0.0,
            "gst": 0.0, "tcs": 0.0,
        })
        sdata["sales_cash"] += float(sales_cash)
        sdata["sales_non_cash"] += float(sales_non_cash_net)
        sdata["purchase_cash"] += float(purch_cash)
        sdata["purchase_non_cash"] += float(purch_non_cash)
        sdata["profit_cash"] += float(profit_cash)
        sdata["profit_non_cash"] += float(profit_non_cash)
        sdata["discount"] += float(discount_total)
        sdata["gst"] += float(gst_amt)
        sdata["tcs"] += float(tcs_amt)

        # Employee summary (service attribution = BookingService.assigned_to)
        emp_name = a.assigned_to.get_full_name() or a.assigned_to.username
        edata = results["employee_summary"].setdefault(emp_name, {
            "sales_cash": 0.0, "sales_non_cash": 0.0,
            "purchase_cash": 0.0, "purchase_non_cash": 0.0,
            "profit_cash": 0.0, "profit_non_cash": 0.0,
            "discount": 0.0,
            "gst": 0.0, "tcs": 0.0,
        })
        edata["sales_cash"] += float(sales_cash)
        edata["sales_non_cash"] += float(sales_non_cash_net)
        edata["purchase_cash"] += float(purch_cash)
        edata["purchase_non_cash"] += float(purch_non_cash)
        edata["profit_cash"] += float(profit_cash)
        edata["profit_non_cash"] += float(profit_non_cash)
        edata["discount"] += float(discount_total)
        edata["gst"] += float(gst_amt)
        edata["tcs"] += float(tcs_amt)

    results["totals"]["bookings"] = len(seen_booking_ids)

    def add_total(block: Dict):
        keys = [
            "sales_cash", "sales_non_cash",
            "purchase_cash", "purchase_non_cash",
            "profit_cash", "profit_non_cash",
            "discount", "gst", "tcs",
        ]
        totals = {k: 0.0 for k in keys}
        for v in block.values():
            for k in keys:
                totals[k] += float(v.get(k, 0.0))
        block["TOTAL"] = totals

    add_total(results["service_summary"])
    add_total(results["employee_summary"])

    return JsonResponse(results)


# ---------------------------
# Booking-wise Summary (Client table) - NEW SYSTEM ONLY
# ---------------------------

@login_required
def bookings_report(request):
    service = request.GET.get("service")
    employee = request.GET.get("employee")
    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    # Only bookings with approved NEW payments (service_id not null)
    bookings = (
        Booking.objects
        .filter(
            id__in=PaymentReceived.objects.filter(approved=True, service__isnull=False)
            .values_list("booking_id", flat=True)
            .distinct()
        )
        .select_related("client", "created_by")
        .distinct()
    )

    # Booking-level filters
    if year:
        bookings = bookings.filter(booking_date__year=year)
    if month:
        try:
            month_num = datetime.strptime(month, "%B").month
            bookings = bookings.filter(booking_date__month=month_num)
        except ValueError:
            pass
    if employee:
        # Booking table meaning (as in your UI): created_by
        bookings = bookings.filter(created_by_id=employee)
    if client:
        bookings = bookings.filter(client_id=client)

    data = []

    for booking in bookings:
        if not booking_all_services_fully_approved(booking.id):
            continue

        bs_qs = (
            BookingService.objects
            .filter(booking_id=booking.id)
            .select_related("service")
            .distinct()
        )

        # Service filter (new system only)
        if service:
            bs_qs = bs_qs.filter(service__name=service)

        services_data = []

        book_sales_cash = Decimal("0")
        book_sales_non_cash_net = Decimal("0")
        book_purchase_cash = Decimal("0")
        book_purchase_non_cash = Decimal("0")
        book_profit_cash = Decimal("0")
        book_profit_non_cash = Decimal("0")
        book_discount = Decimal("0")
        book_gst = Decimal("0")
        book_tcs = Decimal("0")

        for bs in bs_qs:
            svc = bs.service
            service_code = _svc_code(svc)

            model = SERVICE_MODEL_MAP.get(service_code)
            if supplier and model:
                if not model.objects.filter(booking_id=booking.id, supplier_id=supplier).exists():
                    continue

            sales_total, sales_cash, sales_non_cash, discount_total = _svc_sales_totals_from_payments(
                booking_id=booking.id,
                service_id=svc.id
            )
            if sales_total <= 0:
                continue

            _, purch_cash, purch_non_cash = _svc_purchase_totals(booking.id, service_code)
            gst_amt, tcs_amt = _svc_tax_totals_from_service_rows(booking.id, service_code)

            sales_non_cash_net = sales_non_cash - tcs_amt

            profit_cash = sales_cash - purch_cash
            profit_non_cash = (sales_non_cash_net - purch_non_cash) - gst_amt
            profit_total = profit_cash + profit_non_cash

            def get_service_creator_name(booking_id, service_code, fallback_user):
                model = SERVICE_MODEL_MAP.get(service_code)
                if not model:
                    return fallback_user
                obj = (
                    model.objects
                    .filter(booking_id=booking_id)
                    .select_related("created_by")
                    .first()
                )
                if obj and obj.created_by:
                    return obj.created_by.get_full_name() or obj.created_by.username
                return fallback_user

            entered_by = get_service_creator_name(
                booking.id,
                service_code,
                booking.created_by.get_full_name() or booking.created_by.username
            )

            services_data.append({
                "service_id": svc.id,
                "service": svc.name,
                "mode": "Mixed",

                "sales_cash": float(sales_cash),
                "sales_non_cash": float(sales_non_cash_net),
                "sales_total": float(to_decimal(sales_cash + sales_non_cash_net)),

                "purchase_cash": float(purch_cash),
                "purchase_non_cash": float(purch_non_cash),
                "purchase_total": float(to_decimal(purch_cash + purch_non_cash)),

                "profit_cash": float(profit_cash),
                "profit_non_cash": float(profit_non_cash),
                "profit_total": float(profit_total),

                "gst": float(gst_amt),
                "tcs": float(tcs_amt),
                "discount": float(discount_total),

                "entered_by": entered_by,
            })

            book_sales_cash += sales_cash
            book_sales_non_cash_net += sales_non_cash_net
            book_purchase_cash += purch_cash
            book_purchase_non_cash += purch_non_cash
            book_profit_cash += profit_cash
            book_profit_non_cash += profit_non_cash
            book_discount += discount_total
            book_gst += gst_amt
            book_tcs += tcs_amt

        if not services_data:
            continue

        data.append({
            "booking_id": booking.booking_id,
            "booking_date": booking.booking_date.strftime("%d-%b-%Y") if booking.booking_date else "",
            "created_by": booking.created_by.get_full_name() or booking.created_by.username,
            "client_name": f"{booking.client.first_name} {booking.client.last_name}" if booking.client else "Unknown",
            "services": services_data,
            "totals": {
                "sales_cash": float(book_sales_cash),
                "sales_non_cash": float(book_sales_non_cash_net),
                "purchase_cash": float(book_purchase_cash),
                "purchase_non_cash": float(book_purchase_non_cash),
                "profit_cash": float(book_profit_cash),
                "profit_non_cash": float(book_profit_non_cash),
                "total_profit": float(book_profit_cash + book_profit_non_cash),
                "discount": float(book_discount),
                "gst": float(book_gst),
                "tcs": float(book_tcs),
            },
            "is_legacy": False,
        })

    return JsonResponse({"data": data})
