# payments/views.py
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Tuple

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Sum, Q
from django.http import HttpResponseBadRequest, HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string

from bookings.models import Booking, BookingService
from services.models import (
    ServiceList,
    Hotel, Insurance, Passport, SightSeeing, Ticket, Transfer, Visa
)
from .models import PaymentReceived, Mode
from .forms import ModeOfPaymentForm

User = get_user_model()
ACCOUNTS_GROUP_NAME = "Accounts"  # change if needed


# ---------------------------
# Role / access helpers
# ---------------------------

def is_owner_or_admin(user):
    return user.is_authenticated and getattr(user, "role", "") in ["OWNER", "ADMIN"]


def is_accounts(user):
    return (
        user.is_superuser
        or user.groups.filter(name=ACCOUNTS_GROUP_NAME).exists()
        or getattr(user, "role", "") in ["ACCOUNTANT", "OWNER", "ADMIN"]
    )


# ---------------------------
# Mode of Payment CRUD (OWNER/ADMIN)
# ---------------------------

@login_required
@user_passes_test(is_owner_or_admin)
def modes_of_payment(request):
    modes = Mode.objects.all().order_by("name")
    return render(request, "modes_of_payment.html", {"modes": modes})


@login_required
@user_passes_test(is_owner_or_admin)
def create_mode(request):
    if request.method == "POST":
        form = ModeOfPaymentForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("modes_of_payment")
    else:
        form = ModeOfPaymentForm()
    return render(request, "forms/mode_form.html", {"form": form})


@login_required
@user_passes_test(is_owner_or_admin)
def update_mode(request, pk):
    mode = get_object_or_404(Mode, pk=pk)
    if request.method == "POST":
        form = ModeOfPaymentForm(request.POST, instance=mode)
        if form.is_valid():
            form.save()
            return redirect("modes_of_payment")
    else:
        form = ModeOfPaymentForm(instance=mode)
    return render(request, "forms/mode_form.html", {"form": form})


@login_required
@user_passes_test(is_owner_or_admin)
def delete_mode(request, pk):
    mode = get_object_or_404(Mode, pk=pk)
    if request.method == "POST":
        mode.delete()
        return redirect("modes_of_payment")
    return render(request, "payments/mode_confirm_delete.html", {"mode": mode})


# ---------------------------
# Service mapping for targets
# ---------------------------

SERVICE_MODEL_MAP = {
    "hotel": Hotel,
    "insurance": Insurance,
    "passport": Passport,
    "sightseeing": SightSeeing,
    "ticket": Ticket,
    "transfer": Transfer,
    "visa": Visa,
}

# TCS applies only on these (per your Booking.tcs_amount property logic)
TCS_ELIGIBLE_CODES = {"hotel", "transfer", "sightseeing"}

PAISE = Decimal("0.01")


def _q2(x: Decimal) -> Decimal:
    """Quantize to 2 decimals (₹ paise) with normal rounding."""
    return (x or Decimal("0")).quantize(PAISE, rounding=ROUND_HALF_UP)


def _norm_service_code(svc: ServiceList) -> str:
    return (svc.code or svc.name or "").strip().lower().replace(" ", "")


def _assert_user_assigned(request, booking_id: int, service_id: int) -> None:
    ok = BookingService.objects.filter(
        booking_id=booking_id,
        service_id=service_id,
        assigned_to=request.user
    ).exists()
    if not ok:
        raise PermissionError("You are not assigned to this service for this booking.")


def _service_sales_target_by_code(booking_id: int, service_code: str) -> Decimal:
    """
    Returns sales_amount sum for THIS booking & service_code.
    IMPORTANT: this is only service sales (no TCS).
    """
    model = SERVICE_MODEL_MAP.get(service_code)
    if not model:
        return Decimal("0.00")
    agg = model.objects.filter(booking_id=booking_id).aggregate(s=Sum("sales_amount"))
    return _q2(Decimal(str(agg["s"] or 0)))


def _service_payments_totals(booking_id: int, service_id: int) -> Tuple[Decimal, Decimal]:
    """
    Returns (approved_sum, pending_sum) for booking+service (service FK).
    """
    approved = (
        PaymentReceived.objects
        .filter(booking_id=booking_id, service_id=service_id, approved=True)
        .aggregate(s=Sum("amount"))["s"] or 0
    )
    pending = (
        PaymentReceived.objects
        .filter(booking_id=booking_id, service_id=service_id, approved=False)
        .aggregate(s=Sum("amount"))["s"] or 0
    )
    return _q2(Decimal(str(approved))), _q2(Decimal(str(pending)))


def _booking_tcs_total(booking: Booking) -> Decimal:
    """
    Uses your @property Booking.tcs_amount.
    That property already enforces:
    - International only
    - Non-cash only
    - Only hotel+transfer+sightseeing
    """
    return _q2(Decimal(str(getattr(booking, "tcs_amount", 0) or 0)))


def _eligible_sales_total_for_tcs(booking: Booking) -> Decimal:
    """
    Compute sales base for TCS allocation.
    We intentionally match Booking.tcs_amount eligibility as closely as we can
    WITHOUT re-implementing your entire property filters.
    For perfect correctness, we compute from those three models with the SAME filters.
    """
    hotel_sales = booking.hotels.exclude(mode__name__iexact="cash").filter(
        travel_type__iexact="international"
    ).aggregate(total=Sum("sales_amount"))["total"] or 0

    transfer_sales = booking.transfers.exclude(mode__name__iexact="cash").filter(
        travel_type__iexact="international"
    ).aggregate(total=Sum("sales_amount"))["total"] or 0

    sightseeing_sales = booking.sightseeings.exclude(mode__name__iexact="cash").filter(
        travel_type__iexact="international"
    ).aggregate(total=Sum("sales_amount"))["total"] or 0

    return _q2(Decimal(str(hotel_sales)) + Decimal(str(transfer_sales)) + Decimal(str(sightseeing_sales)))


def _service_sales_base_for_tcs(booking: Booking, service_code: str) -> Decimal:
    """
    Service sales base used for TCS allocation (matches Booking.tcs_amount filters).
    Only meaningful for hotel/transfer/sightseeing; otherwise 0.
    """
    if service_code not in TCS_ELIGIBLE_CODES:
        return Decimal("0.00")

    if service_code == "hotel":
        total = booking.hotels.exclude(mode__name__iexact="cash").filter(
            travel_type__iexact="international"
        ).aggregate(total=Sum("sales_amount"))["total"] or 0
        return _q2(Decimal(str(total)))

    if service_code == "transfer":
        total = booking.transfers.exclude(mode__name__iexact="cash").filter(
            travel_type__iexact="international"
        ).aggregate(total=Sum("sales_amount"))["total"] or 0
        return _q2(Decimal(str(total)))

    # sightseeing
    total = booking.sightseeings.exclude(mode__name__iexact="cash").filter(
        travel_type__iexact="international"
    ).aggregate(total=Sum("sales_amount"))["total"] or 0
    return _q2(Decimal(str(total)))


def _service_target_with_tcs(booking: Booking, service: ServiceList) -> Decimal:
    """
    Service-wise target INCLUDING TCS allocation with PERFECT reconciliation.

    Rule:
    - Total TCS = booking.tcs_amount (already computed by your Booking property)
    - Allocate ONLY among eligible services (hotel/transfer/sightseeing),
      proportionally by their eligible sales base (same filters).
    - Use remainder method:
      * round each share to 2 decimals
      * assign any rounding remainder to the LAST eligible service (by deterministic order)
      => Sum(service_targets) includes EXACT booking TCS amount.
    """
    service_code = _norm_service_code(service)

    # base sales target for this service (full sales, not filtered) — this is what you were already showing
    service_sales_total = _service_sales_target_by_code(booking.id, service_code)

    # if no TCS, or non-eligible, just return sales
    tcs_total = _booking_tcs_total(booking)
    if tcs_total == 0 or service_code not in TCS_ELIGIBLE_CODES:
        return service_sales_total

    eligible_total = _eligible_sales_total_for_tcs(booking)
    if eligible_total == 0:
        # TCS says 0 anyway in that case, but safe fallback
        return service_sales_total

    # Determine a stable eligible ordering for remainder assignment
    eligible_order = ["hotel", "transfer", "sightseeing"]

    # Precompute rounded shares for eligible services
    shares = {}
    running = Decimal("0.00")
    for code in eligible_order:
        base = _service_sales_base_for_tcs(booking, code)
        if base == 0:
            shares[code] = Decimal("0.00")
            continue
        share = _q2((base / eligible_total) * tcs_total)
        shares[code] = share
        running += share

    # Remainder fix: assign remainder to last eligible code
    remainder = _q2(tcs_total - running)
    if remainder != 0:
        last_code = eligible_order[-1]
        shares[last_code] = _q2(shares.get(last_code, Decimal("0.00")) + remainder)

    # Add this service's share
    tcs_share = shares.get(service_code, Decimal("0.00"))
    return _q2(service_sales_total + tcs_share)


def _compute_discount(target: Decimal, received_total: Decimal) -> Decimal:
    """
    Settlement balance (what's left to settle):
    +ve => shortfall
    -ve => overpayment
    """
    return _q2(target - received_total)


def _auto_close_booking_if_all_services_settled(booking: Booking) -> None:
    """
    Close booking ONLY after accountant approvals when every service assigned in BookingService
    has an approved settlement row (is_full=True, approved=True).
    """
    service_ids = list(
        BookingService.objects.filter(booking=booking).values_list("service_id", flat=True)
    )
    if not service_ids:
        return

    for sid in service_ids:
        settled = PaymentReceived.objects.filter(
            booking_id=booking.id,
            service_id=sid,
            is_full=True,
            approved=True,
        ).exists()
        if not settled:
            return

    booking.status_id = 4  # your "closed" status
    booking.save(update_fields=["status_id"])


# ---------------------------
# Employee: Payments Home (service-wise)
# ---------------------------

@login_required
def payments_home(request):
    """
    Show rows ONLY for services assigned to this user.
    Each row = (booking, service) with target INCLUDING allocated TCS (if eligible).
    """
    assignments = (
        BookingService.objects
        .filter(assigned_to=request.user)
        .select_related("booking", "booking__client", "service")
        .exclude(booking__status_id=3)
        .order_by("booking__tour_start_date", "booking__booking_date")
    )

    rows = []
    for a in assignments:
        b = a.booking
        svc = a.service

        # ✅ if settlement already created (pending OR approved), hide from employee list
        if PaymentReceived.objects.filter(
            booking_id=b.id,
            service_id=svc.id,
            is_full=True,
        ).exists():
            continue

        target = _service_target_with_tcs(b, svc)  # ✅ includes TCS allocation
        approved, pending = _service_payments_totals(b.id, svc.id)
        received_total = _q2(approved + pending)
        remaining = _q2(max(Decimal("0.00"), target - received_total))

        rows.append({
            "booking": b,
            "service": svc,
            "service_id": svc.id,
            "service_label": svc.name,
            "service_code": _norm_service_code(svc),
            "target": int(target),                 # keep your UI behavior
            "approved": int(approved),
            "pending": int(pending),
            "remaining": int(remaining),
        })

    modes = Mode.objects.all().order_by("name")
    return render(request, "payments/home.html", {"rows": rows, "modes": modes})


# ---------------------------
# Employee: Details modal (service-wise)
# ---------------------------

@login_required
def payment_details_modal(request, booking_id: int, service_id: int):
    booking = get_object_or_404(Booking, id=booking_id)
    service = get_object_or_404(ServiceList, id=service_id)

    try:
        _assert_user_assigned(request, booking.id, service.id)
    except PermissionError as e:
        return HttpResponseBadRequest(str(e))

    items = (
        PaymentReceived.objects
        .filter(booking_id=booking.id, service_id=service.id)
        .select_related("received_by", "mode")
        .order_by("-created_at")
    )
    modes = Mode.objects.all().order_by("name")

    html = render_to_string("payments/_details.html", {
        "booking": booking,
        "service": service,
        "items": items,
        "modes": modes,
    }, request=request)
    return HttpResponse(html)


# ---------------------------
# Employee: Add installment (service-wise)
# ---------------------------

@login_required
def payment_add_installment(request, booking_id: int, service_id: int):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    booking = get_object_or_404(Booking, id=booking_id)
    service = get_object_or_404(ServiceList, id=service_id)

    try:
        _assert_user_assigned(request, booking.id, service.id)
    except PermissionError as e:
        return HttpResponseBadRequest(str(e))

    amount = request.POST.get("amount")
    mode_id = request.POST.get("mode")
    remarks = request.POST.get("remarks", "")
    doc = request.FILES.get("document")

    try:
        amount_val = _q2(Decimal(amount or "0"))
        if amount_val <= 0:
            return HttpResponseBadRequest("Amount must be > 0.")
    except Exception:
        return HttpResponseBadRequest("Invalid amount.")

    mode = get_object_or_404(Mode, id=mode_id)

    PaymentReceived.objects.create(
        booking=booking,
        service=service,
        mode=mode,
        amount=amount_val,
        received_by=request.user,
        document=doc,
        remarks=remarks,
        sent_for_approval=True,
        approved=False,
    )

    if request.headers.get("HX-Request") or request.headers.get("Hx-Request"):
        return payment_details_modal(request, booking_id=booking.id, service_id=service.id)

    return redirect("payments_home")


# ---------------------------
# Employee: Mark full (service-wise, accountant-approved)
# ---------------------------

@login_required
def payment_mark_full(request, booking_id: int, service_id: int):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    booking = get_object_or_404(Booking, id=booking_id)
    service = get_object_or_404(ServiceList, id=service_id)

    try:
        _assert_user_assigned(request, booking.id, service.id)
    except PermissionError as e:
        return HttpResponseBadRequest(str(e))

    # ✅ target now includes TCS allocation (perfect reconciliation)
    target = _service_target_with_tcs(booking, service)

    approved, pending = _service_payments_totals(booking.id, service.id)
    received_total = _q2(approved + pending)

    discount = _compute_discount(target=target, received_total=received_total)

    PaymentReceived.objects.create(
        booking=booking,
        service=service,
        mode=Mode.objects.first(),  # ideally a dedicated "Settlement/Adjustment" mode
        amount=Decimal("0.00"),
        received_by=request.user,
        remarks=f"Marked as fully received ({service.name})",
        is_full=True,
        discount=discount,          # + shortfall, - overpayment
        sent_for_approval=True,
        approved=False,
    )

    return HttpResponse("")


# ---------------------------
# Accounts: Approvals
# ---------------------------

@login_required
@user_passes_test(is_accounts)
def payment_approvals(request):
    items = (
        PaymentReceived.objects
        .filter(sent_for_approval=True, approved=False)
        .select_related("booking", "booking__client", "received_by", "mode", "service")
        .order_by("created_at")
    )
    return render(request, "payments/approvals.html", {"items": items})


@login_required
@user_passes_test(is_accounts)
def payment_approve(request, pk: int):
    item = get_object_or_404(PaymentReceived, pk=pk)
    item.approve(request.user)

    # after approval, attempt auto-close booking when all services have approved settlement
    try:
        _auto_close_booking_if_all_services_settled(item.booking)
    except Exception:
        pass

    if request.headers.get("HX-Request") or request.headers.get("Hx-Request"):
        return HttpResponse(f'<tr id="payrow-{item.id}" class="flash-approved"></tr>')

    return redirect("approvals")


@login_required
@user_passes_test(is_accounts)
def payment_reject(request, pk: int):
    item = get_object_or_404(PaymentReceived, pk=pk)
    item.delete()

    if request.headers.get("HX-Request") or request.headers.get("Hx-Request"):
        return HttpResponse("")

    return redirect("approvals")


from decimal import Decimal
from django.db.models import Sum, Q

from services.models import Hotel, Transfer, SightSeeing, Ticket, Visa, Insurance, Passport


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
    # PaymentReceived.service is likely ServiceList with .code
    return (getattr(service_obj, "code", "") or getattr(service_obj, "name", "") or "").strip().lower().replace(" ", "")


def _money(val) -> Decimal:
    try:
        return Decimal(str(val or 0))
    except Exception:
        return Decimal("0")


def _target_sales_for_queryset(payments_qs) -> Decimal:
    """
    Target = SUM(service_table.sales_amount) for the bookings+service-types present in payments_qs.
    This is a practical “expected sales” baseline for accountants.
    """
    booking_ids = list(payments_qs.values_list("booking_id", flat=True).distinct())
    if not booking_ids:
        return Decimal("0")

    # Collect which service-types are present in the qs (ticket/hotel/visa/etc.)
    service_objs = payments_qs.select_related("service").values_list("service__id", "service__code", "service__name").distinct()

    codes = set()
    for _, code, name in service_objs:
        scode = (code or name or "").strip().lower().replace(" ", "")
        if scode:
            codes.add(scode)

    total = Decimal("0")
    for scode in codes:
        model = SERVICE_MODEL_MAP.get(scode)
        if not model:
            continue

        agg = model.objects.filter(booking_id__in=booking_ids).aggregate(s=Sum("sales_amount"))["s"]
        total += _money(agg)

    return total




from decimal import Decimal
from typing import Dict, Tuple, Iterable

from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.shortcuts import render

from payments.models import PaymentReceived
from services.models import Hotel, Transfer, SightSeeing, Ticket, Visa, Insurance, Passport


# ---------------------------
# helpers
# ---------------------------

def _money(v) -> Decimal:
    try:
        return Decimal(str(v or 0))
    except Exception:
        return Decimal("0")


def _svc_code(service_obj) -> str:
    # PaymentReceived.service is your ServiceList (probably has .code)
    return (getattr(service_obj, "code", "") or getattr(service_obj, "name", "") or "") \
        .strip().lower().replace(" ", "")


SERVICE_MODEL_MAP = {
    "hotel": Hotel,
    "transfer": Transfer,
    "sightseeing": SightSeeing,
    "ticket": Ticket,
    "visa": Visa,
    "insurance": Insurance,
    "passport": Passport,
}


def _build_targets_for_rows(rows: Iterable[PaymentReceived]) -> Dict[Tuple[int, str], Decimal]:
    """
    Build target sales map:
        key = (booking_id, service_code)
        value = sum(service_table.sales_amount) for that booking_id in that model
    We intentionally use booking_id + service_code (service type), because your service tables
    are per-type tables and generally do not store ServiceList FK.
    """
    # group booking_ids by service_code
    by_code: Dict[str, set[int]] = {}
    for p in rows:
        code = _svc_code(p.service)
        if not code:
            continue
        by_code.setdefault(code, set()).add(p.booking_id)

    targets: Dict[Tuple[int, str], Decimal] = {}
    for code, booking_ids in by_code.items():
        model = SERVICE_MODEL_MAP.get(code)
        if not model or not booking_ids:
            continue

        # sum sales_amount per booking_id
        qs = (
            model.objects
            .filter(booking_id__in=list(booking_ids))
            .values("booking_id")
            .annotate(target=Sum("sales_amount"))
        )
        for row in qs:
            bid = row["booking_id"]
            targets[(bid, code)] = _money(row["target"])

    return targets


def _build_received_aggregates(rows: Iterable[PaymentReceived]) -> Dict[Tuple[int, int], Dict[str, Decimal]]:
    """
    Build received totals map:
        key = (booking_id, service_id)
        value = {"approved": sum(approved amounts), "pending": sum(pending amounts), "all": sum(all)}
    Uses PaymentReceived data only.
    """
    pairs = set()
    for p in rows:
        if p.booking_id and p.service_id:
            pairs.add((p.booking_id, p.service_id))

    if not pairs:
        return {}

    booking_ids = sorted({b for b, _ in pairs})
    service_ids = sorted({s for _, s in pairs})

    # aggregate on all PaymentReceived for these booking/service combos
    agg_qs = (
        PaymentReceived.objects
        .filter(booking_id__in=booking_ids, service_id__in=service_ids)
        .values("booking_id", "service_id")
        .annotate(
            approved_sum=Sum("amount", filter=Q(approved=True)),
            pending_sum=Sum("amount", filter=Q(approved=False)),
            all_sum=Sum("amount"),
            approved_disc=Sum("discount", filter=Q(approved=True)),
            pending_disc=Sum("discount", filter=Q(approved=False)),
        )
    )

    out: Dict[Tuple[int, int], Dict[str, Decimal]] = {}
    for r in agg_qs:
        key = (r["booking_id"], r["service_id"])
        out[key] = {
            "approved": _money(r["approved_sum"]),
            "pending": _money(r["pending_sum"]),
            "all": _money(r["all_sum"]),
            "approved_disc": _money(r["approved_disc"]),
            "pending_disc": _money(r["pending_disc"]),
        }
    return out


# ---------------------------
# Accountant dashboard (default = pending + per-row targets)
# ---------------------------

@login_required
def accountant_dashboard(request):
    if not is_accounts(request.user):
        return render(request, "payments/accountant_dashboard.html", {"payments": []})

    base_qs = (
        PaymentReceived.objects
        .select_related("booking", "booking__client", "received_by", "mode", "service")
        .all()
    )

    client = request.GET.get("client", "")
    status = request.GET.get("status", "pending")  # ✅ default pending
    order = request.GET.get("order", "desc")

    # client filter (applies to everything incl KPIs)
    if client:
        base_qs = base_qs.filter(
            Q(booking__client__first_name__icontains=client)
            | Q(booking__client__last_name__icontains=client)
        )

    # status filter for the table list
    qs = base_qs
    if status == "approved":
        qs = qs.filter(approved=True)
    elif status == "pending":
        qs = qs.filter(approved=False)
    # else: treat anything else as "all"

    qs = qs.order_by("created_at") if order == "asc" else qs.order_by("-created_at")

    # We need the rows to compute targets/received maps
    rows = list(qs)

    # ---------------------------
    # Per-row computations
    # ---------------------------
    targets_map = _build_targets_for_rows(rows)              # (booking_id, service_code) -> target_sales
    received_map = _build_received_aggregates(rows)          # (booking_id, service_id) -> approved/pending/all

    for p in rows:
        code = _svc_code(p.service)
        target = targets_map.get((p.booking_id, code), Decimal("0"))

        rec = received_map.get((p.booking_id, p.service_id), {})
        approved_received = rec.get("approved", Decimal("0"))
        pending_received = rec.get("pending", Decimal("0"))
        total_received = rec.get("all", Decimal("0"))

        remaining = target - approved_received
        if remaining < 0:
            remaining = Decimal("0")

        if target > 0:
            collection_pct = (approved_received / target) * Decimal("100")
        else:
            collection_pct = Decimal("0")

        # attach fields for template columns
        p.target_sales = target
        p.approved_received = approved_received
        p.pending_received = pending_received
        p.total_received = total_received
        p.remaining_to_collect = remaining
        p.collection_pct = collection_pct

        # (optional but useful) discount aggregation context
        p.approved_discount_total = rec.get("approved_disc", Decimal("0"))
        p.pending_discount_total = rec.get("pending_disc", Decimal("0"))

    # ---------------------------
    # Dashboard KPIs (on base_qs, not just filtered list)
    # ---------------------------
    approved_amount = _money(base_qs.filter(approved=True).aggregate(s=Sum("amount"))["s"])
    pending_amount = _money(base_qs.filter(approved=False).aggregate(s=Sum("amount"))["s"])

    approved_count = base_qs.filter(approved=True).count()
    pending_count = base_qs.filter(approved=False).count()
    total_count = base_qs.count()

    # KPI target = sum of per-row targets for the CURRENT LIST rows (more honest),
    # and also a global target for all visible rows in base_qs is usually too expensive.
    # This is the most useful operational KPI: “what is target for what I am looking at”.
    list_target_sales = sum((getattr(p, "target_sales", Decimal("0")) for p in rows), Decimal("0"))
    list_approved_received = sum((getattr(p, "approved_received", Decimal("0")) for p in rows), Decimal("0"))
    list_remaining = list_target_sales - list_approved_received
    if list_remaining < 0:
        list_remaining = Decimal("0")

    if list_target_sales > 0:
        list_collection_pct = (list_approved_received / list_target_sales) * Decimal("100")
    else:
        list_collection_pct = Decimal("0")

    return render(
        request,
        "payments/accountant_dashboard.html",
        {
            "payments": rows,  # rows list with attached computed fields
            "client": client,
            "status": status,
            "order": order,

            "kpi": {
                "approved_amount": approved_amount,
                "pending_amount": pending_amount,
                "approved_count": approved_count,
                "pending_count": pending_count,
                "total_count": total_count,

                # list-context KPIs (what they are approving right now)
                "list_target_sales": list_target_sales,
                "list_approved_received": list_approved_received,
                "list_remaining": list_remaining,
                "list_collection_pct": list_collection_pct,
            },
        },
    )
