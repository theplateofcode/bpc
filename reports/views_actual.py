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
    Cash detection rule:
    mode is cash if its name is exactly 'cash' (case-insensitive).
    """
    if not mode or not getattr(mode, "name", None):
        return False
    return mode.name.strip().lower() == "cash"


# ---------------------------
# Legacy helpers (service is NULL)
# ---------------------------

def _legacy_booking_sales_from_payments(booking_id: int) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
    """
    Legacy booking-wise totals from approved payments where service is NULL.
    Returns (sales_total, sales_cash, sales_non_cash, discount_total)
    """
    qs = (
        PaymentReceived.objects
        .filter(booking_id=booking_id, approved=True, service__isnull=True)
        .select_related("mode")
    )
    if not qs.exists():
        z = Decimal("0")
        return z, z, z, z

    sales_total = sum(to_decimal(p.amount) for p in qs)
    sales_cash = sum(to_decimal(p.amount) for p in qs if is_cash_mode(p.mode))
    sales_non_cash = sales_total - sales_cash
    discount_total = sum(to_decimal(p.discount) for p in qs)

    return sales_total, sales_cash, sales_non_cash, discount_total


def _booking_is_legacy_only(booking_id: int) -> bool:
    """
    Legacy-only booking means:
      - it has approved payments with service NULL
      - and it has NO approved payments with service NOT NULL
    This avoids double counting when mixed data exists.
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

def _svc_purchase_totals(booking_id: int, service_code: str) -> Tuple[Decimal, Decimal, Decimal]:
    """
    Returns (purchase_total, purchase_cash, purchase_non_cash) for THIS booking + THIS service.
    Uses the service table's Mode (supplier-side).
    """
    model = SERVICE_MODEL_MAP.get(service_code)
    z = Decimal("0")
    if not model:
        return z, z, z

    total = model.objects.filter(booking_id=booking_id).aggregate(s=Sum("purchase_amount"))["s"] or z
    cash = (
        model.objects.filter(booking_id=booking_id, mode__name__iexact="cash")
        .aggregate(s=Sum("purchase_amount"))["s"]
        or z
    )
    non_cash = total - cash
    return to_decimal(total), to_decimal(cash), to_decimal(non_cash)


# ---------------------------
# Sales totals (payments table: customer-side actuals)
# ---------------------------

def _svc_sales_totals_from_payments(booking_id: int, service_id: int) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
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

def _svc_tax_totals_from_service_rows(booking_id: int, service_code: str) -> Tuple[Decimal, Decimal]:
    """
    Returns (gst_total, tcs_total) for THIS booking + THIS service, computed from service rows.

    GST rules:
      - Ticket: GST ALWAYS on (sales_amount - purchase_amount) * 18% (even cash)
      - Others: GST only if NON-CASH on that service row

    TCS rules:
      - Only for Hotel/Transfer/Sightseeing
      - Only if NON-CASH AND travel_type == 'international'
      - TCS = sales_amount * 5%
    """
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
            travel_type = getattr(obj, "travel_type", "") or ""
            is_international = travel_type.strip().lower() == "international"
            if (not row_is_cash) and is_international:
                tcs_total += (sales_amount * TCS_RATE)

    return gst_total, tcs_total


# ---------------------------
# Booking “fully approved” gate (new system)
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

    if PaymentReceived.objects.filter(
        booking_id=booking_id,
        service_id__in=service_ids,
        approved=False
    ).exists():
        return False

    for sid in service_ids:
        if not PaymentReceived.objects.filter(booking_id=booking_id, service_id=sid, approved=True).exists():
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
# (UPDATED: KPI totals + employee summary include legacy booking-wise)
# ---------------------------

@login_required
def filtered_actual_report(request):
    service = request.GET.get("service")
    employee = request.GET.get("employee")
    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    assignments = (
        BookingService.objects
        .select_related("booking", "booking__client", "booking__created_by", "service", "assigned_to")
        .filter(
            booking_id__in=PaymentReceived.objects.filter(approved=True)
            .values_list("booking_id", flat=True)
            .distinct()
        )
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
            "legacy_bookings": 0,
        },
        "service_summary": {},
        "employee_summary": {},
    }

    seen_booking_ids = set()
    legacy_seen_booking_ids = set()

    # ---------------------------
    # (A) New system (service-attributed)
    # ---------------------------
    for a in assignments:
        booking = a.booking
        svc = a.service
        service_code = _svc_code(svc)

        # ✅ If this booking is legacy-only, skip here to avoid wrong splits
        if _booking_is_legacy_only(booking.id):
            legacy_seen_booking_ids.add(booking.id)
            continue

        # Supplier filter: service-table supplier
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

        seen_booking_ids.add(booking.id)

        purch_total, purch_cash, purch_non_cash = _svc_purchase_totals(booking.id, service_code)
        gst_amt, tcs_amt = _svc_tax_totals_from_service_rows(booking.id, service_code)

        # TCS reduces NON-CASH sales
        sales_non_cash_net = sales_non_cash - tcs_amt

        # ✅ Your rule: NO GST in cash profit. GST subtract only from non-cash bucket.
        profit_cash = sales_cash - purch_cash
        profit_non_cash = (sales_non_cash_net - purch_non_cash) - gst_amt

        # Cards totals
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

        # Employee summary
        emp_name = a.assigned_to.get_full_name() or a.assigned_to.username
        edata = results["employee_summary"].setdefault(emp_name, {
            "sales_cash": 0.0, "sales_non_cash": 0.0,
            "purchase_cash": 0.0, "purchase_non_cash": 0.0,
            "profit_cash": 0.0, "profit_non_cash": 0.0,
            "discount": 0.0,
            "gst": 0.0, "tcs": 0.0,
            "legacy_bookings": 0,
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

    # ---------------------------
    # (B) Legacy-only bookings -> KPI totals + employee summary
    # ---------------------------
    legacy_bookings = (
        Booking.objects
        .filter(
            id__in=PaymentReceived.objects.filter(approved=True, service__isnull=True)
            .values_list("booking_id", flat=True)
            .distinct()
        )
        .select_related("client", "created_by")
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

    # Important:
    # - service/supplier filters cannot be applied safely
    # - employee filter is also not safely applicable to legacy multi-service
    # We include legacy in totals/summaries for correctness and visibility.
    for b in legacy_bookings:
        if not _booking_is_legacy_only(b.id):
            continue

        sales_total, sales_cash, sales_non_cash, discount_total = _legacy_booking_sales_from_payments(b.id)
        if sales_total <= 0:
            continue

        purchase_total = to_decimal(getattr(b, "purchase_total", 0))

        # No reliable split for legacy purchase => keep in NON-CASH bucket
        purch_cash = Decimal("0")
        purch_non_cash = purchase_total

        profit_cash = sales_cash - purch_cash
        profit_non_cash = sales_non_cash - purch_non_cash

        # KPI totals
        results["totals"]["sales_cash"] += float(sales_cash)
        results["totals"]["sales_non_cash"] += float(sales_non_cash)
        results["totals"]["purchase_cash"] += float(purch_cash)
        results["totals"]["purchase_non_cash"] += float(purch_non_cash)
        results["totals"]["profit_cash"] += float(profit_cash)
        results["totals"]["profit_non_cash"] += float(profit_non_cash)
        results["totals"]["discount"] += float(discount_total)

        # Employee summary attribution rule for legacy: booking.created_by
        legacy_owner = b.created_by
        emp_name = (legacy_owner.get_full_name() or legacy_owner.username) if legacy_owner else "Unknown"
        edata = results["employee_summary"].setdefault(emp_name, {
            "sales_cash": 0.0, "sales_non_cash": 0.0,
            "purchase_cash": 0.0, "purchase_non_cash": 0.0,
            "profit_cash": 0.0, "profit_non_cash": 0.0,
            "discount": 0.0,
            "gst": 0.0, "tcs": 0.0,
            "legacy_bookings": 0,
        })
        edata["sales_cash"] += float(sales_cash)
        edata["sales_non_cash"] += float(sales_non_cash)
        edata["purchase_cash"] += float(purch_cash)
        edata["purchase_non_cash"] += float(purch_non_cash)
        edata["profit_cash"] += float(profit_cash)
        edata["profit_non_cash"] += float(profit_non_cash)
        edata["discount"] += float(discount_total)
        edata["legacy_bookings"] += 1

        legacy_seen_booking_ids.add(b.id)

    # booking counts
    results["totals"]["bookings"] = len(seen_booking_ids.union(legacy_seen_booking_ids))
    results["totals"]["legacy_bookings"] = len(legacy_seen_booking_ids)

    # Add TOTAL rows to summaries (updated: sums legacy_bookings too if present)
    def add_total(block: Dict):
        base_keys = [
            "sales_cash", "sales_non_cash",
            "purchase_cash", "purchase_non_cash",
            "profit_cash", "profit_non_cash",
            "discount", "gst", "tcs",
        ]
        totals = {k: 0.0 for k in base_keys}
        legacy_cnt = 0

        for v in block.values():
            for k in base_keys:
                totals[k] += float(v.get(k, 0.0))
            legacy_cnt += int(v.get("legacy_bookings", 0))

        totals["legacy_bookings"] = legacy_cnt
        block["TOTAL"] = totals

    add_total(results["service_summary"])
    add_total(results["employee_summary"])

    return JsonResponse(results)


# ---------------------------
# Booking-wise Summary (Client Table)
# UPDATED: includes legacy bookings too
# ---------------------------

@login_required
def bookings_report(request):
    service = request.GET.get("service")
    employee = request.GET.get("employee")
    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    # Include any booking that has at least one approved payment (legacy or new)
    bookings = (
        Booking.objects
        .filter(
            id__in=PaymentReceived.objects.filter(approved=True)
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
        # keeping your old meaning here: created_by filter for booking table
        bookings = bookings.filter(created_by_id=employee)
    if client:
        bookings = bookings.filter(client_id=client)

    data = []

    for booking in bookings:
        # ---------------------------
        # Legacy-only booking row
        # ---------------------------
        if _booking_is_legacy_only(booking.id):
            # If service filter is applied, legacy bookings cannot match (no split exists)
            if service:
                continue

            sales_total, sales_cash, sales_non_cash, discount_total = _legacy_booking_sales_from_payments(booking.id)
            if sales_total <= 0:
                continue

            purchase_total = to_decimal(getattr(booking, "purchase_total", 0))

            # Legacy purchase split unknown => keep in non-cash bucket
            purch_cash = Decimal("0")
            purch_non_cash = purchase_total

            profit_cash = sales_cash - purch_cash
            profit_non_cash = sales_non_cash - purch_non_cash
            profit_total = profit_cash + profit_non_cash

            entered_by = booking.created_by.get_full_name() or booking.created_by.username

            # One pseudo service row so UI stays consistent
            services_data = [{
                "service": "LEGACY (Not split)",
                "mode": "NA",

                "sales_cash": float(sales_cash),
                "sales_non_cash": float(sales_non_cash),
                "sales_total": float(sales_total),

                "purchase_cash": float(purch_cash),
                "purchase_non_cash": float(purch_non_cash),
                "purchase_total": float(purchase_total),

                "profit_cash": float(profit_cash),
                "profit_non_cash": float(profit_non_cash),
                "profit_total": float(profit_total),

                "gst": 0.0,
                "tcs": 0.0,
                "discount": float(discount_total),
                "entered_by": entered_by,
            }]

            data.append({
                "booking_id": booking.booking_id,
                "booking_date": booking.booking_date.strftime("%d-%b-%Y") if booking.booking_date else "",
                "created_by": entered_by,
                "client_name": f"{booking.client.first_name} {booking.client.last_name}" if booking.client else "Unknown",
                "services": services_data,
                "totals": {
                    "sales_cash": float(sales_cash),
                    "sales_non_cash": float(sales_non_cash),
                    "purchase_cash": float(purch_cash),
                    "purchase_non_cash": float(purch_non_cash),
                    "profit_cash": float(profit_cash),
                    "profit_non_cash": float(profit_non_cash),
                    "total_profit": float(profit_total),
                    "discount": float(discount_total),
                    "gst": 0.0,
                    "tcs": 0.0,
                },
                "is_legacy": True,
            })
            continue

        # ---------------------------
        # New system booking row (service-attributed)
        # ---------------------------
        if not booking_all_services_fully_approved(booking.id):
            continue

        bs_qs = (
            BookingService.objects
            .filter(booking_id=booking.id)
            .select_related("service")
            .distinct()
        )

        # service filter (new system only)
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

            purch_total, purch_cash, purch_non_cash = _svc_purchase_totals(booking.id, service_code)
            gst_amt, tcs_amt = _svc_tax_totals_from_service_rows(booking.id, service_code)

            sales_non_cash_net = sales_non_cash - tcs_amt

            # ✅ no GST in cash profit; GST subtract from non-cash bucket
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
            "is_legacy": False,
        })

    return JsonResponse({"data": data})
