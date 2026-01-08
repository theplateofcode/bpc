from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict, Tuple

from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db.models import Sum, Q
from django.http import JsonResponse
from django.shortcuts import render

from bookings.models import Booking, BookingService
from payments.models import PaymentReceived, Mode
from services.models import Hotel, Transfer, SightSeeing, Ticket, Visa, Insurance, Passport

User = get_user_model()

# ---------------------------
# Small utils
# ---------------------------

GST_RATE = Decimal("0.18")
TCS_RATE = Decimal("0.05")


def to_decimal(val) -> Decimal:
    try:
        return Decimal(str(val or 0))
    except Exception:
        return Decimal("0")


def is_cash_mode(mode) -> bool:
    """
    PaymentReceived.mode cash detection:
    mode is cash if its name is exactly 'cash' (case-insensitive).
    """
    if not mode or not getattr(mode, "name", None):
        return False
    return mode.name.strip().lower() == "cash"


def get_cash_mode_ids() -> Tuple[int, ...]:
    """
    Robust 'cash' detection for service purchase rows.
    Uses Mode IDs (avoids join+string issues).
    """
    return tuple(Mode.objects.filter(name__iexact="cash").values_list("id", flat=True))


# ---------------------------
# Service mapping (purchase/sales source)
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
    """
    BookingService.service is ServiceList.
    Typically .code is lowercase like 'hotel', 'ticket', etc.
    """
    return (
        (getattr(service_obj, "code", "") or getattr(service_obj, "name", "") or "")
        .strip()
        .lower()
        .replace(" ", "")
    )


# ---------------------------
# Purchase totals (service table: supplier-side)
# ---------------------------

def _svc_purchase_totals(
    booking_id: int,
    service_code: str,
    cash_mode_ids: Tuple[int, ...],
) -> Tuple[Decimal, Decimal, Decimal]:
    """
    Returns (purchase_total, purchase_cash, purchase_non_cash) for THIS booking + THIS service.
    Cash is detected by mode_id IN cash_mode_ids (NOT mode__name join).
    """
    model = SERVICE_MODEL_MAP.get(service_code)
    z = Decimal("0")
    if not model:
        return z, z, z

    agg = (
        model.objects
        .filter(booking_id=booking_id)
        .aggregate(
            total=Sum("purchase_amount"),
            cash=Sum("purchase_amount", filter=Q(mode_id__in=cash_mode_ids)) if cash_mode_ids else None,
        )
    )

    total = to_decimal(agg["total"])
    cash = to_decimal(agg["cash"])
    non_cash = total - cash
    return total, cash, non_cash


# ---------------------------
# Sales totals (payments table: customer-side actuals)
# ---------------------------

def _svc_sales_totals_from_payments(
    booking_id: int,
    service_id: int
) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
    """
    Returns (sales_total, sales_cash, sales_non_cash, discount_total) for THIS booking+service
    from approved PaymentReceived rows.
    """
    payments = (
        PaymentReceived.objects
        .filter(booking_id=booking_id, service_id=service_id, approved=True)
        .select_related("mode")
    )

    if not payments.exists():
        z = Decimal("0")
        return z, z, z, z

    sales_cash = sum(to_decimal(p.amount) for p in payments if is_cash_mode(p.mode))
    sales_total = sum(to_decimal(p.amount) for p in payments)
    sales_non_cash = sales_total - sales_cash
    discount_total = sum(to_decimal(p.discount) for p in payments)
    return sales_total, sales_cash, sales_non_cash, discount_total


# ---------------------------
# GST/TCS helpers (service-row rules: NOT payments)
# ---------------------------

def _svc_tax_totals_from_service_rows(
    booking_id: int,
    service_code: str,
    cash_mode_ids: Tuple[int, ...],
) -> Tuple[Decimal, Decimal]:
    """
    Returns (gst_total, tcs_total) for THIS booking + THIS service, computed from service rows.

    GST rules:
      - Ticket: GST ALWAYS on (sales_amount - purchase_amount) * 18% (even cash)
      - Others: GST only if NON-CASH on that service row

    TCS rules:
      - Only for Hotel/Transfer/Sightseeing
      - Only if NON-CASH AND travel_type == 'international'
      - TCS = sales_amount * 5%

    IMPORTANT: cash detection uses obj.mode_id IN cash_mode_ids.
    """
    model = SERVICE_MODEL_MAP.get(service_code)
    z = Decimal("0")
    if not model:
        return z, z

    qs = model.objects.filter(booking_id=booking_id)

    gst_total = Decimal("0")
    tcs_total = Decimal("0")

    for obj in qs:
        is_cash = bool(getattr(obj, "mode_id", None) in cash_mode_ids)

        sales_amount = to_decimal(getattr(obj, "sales_amount", 0))
        purchase_amount = to_decimal(getattr(obj, "purchase_amount", 0))
        base_amount = sales_amount - purchase_amount

        # GST
        if service_code == "ticket":
            gst = base_amount * GST_RATE
        else:
            gst = Decimal("0") if is_cash else base_amount * GST_RATE

        gst_total += gst

        # TCS
        if service_code in {"hotel", "transfer", "sightseeing"}:
            travel_type = (getattr(obj, "travel_type", "") or "").strip().lower()
            is_international = travel_type == "international"
            if (not is_cash) and is_international:
                tcs_total += (sales_amount * TCS_RATE)

    return gst_total, tcs_total


# ---------------------------
# Booking “fully approved” gate
# ---------------------------

def booking_all_services_fully_approved(booking_id: int) -> bool:
    """
    Booking is eligible only if:
    - booking has services assigned in BookingService
    - AND there are NO pending (approved=False) payments for that booking+assigned services
    - AND each assigned service has at least 1 approved payment row
    """
    service_ids = list(
        BookingService.objects
        .filter(booking_id=booking_id)
        .values_list("service_id", flat=True)
        .distinct()
    )
    if not service_ids:
        return False

    if PaymentReceived.objects.filter(
        booking_id=booking_id,
        service_id__in=service_ids,
        approved=False
    ).exists():
        return False

    for sid in service_ids:
        if not PaymentReceived.objects.filter(
            booking_id=booking_id,
            service_id=sid,
            approved=True
        ).exists():
            return False

    return True


# ---------------------------
# Main Page
# ---------------------------

@login_required
def owner_actual_reports(request):
    return render(request, "owner_reports_actual.html")


# ---------------------------
# Filtered Report (Cards + Summaries)
# NEW SYSTEM ONLY
# ---------------------------

@login_required
def filtered_actual_report(request):
    service = request.GET.get("service")      # ServiceList.name from UI
    employee = request.GET.get("employee")    # assigned_to id
    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    cash_mode_ids = get_cash_mode_ids()

    # Restrict to bookings that have at least one approved payment with a service (new system)
    new_booking_ids = PaymentReceived.objects.filter(
        approved=True,
        service__isnull=False
    ).values_list("booking_id", flat=True).distinct()

    assignments = (
        BookingService.objects
        .select_related("booking", "booking__client", "booking__created_by", "service", "assigned_to")
        .filter(booking_id__in=new_booking_ids)
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

        # Gate: only fully-approved new system bookings
        if not booking_all_services_fully_approved(booking.id):
            continue

        svc = a.service
        service_code = _svc_code(svc)

        # Supplier filter: check service model rows
        model = SERVICE_MODEL_MAP.get(service_code)
        if supplier and model:
            if not model.objects.filter(booking_id=booking.id, supplier_id=supplier).exists():
                continue

        # Sales from payments (actual received)
        sales_total, sales_cash, sales_non_cash, discount_total = _svc_sales_totals_from_payments(
            booking_id=booking.id,
            service_id=svc.id
        )
        if sales_total <= 0:
            continue

        seen_booking_ids.add(booking.id)

        # Purchase from service rows (robust cash split)
        purch_total, purch_cash, purch_non_cash = _svc_purchase_totals(
            booking.id, service_code, cash_mode_ids
        )

        # Taxes from service rows (robust cash check)
        gst_amt, tcs_amt = _svc_tax_totals_from_service_rows(
            booking.id, service_code, cash_mode_ids
        )

        # Apply TCS to NON-CASH sales (net)
        sales_non_cash_net = sales_non_cash - tcs_amt

        # Your rule: NO GST in cash profit; GST subtract from non-cash bucket only
        profit_cash = sales_cash - purch_cash
        profit_non_cash = (sales_non_cash_net - purch_non_cash) - gst_amt

        # Totals
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

        # Employee summary (assigned_to gets service contribution)
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
# Booking-wise Summary (Client Table)
# NEW SYSTEM ONLY
# ---------------------------

@login_required
def bookings_report(request):
    service = request.GET.get("service")
    employee = request.GET.get("employee")
    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    cash_mode_ids = get_cash_mode_ids()

    # Only bookings that have approved payments with a service (new system)
    bookings = (
        Booking.objects
        .filter(
            id__in=PaymentReceived.objects.filter(approved=True, service__isnull=False)
            .values_list("booking_id", flat=True)
            .distinct()
        )
        .select_related("client", "created_by")
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
        bookings = bookings.filter(created_by_id=employee)  # your existing meaning
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

        # service filter applies here too
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

            purch_total, purch_cash, purch_non_cash = _svc_purchase_totals(
                booking.id, service_code, cash_mode_ids
            )
            gst_amt, tcs_amt = _svc_tax_totals_from_service_rows(
                booking.id, service_code, cash_mode_ids
            )

            sales_non_cash_net = sales_non_cash - tcs_amt

            # Your rule: NO GST in cash profit; GST subtract from non-cash bucket
            profit_cash = sales_cash - purch_cash
            profit_non_cash = (sales_non_cash_net - purch_non_cash) - gst_amt
            profit_total = profit_cash + profit_non_cash

            def get_service_creator_name(booking_id: int, service_code: str, fallback_user: str) -> str:
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
                "service": svc.name,
                "mode": "Mixed",

                "sales_cash": float(sales_cash),
                "sales_non_cash": float(sales_non_cash_net),
                "sales_total": float(sales_cash + sales_non_cash_net),

                "purchase_cash": float(purch_cash),
                "purchase_non_cash": float(purch_non_cash),
                "purchase_total": float(purch_cash + purch_non_cash),

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
        })

    return JsonResponse({"data": data})
