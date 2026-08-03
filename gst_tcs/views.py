from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.db.models import Q

from bookings.models import Booking
from django.contrib.auth import get_user_model

User = get_user_model()

PAGE_SIZE = 10


def to_float(val):
    try:
        return float(val or 0)
    except Exception:
        return 0.0


def base_queryset_closed(mode: str):
    """
    Base = CLOSED bookings only (status is FK => status__name).
    In TCS mode, we also remove "blank TCS" bookings at the DB level by requiring
    at least one qualifying international non-cash hotel/transfer/sightseeing row.
    """
    qs = (
        Booking.objects
        .filter(status__name__iexact="closed")
        .select_related("client", "created_by", "status")
        # get_tax_value() below reads the tcs_amount / sales_gst properties for
        # every row, so pull their service rows in one pass rather than per row.
        .with_service_rows()
        .distinct()
    )

    mode = (mode or "gst").lower()
    if mode == "tcs":
        # Qualifying services for TCS: international + non-cash
        # (Matches your tcs_amount property logic)
        tcs_exists = (
            Q(hotels__travel_type__iexact="international") & ~Q(hotels__mode__name__iexact="cash")
        ) | (
            Q(transfers__travel_type__iexact="international") & ~Q(transfers__mode__name__iexact="cash")
        ) | (
            Q(sightseeings__travel_type__iexact="international") & ~Q(sightseeings__mode__name__iexact="cash")
        )
        qs = qs.filter(tcs_exists).distinct()

    return qs


def get_tax_value(booking: Booking, mode: str) -> float:
    mode = (mode or "gst").lower()
    if mode == "tcs":
        return to_float(getattr(booking, "tcs_amount", 0))  # property
    return to_float(getattr(booking, "sales_gst", 0))       # property


@login_required
def gst_tcs_view(request, mode="gst"):
    mode = (mode or "gst").lower()
    if mode not in ("gst", "tcs"):
        mode = "gst"
    return render(request, "gst_tcs.html", {"mode": mode})


@login_required
def gst_tcs_filters(request, mode="gst"):
    """
    Returns dropdown options for filters.
    Dropdowns:
      - booking_id (exact)
      - employee (created_by user id)
      - client (client id)
      - tax_filter: all | gt0 | eq0
    """
    mode = (mode or "gst").lower()
    if mode not in ("gst", "tcs"):
        mode = "gst"

    qs = base_queryset_closed(mode).order_by("-booking_date", "-id")

    # Booking IDs
    booking_ids = list(qs.values_list("booking_id", flat=True).distinct())

    # Employees (created_by)
    user_ids = list(qs.values_list("created_by_id", flat=True).distinct())
    users = (
        User.objects
        .filter(id__in=[uid for uid in user_ids if uid is not None])
        .values("id", "first_name", "last_name", "username")
        .order_by("first_name", "last_name", "username")
    )
    employees = []
    for u in users:
        full = f"{u['first_name'] or ''} {u['last_name'] or ''}".strip()
        employees.append({"id": u["id"], "name": full or u["username"] or str(u["id"])})

    # Clients
    clients_qs = (
        qs.values("client_id", "client__first_name", "client__last_name")
        .distinct()
        .order_by("client__first_name", "client__last_name")
    )
    clients = []
    for c in clients_qs:
        nm = f"{c['client__first_name'] or ''} {c['client__last_name'] or ''}".strip() or "Unknown"
        clients.append({"id": c["client_id"], "name": nm})

    # Tax filter dropdown
    tax_filter_options = [
        {"value": "all", "label": "All"},
        {"value": "gt0", "label": "Has Tax (> 0)"},
        {"value": "eq0", "label": "No Tax (= 0)"},
    ]

    # In TCS mode: enforce non-blank by default
    default_tax_filter = "gt0" if mode == "tcs" else "all"

    return JsonResponse({
        "mode": mode,
        "booking_ids": booking_ids,
        "employees": employees,
        "clients": clients,
        "tax_filter_options": tax_filter_options,
        "default_tax_filter": default_tax_filter,
    })


@login_required
def gst_tcs_data(request, mode="gst"):
    """
    Data endpoint:
      - page (lazy load, 10)
      - booking_id (exact)
      - employee_id
      - client_id
      - tax_filter: all | gt0 | eq0   (Python-filtered because tax is property)
    """
    mode = (mode or "gst").lower()
    if mode not in ("gst", "tcs"):
        mode = "gst"

    try:
        page = int(request.GET.get("page", 1))
        if page < 1:
            page = 1
    except ValueError:
        page = 1

    booking_id = (request.GET.get("booking_id") or "").strip()
    employee_id = (request.GET.get("employee_id") or "").strip()
    client_id = (request.GET.get("client_id") or "").strip()
    tax_filter = (request.GET.get("tax_filter") or "").strip()  # all|gt0|eq0

    qs = base_queryset_closed(mode)

    # Apply dropdown filters (DB filters)
    if booking_id:
        qs = qs.filter(booking_id=booking_id)

    if employee_id:
        try:
            qs = qs.filter(created_by_id=int(employee_id))
        except ValueError:
            pass

    if client_id:
        try:
            qs = qs.filter(client_id=int(client_id))
        except ValueError:
            pass

    # Default ordering
    qs = qs.order_by("-booking_date", "-id")

    # DB pagination slice
    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE + 1
    items = list(qs[start:end])

    has_next = len(items) > PAGE_SIZE
    items = items[:PAGE_SIZE]

    # Build rows (compute tax property)
    rows = []
    for b in items:
        created_by = "Unknown"
        if b.created_by:
            created_by = (b.created_by.get_full_name() or b.created_by.username or "Unknown").strip()

        client_name = "Unknown"
        if b.client:
            client_name = f"{b.client.first_name or ''} {b.client.last_name or ''}".strip() or "Unknown"

        rows.append({
            "booking_id": b.booking_id,
            "booking_date": b.booking_date.strftime("%d-%b-%Y") if b.booking_date else "",
            "created_by": created_by,
            "client_name": client_name,
            "tax": get_tax_value(b, mode),
        })

    # Enforce: in TCS mode, never show blanks
    # (even if edge cases slip through DB existence filter)
    if mode == "tcs":
        rows = [r for r in rows if r["tax"] > 0]

    # Apply tax_filter dropdown (Python filter)
    if tax_filter == "gt0":
        rows = [r for r in rows if r["tax"] > 0]
    elif tax_filter == "eq0":
        rows = [r for r in rows if r["tax"] == 0]

    return JsonResponse({
        "mode": mode,
        "page": page,
        "page_size": PAGE_SIZE,
        "has_next": has_next,
        "rows": rows,
    })
