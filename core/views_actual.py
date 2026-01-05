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
from payments.models import PaymentReceived
from services.models import Hotel, Transfer, SightSeeing, Ticket, Visa, Insurance, Passport

User = get_user_model()


# ---------------------------
# Small utils
# ---------------------------

def to_decimal(val) -> Decimal:
    try:
        return Decimal(str(val or 0))
    except Exception:
        return Decimal("0")


def is_cash_mode(mode) -> bool:
    """Cash detection: mode.name contains 'cash' (case-insensitive)."""
    if not mode or not getattr(mode, "name", None):
        return False
    return "cash" in mode.name.lower()


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
    return (getattr(service_obj, "code", "") or getattr(service_obj, "name", "") or "") \
        .strip().lower().replace(" ", "")


def _svc_purchase_totals(booking_id: int, service_code: str) -> Tuple[Decimal, Decimal, Decimal]:
    """
    Purchase is from service tables (supplier-side).
    Split cash/non-cash using service.mode.
    """
    model = SERVICE_MODEL_MAP.get(service_code)
    z = Decimal("0")
    if not model:
        return z, z, z

    total = model.objects.filter(booking_id=booking_id).aggregate(s=Sum("purchase_amount"))["s"] or z
    cash = model.objects.filter(booking_id=booking_id, mode__name__icontains="cash").aggregate(s=Sum("purchase_amount"))["s"] or z
    non_cash = to_decimal(total) - to_decimal(cash)
    return to_decimal(total), to_decimal(cash), to_decimal(non_cash)


def _svc_sales_totals_from_payments(booking_id: int, service_id: int) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
    """
    Sales is from approved payments (customer-side).
    """
    payments = (
        PaymentReceived.objects
        .filter(booking_id=booking_id, service_id=service_id, approved=True)
        .select_related("mode")
    )
    z = Decimal("0")
    if not payments.exists():
        return z, z, z, z

    sales_total = sum(to_decimal(p.amount) for p in payments)
    sales_cash = sum(to_decimal(p.amount) for p in payments if is_cash_mode(p.mode))
    sales_non_cash = sales_total - sales_cash
    discount_total = sum(to_decimal(p.discount) for p in payments)

    return sales_total, sales_cash, sales_non_cash, discount_total


def _svc_gst_tcs_split_for_booking_service(booking_id: int, service_code: str) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
    """
    Returns:
      (gst_cash, gst_non_cash, tcs_non_cash, gst_total)

    EXACT RULES YOU WANT (service-table based, NOT payment based):

    GST:
      - Ticket: GST applies ALWAYS (cash OR non-cash) and stays in that bucket
      - Other services: GST ONLY if NON-CASH (cash => 0)
      - GST = 18% * (sales_amount - purchase_amount) per service-row

    TCS:
      - Only Hotel / Sightseeing / Transfer
      - Only if NON-CASH AND international (travel_type == 'international')
      - TCS = sales_amount * 5% (per row)
      - TCS always belongs to NON-CASH bucket (reduces non-cash sales side)
    """
    model = SERVICE_MODEL_MAP.get(service_code)
    z = Decimal("0")
    if not model:
        return z, z, z, z

    qs = model.objects.filter(booking_id=booking_id).select_related("mode")

    gst_rate = Decimal("0.18")
    tcs_rate = Decimal("0.05")

    gst_cash = Decimal("0")
    gst_non_cash = Decimal("0")
    tcs_non_cash = Decimal("0")

    for obj in qs:
        mode = getattr(obj, "mode", None)
        mode_name = (getattr(mode, "name", "") or "").strip().lower()
        obj_is_cash = (mode_name == "cash")

        sales_amt = to_decimal(getattr(obj, "sales_amount", 0))
        purchase_amt = to_decimal(getattr(obj, "purchase_amount", 0))
        base_amount = sales_amt - purchase_amt

        # GST
        if service_code == "ticket":
            gst = base_amount * gst_rate
            if obj_is_cash:
                gst_cash += gst
            else:
                gst_non_cash += gst
        else:
            # non-ticket: ONLY if NON-CASH
            if not obj_is_cash:
                gst_non_cash += (base_amount * gst_rate)

        # TCS
        if service_code in ["hotel", "transfer", "sightseeing"]:
            travel_type = (getattr(obj, "travel_type", "") or "").strip().lower()
            is_international = (travel_type == "international")
            if (not obj_is_cash) and is_international:
                tcs_non_cash += (sales_amt * tcs_rate)

    gst_total = gst_cash + gst_non_cash
    return gst_cash, gst_non_cash, tcs_non_cash, gst_total


# ---------------------------
# Gate: all assigned services fully approved
# ---------------------------

def booking_all_services_fully_approved(booking_id: int) -> bool:
    service_ids = list(
        BookingService.objects.filter(booking_id=booking_id)
        .values_list("service_id", flat=True)
        .distinct()
    )
    if not service_ids:
        return False

    # any pending payment row => booking not eligible
    if PaymentReceived.objects.filter(booking_id=booking_id, service_id__in=service_ids, approved=False).exists():
        return False

    # each assigned service must have at least 1 approved payment row
    for sid in service_ids:
        if not PaymentReceived.objects.filter(booking_id=booking_id, service_id=sid, approved=True).exists():
            return False

    return True


# ---------------------------
# Main Page
# ---------------------------

@login_required
def staff_actual_reports(request):
    return render(request, "staff_actual_profit.html")


# ---------------------------
# Staff Filtered Summary
# Totals = ONLY logged-in user's service contributions
# ---------------------------

@login_required
def staff_filtered_actual_report(request):
    user = request.user

    service = request.GET.get("service")
    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    # totals are based ONLY on assignments where assigned_to=user
    assignments = (
        BookingService.objects
        .select_related("booking", "booking__client", "service")
        .filter(assigned_to=user)
        .filter(
            booking_id__in=PaymentReceived.objects.filter(approved=True)
            .values_list("booking_id", flat=True)
            .distinct()
        )
    )

    # booking-level filters
    if year:
        assignments = assignments.filter(booking__booking_date__year=year)
    if month:
        try:
            month_num = datetime.strptime(month, "%B").month
            assignments = assignments.filter(booking__booking_date__month=month_num)
        except ValueError:
            pass
    if client:
        assignments = assignments.filter(booking__client_id=client)

    # service filter
    if service:
        assignments = assignments.filter(service__name=service)

    results = {
        "totals": {
            "sales_cash": 0.0, "sales_non_cash": 0.0,
            "purchase_cash": 0.0, "purchase_non_cash": 0.0,
            "profit_cash": 0.0, "profit_non_cash": 0.0,
            "discount": 0.0, "bookings": 0,
        },
        "service_summary": {},
    }

    seen_booking_ids = set()

    for a in assignments:
        booking = a.booking
        if not booking_all_services_fully_approved(booking.id):
            continue

        svc = a.service
        scode = _svc_code(svc)

        # supplier filter depends on service table
        model = SERVICE_MODEL_MAP.get(scode)
        if supplier and model:
            if not model.objects.filter(booking_id=booking.id, supplier_id=supplier).exists():
                continue

        sales_total, sales_cash, sales_non_cash, discount_total = _svc_sales_totals_from_payments(
            booking_id=booking.id,
            service_id=svc.id
        )
        if sales_total <= 0:
            continue

        purch_total, purch_cash, purch_non_cash = _svc_purchase_totals(booking.id, scode)

        # ✅ taxes split by bucket using service-table mode rows
        gst_cash, gst_non_cash, tcs_non_cash, _gst_total = _svc_gst_tcs_split_for_booking_service(booking.id, scode)

        # ✅ TCS reduces NON-CASH sales side
        sales_non_cash_net = sales_non_cash - tcs_non_cash

        # ✅ NET profits per your rule: cash side never gets GST for non-ticket
        profit_cash = (sales_cash - purch_cash) - gst_cash
        profit_non_cash = (sales_non_cash_net - purch_non_cash) - gst_non_cash

        results["totals"]["sales_cash"] += float(sales_cash)
        results["totals"]["sales_non_cash"] += float(sales_non_cash_net)
        results["totals"]["purchase_cash"] += float(purch_cash)
        results["totals"]["purchase_non_cash"] += float(purch_non_cash)
        results["totals"]["profit_cash"] += float(profit_cash)
        results["totals"]["profit_non_cash"] += float(profit_non_cash)
        results["totals"]["discount"] += float(discount_total)

        seen_booking_ids.add(booking.id)

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
# Staff Bookings (table + modal)
# Table totals = user-only contribution
# Modal = if user created booking show all services, else only their services
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
        .filter(
            id__in=PaymentReceived.objects.filter(approved=True).values_list("booking_id", flat=True).distinct()
        )
        .select_related("client", "created_by")
        .distinct()
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

    def passes_supplier_filter(booking_id: int, svc_obj) -> bool:
        if not supplier:
            return True
        scode = _svc_code(svc_obj)
        model = SERVICE_MODEL_MAP.get(scode)
        if not model:
            return False
        return model.objects.filter(booking_id=booking_id, supplier_id=supplier).exists()

    data = []

    for booking in bookings:
        if not booking_all_services_fully_approved(booking.id):
            continue

        user_is_creator = (booking.created_by_id == user.id)

        # modal: creator sees all services, otherwise only user services
        modal_bs = BookingService.objects.filter(booking_id=booking.id).select_related("service", "assigned_to")
        if not user_is_creator:
            modal_bs = modal_bs.filter(assigned_to=user)

        if service:
            modal_bs = modal_bs.filter(service__name=service)

        # table totals are always user-only services
        totals_bs = BookingService.objects.filter(booking_id=booking.id, assigned_to=user).select_related("service")
        if service:
            totals_bs = totals_bs.filter(service__name=service)

        services_data = []

        # -------------------------
        # Modal services list
        # -------------------------
        for bs in modal_bs:
            svc = bs.service
            if not passes_supplier_filter(booking.id, svc):
                continue

            scode = _svc_code(svc)

            sales_total, sales_cash, sales_non_cash, discount_total = _svc_sales_totals_from_payments(booking.id, svc.id)
            if sales_total <= 0:
                continue

            purch_total, purch_cash, purch_non_cash = _svc_purchase_totals(booking.id, scode)

            # ✅ taxes split correctly by your rules
            gst_cash, gst_non_cash, tcs_non_cash, gst_total = _svc_gst_tcs_split_for_booking_service(booking.id, scode)

            sales_non_cash_net = sales_non_cash - tcs_non_cash

            profit_cash = (sales_cash - purch_cash) - gst_cash
            profit_non_cash = (sales_non_cash_net - purch_non_cash) - gst_non_cash
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

                # ✅ NET profits with correct GST behavior
                "profit_cash": float(profit_cash),
                "profit_non_cash": float(profit_non_cash),
                "profit_total": float(profit_total),

                "gst": float(gst_total),
                "tcs": float(tcs_non_cash),

                "discount": float(discount_total),
                "entered_by": bs.assigned_to.get_full_name() or bs.assigned_to.username,
            })

        if not services_data:
            continue

        # -------------------------
        # Table totals (user-only)
        # -------------------------
        tot_sales_cash = Decimal("0")
        tot_sales_non_cash = Decimal("0")
        tot_purchase_cash = Decimal("0")
        tot_purchase_non_cash = Decimal("0")
        tot_profit_cash = Decimal("0")
        tot_profit_non_cash = Decimal("0")
        tot_discount = Decimal("0")

        for bs in totals_bs:
            svc = bs.service
            if not passes_supplier_filter(booking.id, svc):
                continue

            scode = _svc_code(svc)

            sales_total, sales_cash, sales_non_cash, discount_total = _svc_sales_totals_from_payments(booking.id, svc.id)
            if sales_total <= 0:
                continue

            purch_total, purch_cash, purch_non_cash = _svc_purchase_totals(booking.id, scode)

            # ✅ taxes split correctly by your rules
            gst_cash, gst_non_cash, tcs_non_cash, _gst_total = _svc_gst_tcs_split_for_booking_service(booking.id, scode)

            sales_non_cash_net = sales_non_cash - tcs_non_cash

            profit_cash = (sales_cash - purch_cash) - gst_cash
            profit_non_cash = (sales_non_cash_net - purch_non_cash) - gst_non_cash

            tot_sales_cash += sales_cash
            tot_sales_non_cash += sales_non_cash_net
            tot_purchase_cash += purch_cash
            tot_purchase_non_cash += purch_non_cash
            tot_profit_cash += profit_cash
            tot_profit_non_cash += profit_non_cash
            tot_discount += discount_total

        if (tot_sales_cash + tot_sales_non_cash) <= 0:
            continue

        data.append({
            "booking_id": booking.booking_id,
            "booking_date": booking.booking_date.strftime("%d-%b-%Y") if booking.booking_date else "",
            "client_name": f"{booking.client.first_name} {booking.client.last_name}" if booking.client else "Unknown",

            # new visibility fields
            "booking_created_by": booking.created_by.get_full_name() or booking.created_by.username,
            "i_created_this_booking": bool(user_is_creator),

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
