# reports/views_actual.py  (NEW-ONLY staff logic)

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Tuple

from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db.models import Sum, Q
from django.http import JsonResponse
from django.shortcuts import render

from bookings.models import Booking, BookingService
from payments.models import PaymentReceived
from services.models import Hotel, Transfer, SightSeeing, Ticket, Visa, Insurance, Passport

User = get_user_model()


# ---------------------------
# Utils
# ---------------------------
ZERO = Decimal("0")


def to_decimal(val) -> Decimal:
    try:
        return Decimal(str(val or 0))
    except Exception:
        return ZERO


def is_cash_mode(mode) -> bool:
    if not mode or not getattr(mode, "name", None):
        return False
    return "cash" in mode.name.lower()


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
        .strip().lower().replace(" ", "")
    )


def booking_has_any_legacy_approved_payments(booking_id: int) -> bool:
    """
    If a booking has any approved PaymentReceived with service IS NULL,
    treat it as legacy-mixed and EXCLUDE from new-only staff reports.
    """
    return PaymentReceived.objects.filter(
        booking_id=booking_id, approved=True, service__isnull=True
    ).exists()


def booking_all_services_fully_approved(booking_id: int) -> bool:
    """
    New rule gate:
    - booking must have BookingService rows
    - no pending PaymentReceived (approved=False) for those service_ids
    - at least 1 approved payment per service_id
    """
    service_ids = list(
        BookingService.objects.filter(booking_id=booking_id)
        .values_list("service_id", flat=True)
        .distinct()
    )
    if not service_ids:
        return False

    if PaymentReceived.objects.filter(
        booking_id=booking_id, service_id__in=service_ids, approved=False
    ).exists():
        return False

    for sid in service_ids:
        if not PaymentReceived.objects.filter(
            booking_id=booking_id, service_id=sid, approved=True
        ).exists():
            return False

    return True


def _svc_purchase_totals(booking_id: int, service_code: str) -> Tuple[Decimal, Decimal, Decimal]:
    """
    Purchase from service tables, split by service.mode cash/non-cash.
    NOTE: This sums purchase_amount for the booking in that service table.
    """
    model = SERVICE_MODEL_MAP.get(service_code)
    if not model:
        return ZERO, ZERO, ZERO

    total = to_decimal(model.objects.filter(booking_id=booking_id).aggregate(s=Sum("purchase_amount"))["s"])
    cash = to_decimal(
        model.objects.filter(booking_id=booking_id, mode__name__icontains="cash")
        .aggregate(s=Sum("purchase_amount"))["s"]
    )
    non_cash = total - cash
    return total, cash, non_cash


def _svc_sales_totals_from_payments(booking_id: int, service_id: int) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
    """
    Sales from approved payments tied to a specific service.
    """
    payments = (
        PaymentReceived.objects
        .filter(booking_id=booking_id, service_id=service_id, approved=True)
        .select_related("mode")
    )
    if not payments.exists():
        return ZERO, ZERO, ZERO, ZERO

    sales_total = sum(to_decimal(p.amount) for p in payments)
    sales_cash = sum(to_decimal(p.amount) for p in payments if is_cash_mode(p.mode))
    sales_non_cash = sales_total - sales_cash
    discount_total = sum(to_decimal(p.discount) for p in payments)
    return sales_total, sales_cash, sales_non_cash, discount_total


def _svc_gst_tcs_for_booking_service(booking_id: int, service_code: str) -> Tuple[Decimal, Decimal]:
    """
    Your service-table GST/TCS rules.

    GST:
      - Ticket: always
      - Others: only if NON-CASH
      - GST = 18% * (sales_amount - purchase_amount)

    TCS:
      - Only Hotel / Sightseeing / Transfer
      - Only if NON-CASH AND international (travel_type == 'international')
      - TCS = sales_amount * 2%
    """
    model = SERVICE_MODEL_MAP.get(service_code)
    if not model:
        return ZERO, ZERO

    qs = model.objects.filter(booking_id=booking_id).select_related("mode")

    gst_rate = Decimal("0.18")
    tcs_rate = Decimal("0.02")

    gst_total = ZERO
    tcs_total = ZERO

    for obj in qs:
        mode = getattr(obj, "mode", None)
        obj_is_cash = bool(mode and getattr(mode, "name", "").lower() == "cash")

        sales_amt = to_decimal(getattr(obj, "sales_amount", 0))
        purchase_amt = to_decimal(getattr(obj, "purchase_amount", 0))
        base_amount = sales_amt - purchase_amt

        # GST
        if service_code == "ticket":
            gst_total += base_amount * gst_rate
        else:
            if not obj_is_cash:
                gst_total += base_amount * gst_rate

        # TCS
        if service_code in ["hotel", "transfer", "sightseeing"]:
            travel_type = (getattr(obj, "travel_type", "") or "").lower()
            if (not obj_is_cash) and travel_type == "international":
                tcs_total += sales_amt * tcs_rate

    return gst_total, tcs_total


# ---------------------------
# Page
# ---------------------------
@login_required
def staff_actual_reports(request):
    return render(request, "staff_actual_profit.html")


# ---------------------------
# Staff Filtered Summary (NEW-ONLY)
# - only service-linked rows for request.user
# - exclude any booking that has legacy approved payments (service is NULL)
# ---------------------------
@login_required
def staff_filtered_actual_report(request):
    user = request.user

    service = request.GET.get("service")
    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    results = {
        "totals": {
            "sales_cash": 0.0, "sales_non_cash": 0.0,
            "purchase_cash": 0.0, "purchase_non_cash": 0.0,
            "profit_cash": 0.0, "profit_non_cash": 0.0,
            "discount": 0.0, "bookings": 0,
        },
        "service_summary": {},  # service-linked only
    }

    assignments = (
        BookingService.objects
        .select_related("booking", "booking__client", "service")
        .filter(assigned_to=user)
        # must have at least one approved service-linked payment somewhere in the booking
        .filter(
            booking_id__in=PaymentReceived.objects.filter(approved=True, service__isnull=False)
            .values_list("booking_id", flat=True)
            .distinct()
        )
    )

    # booking-level filters
    if year:
        assignments = assignments.filter(booking__booking_date__year=year)
    if month:
        try:
            assignments = assignments.filter(booking__booking_date__month=datetime.strptime(month, "%B").month)
        except ValueError:
            pass
    if client:
        assignments = assignments.filter(booking__client_id=client)

    # service filter
    if service:
        assignments = assignments.filter(service__name=service)

    seen_booking_ids = set()

    for a in assignments:
        booking = a.booking

        # NEW-ONLY hard exclude if booking contains any approved legacy-unassigned payment
        if booking_has_any_legacy_approved_payments(booking.id):
            continue

        # gate: full per-service approval
        if not booking_all_services_fully_approved(booking.id):
            continue

        svc = a.service
        scode = _svc_code(svc)

        # supplier filter (service table based)
        if supplier:
            model = SERVICE_MODEL_MAP.get(scode)
            if not model or not model.objects.filter(booking_id=booking.id, supplier_id=supplier).exists():
                continue

        sales_total, sales_cash, sales_non_cash, discount_total = _svc_sales_totals_from_payments(booking.id, svc.id)
        if sales_total <= 0:
            continue

        _, purch_cash, purch_non_cash = _svc_purchase_totals(booking.id, scode)
        gst_amt, tcs_amt = _svc_gst_tcs_for_booking_service(booking.id, scode)

        # TCS reduces non-cash sales
        sales_non_cash_net = sales_non_cash - tcs_amt

        # Your rule: DO NOT deduct GST from cash profit.
        profit_cash = sales_cash - purch_cash
        profit_non_cash = (sales_non_cash_net - purch_non_cash) - gst_amt

        # totals
        results["totals"]["sales_cash"] += float(sales_cash)
        results["totals"]["sales_non_cash"] += float(sales_non_cash_net)
        results["totals"]["purchase_cash"] += float(purch_cash)
        results["totals"]["purchase_non_cash"] += float(purch_non_cash)
        results["totals"]["profit_cash"] += float(profit_cash)
        results["totals"]["profit_non_cash"] += float(profit_non_cash)
        results["totals"]["discount"] += float(discount_total)

        seen_booking_ids.add(booking.id)

        # service summary
        sname = svc.name
        sdata = results["service_summary"].setdefault(sname, {
            "sales_cash": 0.0, "sales_non_cash": 0.0,
            "purchase_cash": 0.0, "purchase_non_cash": 0.0,
            "profit_cash": 0.0, "profit_non_cash": 0.0,
            "discount": 0.0,
        })
        sdata["sales_cash"] += float(sales_cash)
        sdata["sales_non_cash"] += float(sales_non_cash_net)
        sdata["purchase_cash"] += float(purch_cash)
        sdata["purchase_non_cash"] += float(purch_non_cash)
        sdata["profit_cash"] += float(profit_cash)
        sdata["profit_non_cash"] += float(profit_non_cash)
        sdata["discount"] += float(discount_total)

    results["totals"]["bookings"] = len(seen_booking_ids)
    return JsonResponse(results)


# ---------------------------
# Staff Bookings Report (NEW-ONLY)
# - includes bookings where user is creator OR assigned
# - BUT excludes any booking that has legacy approved payments (service NULL)
# - shows ONLY user's assigned services in totals
# - modal: creator sees all services; otherwise only assigned services
# ---------------------------
@login_required
def staff_bookings_report(request):
    user = request.user

    service = request.GET.get("service")
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
        # must have approved service-linked payment
        .filter(id__in=PaymentReceived.objects.filter(approved=True, service__isnull=False)
                .values_list("booking_id", flat=True).distinct())
        .select_related("client", "created_by")
        .distinct()
    )

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

    def passes_supplier_filter(booking_id: int, svc_obj) -> bool:
        if not supplier:
            return True
        scode = _svc_code(svc_obj)
        model = SERVICE_MODEL_MAP.get(scode)
        if not model:
            return False
        return model.objects.filter(booking_id=booking_id, supplier_id=supplier).exists()

    for booking in bookings:
        # NEW-ONLY hard exclude any legacy-mixed booking
        if booking_has_any_legacy_approved_payments(booking.id):
            continue

        # gate: full approval
        if not booking_all_services_fully_approved(booking.id):
            continue

        user_is_creator = (booking.created_by_id == user.id)

        # modal rows: creator sees all, else only my assigned
        modal_bs = BookingService.objects.filter(booking_id=booking.id).select_related("service", "assigned_to")
        if not user_is_creator:
            modal_bs = modal_bs.filter(assigned_to=user)
        if service:
            modal_bs = modal_bs.filter(service__name=service)

        # table totals: always only my assigned
        totals_bs = BookingService.objects.filter(booking_id=booking.id, assigned_to=user).select_related("service")
        if service:
            totals_bs = totals_bs.filter(service__name=service)

        services_data = []
        for bs in modal_bs:
            svc = bs.service
            if not passes_supplier_filter(booking.id, svc):
                continue

            scode = _svc_code(svc)

            sales_total, sales_cash, sales_non_cash, discount_total = _svc_sales_totals_from_payments(booking.id, svc.id)
            if sales_total <= 0:
                continue

            _, purch_cash, purch_non_cash = _svc_purchase_totals(booking.id, scode)
            gst_amt, tcs_amt = _svc_gst_tcs_for_booking_service(booking.id, scode)

            sales_non_cash_net = sales_non_cash - tcs_amt

            profit_cash = sales_cash - purch_cash
            profit_non_cash = (sales_non_cash_net - purch_non_cash) - gst_amt
            profit_total = profit_cash + profit_non_cash

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
                "entered_by": bs.assigned_to.get_full_name() or bs.assigned_to.username,
            })

        if not services_data:
            continue

        # totals (my assigned only)
        tot_sales_cash = ZERO
        tot_sales_non_cash = ZERO
        tot_purchase_cash = ZERO
        tot_purchase_non_cash = ZERO
        tot_profit_cash = ZERO
        tot_profit_non_cash = ZERO
        tot_discount = ZERO

        for bs in totals_bs:
            svc = bs.service
            if not passes_supplier_filter(booking.id, svc):
                continue

            scode = _svc_code(svc)

            sales_total, sales_cash, sales_non_cash, discount_total = _svc_sales_totals_from_payments(booking.id, svc.id)
            if sales_total <= 0:
                continue

            _, purch_cash, purch_non_cash = _svc_purchase_totals(booking.id, scode)
            gst_amt, tcs_amt = _svc_gst_tcs_for_booking_service(booking.id, scode)

            sales_non_cash_net = sales_non_cash - tcs_amt

            profit_cash = sales_cash - purch_cash
            profit_non_cash = (sales_non_cash_net - purch_non_cash) - gst_amt

            tot_sales_cash += sales_cash
            tot_sales_non_cash += sales_non_cash_net
            tot_purchase_cash += purch_cash
            tot_purchase_non_cash += purch_non_cash
            tot_profit_cash += profit_cash
            tot_profit_non_cash += profit_non_cash
            tot_discount += discount_total

        # hide booking row if I have no contribution
        if (tot_sales_cash + tot_sales_non_cash) <= 0:
            continue

        data.append({
            "booking_id": booking.booking_id,
            "booking_date": booking.booking_date.strftime("%d-%b-%Y") if booking.booking_date else "",
            "client_name": f"{booking.client.first_name} {booking.client.last_name}" if booking.client else "Unknown",
            "services": services_data,
            "totals": {
                "sales_cash": float(tot_sales_cash),
                "sales_non_cash": float(tot_sales_non_cash),
                "purchase_cash": float(tot_purchase_cash),
                "purchase_non_cash": float(tot_purchase_non_cash),
                "profit_cash": float(tot_profit_cash),
                "profit_non_cash": float(tot_profit_non_cash),
                "discount": float(tot_discount),
            },
        })

    return JsonResponse({"data": data})
