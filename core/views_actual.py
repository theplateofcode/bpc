from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Tuple, Optional

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

def to_decimal(val) -> Decimal:
    try:
        return Decimal(str(val or 0))
    except Exception:
        return Decimal("0")


def is_cash_mode(mode) -> bool:
    if not mode or not getattr(mode, "name", None):
        return False
    return "cash" in mode.name.lower()


# ---------------------------
# Service mapping (service tables for GST/TCS + purchase split)
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
    Purchase from service tables, split by service.mode cash/non-cash.
    """
    model = SERVICE_MODEL_MAP.get(service_code)
    z = Decimal("0")
    if not model:
        return z, z, z

    total = model.objects.filter(booking_id=booking_id).aggregate(s=Sum("purchase_amount"))["s"] or z
    cash = model.objects.filter(booking_id=booking_id, mode__name__icontains="cash").aggregate(s=Sum("purchase_amount"))["s"] or z
    total = to_decimal(total)
    cash = to_decimal(cash)
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
    z = Decimal("0")
    if not payments.exists():
        return z, z, z, z

    sales_total = sum(to_decimal(p.amount) for p in payments)
    sales_cash = sum(to_decimal(p.amount) for p in payments if is_cash_mode(p.mode))
    sales_non_cash = sales_total - sales_cash
    discount_total = sum(to_decimal(p.discount) for p in payments)
    return sales_total, sales_cash, sales_non_cash, discount_total


def _legacy_booking_sales_from_payments(booking_id: int) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
    """
    Legacy sales: approved payments where service IS NULL (old production data).
    Exact booking-level totals.
    """
    payments = (
        PaymentReceived.objects
        .filter(booking_id=booking_id, approved=True, service__isnull=True)
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


def booking_has_legacy_unassigned_payments(booking_id: int) -> bool:
    return PaymentReceived.objects.filter(
        booking_id=booking_id, approved=True, service__isnull=True
    ).exists()


def booking_all_services_fully_approved(booking_id: int) -> bool:
    """
    New rule gate for service-linked flows:
    - If a booking has assigned services in BookingService,
      require no pending rows for those service_ids and at least 1 approved row per service.
    Legacy unassigned payments do not satisfy per-service requirements.
    """
    service_ids = list(
        BookingService.objects.filter(booking_id=booking_id)
        .values_list("service_id", flat=True)
        .distinct()
    )
    if not service_ids:
        return False

    if PaymentReceived.objects.filter(booking_id=booking_id, service_id__in=service_ids, approved=False).exists():
        return False

    for sid in service_ids:
        if not PaymentReceived.objects.filter(booking_id=booking_id, service_id=sid, approved=True).exists():
            return False

    return True


def _svc_gst_tcs_for_booking_service(booking_id: int, service_code: str) -> Tuple[Decimal, Decimal]:
    """
    Your exact GST/TCS rules (service-table based):

    GST:
      - Ticket: always (cash or non-cash)
      - Other services: GST only if NON-CASH (cash => 0)
      - GST = 18% * (sales_amount - purchase_amount)

    TCS:
      - Only Hotel / Sightseeing / Transfer
      - Only if NON-CASH AND international (travel_type == 'international')
      - TCS = sales_amount * 5%
    """
    model = SERVICE_MODEL_MAP.get(service_code)
    z = Decimal("0")
    if not model:
        return z, z

    qs = model.objects.filter(booking_id=booking_id).select_related("mode")

    gst_rate = Decimal("0.18")
    tcs_rate = Decimal("0.05")

    gst_total = Decimal("0")
    tcs_total = Decimal("0")

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
# Staff Filtered Summary
# totals = ONLY employee attributable (service-linked) contributions
# legacy bookings are NOT included in totals (cannot attribute)
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
        "service_summary": {},  # keep same behavior (service-linked only)
        "legacy_bookings_visible": 0,
    }

    # ------------------------------------------------------------
    # (A) NEW / SERVICE-LINKED totals: attributable to employee
    # ------------------------------------------------------------
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
            assignments = assignments.filter(booking__booking_date__month=datetime.strptime(month, "%B").month)
        except ValueError:
            pass
    if client:
        assignments = assignments.filter(booking__client_id=client)

    # service filter (applies only to service-linked side)
    if service:
        assignments = assignments.filter(service__name=service)

    seen_booking_ids = set()
    legacy_seen = set()

    for a in assignments:
        booking = a.booking

        # if legacy-unassigned exists, skip from attributable staff totals
        if PaymentReceived.objects.filter(booking_id=booking.id, approved=True, service__isnull=True).exists():
            legacy_seen.add(booking.id)
            continue

        if not booking_all_services_fully_approved(booking.id):
            continue

        svc = a.service
        scode = _svc_code(svc)

        # supplier filter depends on service table
        if supplier:
            model = SERVICE_MODEL_MAP.get(scode)
            if not model or not model.objects.filter(booking_id=booking.id, supplier_id=supplier).exists():
                continue

        sales_total, sales_cash, sales_non_cash, discount_total = _svc_sales_totals_from_payments(booking.id, svc.id)
        if sales_total <= 0:
            continue

        purch_total, purch_cash, purch_non_cash = _svc_purchase_totals(booking.id, scode)
        gst_amt, tcs_amt = _svc_gst_tcs_for_booking_service(booking.id, scode)

        # TCS reduces non-cash sales
        sales_non_cash_net = sales_non_cash - tcs_amt

        # Your rule: DO NOT deduct GST from cash profit at all.
        profit_cash = sales_cash - purch_cash
        profit_non_cash = (sales_non_cash_net - purch_non_cash) - gst_amt

        results["totals"]["sales_cash"] += float(sales_cash)
        results["totals"]["sales_non_cash"] += float(sales_non_cash_net)
        results["totals"]["purchase_cash"] += float(purch_cash)
        results["totals"]["purchase_non_cash"] += float(purch_non_cash)
        results["totals"]["profit_cash"] += float(profit_cash)
        results["totals"]["profit_non_cash"] += float(profit_non_cash)
        results["totals"]["discount"] += float(discount_total)

        seen_booking_ids.add(booking.id)

        # service_summary remains service-linked only (unchanged)
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

    # ------------------------------------------------------------
    # (B) LEGACY totals: add into KPI cards ONLY
    #     (not into service_summary)
    # ------------------------------------------------------------
    legacy_bookings = (
        Booking.objects
        .filter(
            Q(created_by=user) |
            Q(id__in=BookingService.objects.filter(assigned_to=user).values_list("booking_id", flat=True))
        )
        .filter(id__in=PaymentReceived.objects.filter(approved=True, service__isnull=True)
                .values_list("booking_id", flat=True).distinct())
        .select_related("client")
        .distinct()
    )

    # same booking-level filters
    if year:
        legacy_bookings = legacy_bookings.filter(booking_date__year=year)
    if month:
        try:
            legacy_bookings = legacy_bookings.filter(booking_date__month=datetime.strptime(month, "%B").month)
        except ValueError:
            pass
    if client:
        legacy_bookings = legacy_bookings.filter(client_id=client)

    # supplier + service filter:
    # legacy payments have no service mapping, so we can only apply supplier/service
    # safely when booking has exactly one service in BookingService.
    # Otherwise we ignore these filters for legacy to avoid wrong exclusion.
    if supplier or service:
        filtered_ids = []
        for b in legacy_bookings:
            bs = list(BookingService.objects.filter(booking_id=b.id).select_related("service"))
            if len(bs) == 1:
                svc_obj = bs[0].service
                if service and svc_obj.name != service:
                    continue
                if supplier:
                    scode = _svc_code(svc_obj)
                    model = SERVICE_MODEL_MAP.get(scode)
                    if not model or not model.objects.filter(booking_id=b.id, supplier_id=supplier).exists():
                        continue
                filtered_ids.append(b.id)
            else:
                # multi-service legacy: cannot safely filter by supplier/service
                # keep it (so totals remain inclusive & honest)
                filtered_ids.append(b.id)
        legacy_bookings = legacy_bookings.filter(id__in=filtered_ids)

    for b in legacy_bookings:
        sales_total, sales_cash, sales_non_cash, discount_total = _legacy_booking_sales_from_payments(b.id)
        if sales_total <= 0:
            continue

        purchase_total = to_decimal(getattr(b, "purchase_total", 0))

        # no cash/non-cash purchase split exists for legacy => put into non-cash bucket
        purch_cash = Decimal("0")
        purch_non_cash = purchase_total

        profit_cash = sales_cash - purch_cash
        profit_non_cash = sales_non_cash - purch_non_cash

        results["totals"]["sales_cash"] += float(sales_cash)
        results["totals"]["sales_non_cash"] += float(sales_non_cash)
        results["totals"]["purchase_cash"] += float(purch_cash)
        results["totals"]["purchase_non_cash"] += float(purch_non_cash)
        results["totals"]["profit_cash"] += float(profit_cash)
        results["totals"]["profit_non_cash"] += float(profit_non_cash)
        results["totals"]["discount"] += float(discount_total)

        legacy_seen.add(b.id)

    # bookings count on KPI cards: include both sets
    results["totals"]["bookings"] = len(seen_booking_ids.union(legacy_seen))
    results["legacy_bookings_visible"] = len(legacy_seen)

    return JsonResponse(results)

# ---------------------------
# Staff Bookings Report
# - Always includes bookings where user is creator OR assigned
# - If booking is legacy-unassigned:
#     - Table totals show booking-level totals (exact)
#     - Modal shows one row "LEGACY / Unassigned" with gst/tcs = null
# - Else:
#     - Table totals show user-only service totals (attributable)
#     - Modal: creator sees all; else only user's services
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
        .filter(id__in=PaymentReceived.objects.filter(approved=True).values_list("booking_id", flat=True).distinct())
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
        user_is_creator = (booking.created_by_id == user.id)
        legacy = booking_has_legacy_unassigned_payments(booking.id)

        # --------
        # LEGACY booking handling (exact booking totals, NA per-service)
        # --------
        if legacy:
            # booking-level exact
            sales_total, sales_cash, sales_non_cash, discount_total = _legacy_booking_sales_from_payments(booking.id)
            if sales_total <= 0:
                continue

            purchase_total = to_decimal(getattr(booking, "purchase_total", 0))
            # split purchase? not possible reliably at booking level -> keep as TOTAL in non-cash bucket
            # but your UI expects cash/non-cash. We’ll set cash purchase=0, non-cash=purchase_total.
            purch_cash = Decimal("0")
            purch_non_cash = purchase_total

            profit_cash = sales_cash - purch_cash
            profit_non_cash = sales_non_cash - purch_non_cash

            # modal: single legacy row (no GST/TCS)
            services_data = [{
                "service": "LEGACY / Unassigned",
                "mode": "Mixed",
                "sales_cash": float(sales_cash),
                "sales_non_cash": float(sales_non_cash),
                "sales_total": float(sales_total),
                "purchase_cash": float(purch_cash),
                "purchase_non_cash": float(purch_non_cash),
                "purchase_total": float(purchase_total),
                "profit_cash": float(profit_cash),
                "profit_non_cash": float(profit_non_cash),
                "profit_total": float(profit_cash + profit_non_cash),
                "gst": None,
                "tcs": None,
                "discount": float(discount_total),
                "entered_by": None,
            }]

            data.append({
                "booking_id": booking.booking_id,
                "booking_date": booking.booking_date.strftime("%d-%b-%Y") if booking.booking_date else "",
                "client_name": f"{booking.client.first_name} {booking.client.last_name}" if booking.client else "Unknown",
                "booking_created_by": booking.created_by.get_full_name() or booking.created_by.username,
                "i_created_this_booking": bool(user_is_creator),
                "is_legacy": True,

                "services": services_data,

                "totals": {
                    "sales_cash": float(sales_cash),
                    "sales_non_cash": float(sales_non_cash),
                    "purchase_cash": float(purch_cash),
                    "purchase_non_cash": float(purch_non_cash),
                    "profit_cash": float(profit_cash),
                    "profit_non_cash": float(profit_non_cash),
                    "discount": float(discount_total),
                },
            })
            continue

        # --------
        # NEW booking handling (service-linked)
        # --------
        if not booking_all_services_fully_approved(booking.id):
            continue

        # modal services list
        modal_bs = BookingService.objects.filter(booking_id=booking.id).select_related("service", "assigned_to")
        if not user_is_creator:
            modal_bs = modal_bs.filter(assigned_to=user)
        if service:
            modal_bs = modal_bs.filter(service__name=service)

        # totals services list (user-only)
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

            purch_total, purch_cash, purch_non_cash = _svc_purchase_totals(booking.id, scode)
            gst_amt, tcs_amt = _svc_gst_tcs_for_booking_service(booking.id, scode)

            sales_non_cash_net = sales_non_cash - tcs_amt

            # IMPORTANT per your requirement:
            # - No GST for cash side at all.
            # - Ticket GST is always computed, but still not deducted from cash profit.
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

        # table totals (user-only)
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
            gst_amt, tcs_amt = _svc_gst_tcs_for_booking_service(booking.id, scode)

            sales_non_cash_net = sales_non_cash - tcs_amt

            # no GST deduction on cash
            profit_cash = sales_cash - purch_cash
            profit_non_cash = (sales_non_cash_net - purch_non_cash) - gst_amt

            tot_sales_cash += sales_cash
            tot_sales_non_cash += sales_non_cash_net
            tot_purchase_cash += purch_cash
            tot_purchase_non_cash += purch_non_cash
            tot_profit_cash += profit_cash
            tot_profit_non_cash += profit_non_cash
            tot_discount += discount_total

        # if user has no contribution, hide booking row
        if (tot_sales_cash + tot_sales_non_cash) <= 0:
            continue

        data.append({
            "booking_id": booking.booking_id,
            "booking_date": booking.booking_date.strftime("%d-%b-%Y") if booking.booking_date else "",
            "client_name": f"{booking.client.first_name} {booking.client.last_name}" if booking.client else "Unknown",
            "booking_created_by": booking.created_by.get_full_name() or booking.created_by.username,
            "i_created_this_booking": bool(user_is_creator),
            "is_legacy": False,

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
