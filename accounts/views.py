from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.generic import ListView
from django.utils.decorators import method_decorator
from django.http import JsonResponse

from services.models import Ticket, Visa, Hotel, Transfer, Passport, Insurance, SightSeeing
from bookings.views import service_summary
from services.utils.decorators import get_service_model
from django.contrib.auth import get_user_model

User = get_user_model()

SERVICE_MODELS = [
    ("ticket", Ticket),
    ("visa", Visa),
    ("hotel", Hotel),
    ("transfer", Transfer),
    ("passport", Passport),
    ("insurance", Insurance),
    ("sightseeing", SightSeeing),
]

PAGE_SIZE = 50  # infinite scroll batch size


def is_accountant(user):
    return user.is_authenticated and getattr(user, "role", "").upper() == "ACCOUNTANT"


# -----------------------------
# TODO LIST (unchanged)
# -----------------------------
@method_decorator(user_passes_test(is_accountant), name="dispatch")
class AccountTodoView(ListView):
    template_name = "todo_services.html"
    context_object_name = "services"

    def get_queryset(self):
        services = []
        for _, model in SERVICE_MODELS:
            services.extend(
                model.objects.filter(finished=True, accounts_processed=False)
                .select_related("booking__client", "booking__created_by", "created_by")
            )
        return sorted(services, key=lambda x: x.booking.booking_date)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        group_by = self.request.GET.get("group_by", "")
        grouped_services = {}

        if group_by == "booking":
            for service in context["services"]:
                booking = service.booking
                grouped_services.setdefault(booking, []).append(service)

        elif group_by == "user":
            for service in context["services"]:
                user = service.created_by or "Unassigned"
                grouped_services.setdefault(user, []).append(service)

        context["group_by"] = group_by
        context["grouped_services"] = grouped_services
        return context


# -----------------------------
# PROCESS SERVICE (unchanged)
# -----------------------------
@login_required(login_url="/users/login/")
@user_passes_test(is_accountant)
def process_service(request, service_type, pk):
    model = get_service_model(service_type)
    service = get_object_or_404(model, pk=pk)
    booking = service.booking
    client = booking.client

    service_type_name = service._meta.verbose_name_plural.title()
    services_data = {service_type_name: service_summary([service])}

    all_services = [s for service_list in services_data.values() for s in service_list]
    totals = {
        "total_purchase": sum(s["purchase"] for s in all_services),
        "total_sales": sum(s["sales"] for s in all_services),
        "total_gst": sum(s["gst"] for s in all_services),
        "net_profit": sum(s["profit"] for s in all_services),
        "total_tcs": booking.tcs_amount,
    }

    context = {
        "booking": booking,
        "client": client,
        "services_data": services_data,
        "totals": totals,
        "show_pdf_controls": True,
    }

    if request.method == "POST":
        service.accounts_processed = True
        service.save()
        return redirect("accounts_todo")

    return render(request, "process_service.html", context)


# -----------------------------
# Helpers for PROCESSED list
# -----------------------------
def service_label(service):
    return service.__class__._meta.verbose_name.title()


def get_all_processed_by_users():
    """
    Dropdown for Processed By: include ALL users who processed ANY service type.
    """
    user_ids = set()
    for _, model in SERVICE_MODELS:
        ids = (
            model.objects.filter(accounts_processed=True)
            .exclude(created_by__isnull=True)
            .values_list("created_by_id", flat=True)
            .distinct()
        )
        user_ids.update(ids)

    return (
        User.objects.filter(id__in=user_ids)
        .order_by("first_name", "last_name", "username")
    )


def get_all_clients_with_processed_services():
    """
    Dropdown for Clients: include ALL clients that appear in ANY processed service.
    Returns: list of dicts -> [{"id": 12, "name": "A B"}, ...]
    """
    client_map = {}

    for _, model in SERVICE_MODELS:
        qs = (
            model.objects.filter(accounts_processed=True)
            .select_related("booking__client")
            .values(
                "booking__client_id",
                "booking__client__first_name",
                "booking__client__last_name",
            )
            .distinct()
        )
        for row in qs:
            cid = row["booking__client_id"]
            if not cid:
                continue
            name = f"{row.get('booking__client__first_name') or ''} {row.get('booking__client__last_name') or ''}".strip()
            client_map[cid] = name or f"Client #{cid}"

    clients = [{"id": cid, "name": nm} for cid, nm in client_map.items()]
    clients.sort(key=lambda x: x["name"].lower())
    return clients


# -----------------------------
# PROCESSED SERVICES (HTML shell)
# -----------------------------
@login_required(login_url="/users/login/")
@user_passes_test(is_accountant)
def processed_services(request):
    users = get_all_processed_by_users()
    clients = get_all_clients_with_processed_services()

    return render(request, "processed_services.html", {
        "users": users,
        "clients": clients,
    })


# -----------------------------
# PROCESSED SERVICES (DATA API: cursor pagination)
# -----------------------------
@login_required(login_url="/users/login/")
@user_passes_test(is_accountant)
def processed_services_data(request):
    cursor_date = request.GET.get("cursor_date")  # YYYY-MM-DD
    cursor_id = request.GET.get("cursor_id")
    service_type = request.GET.get("service_type")
    processed_by = request.GET.get("processed_by")
    client_id = request.GET.get("client_id")

    rows = []

    models = SERVICE_MODELS
    if service_type:
        models = [m for m in SERVICE_MODELS if m[0] == service_type]

    for _, model in models:
        qs = (
            model.objects.filter(accounts_processed=True)
            .select_related("booking__client", "created_by")
        )

        # Dropdown filters (DB level)
        if processed_by:
            qs = qs.filter(created_by_id=processed_by)

        if client_id:
            qs = qs.filter(booking__client_id=client_id)

        # Cursor pagination (keyset)
        # We combine two conditions using Q to avoid operator precedence issues.
        if cursor_date and cursor_id:
            from django.db.models import Q
            qs = qs.filter(
                Q(booking__booking_date__lt=cursor_date) |
                Q(booking__booking_date=cursor_date, pk__lt=cursor_id)
            )

        qs = qs.order_by("-booking__booking_date", "-pk")[:PAGE_SIZE + 1]
        rows.extend(list(qs))

    # Global sort across models
    rows.sort(key=lambda s: (s.booking.booking_date, s.pk), reverse=True)

    has_more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]

    payload = []
    for s in rows:
        payload.append({
            "id": s.pk,
            "booking_date": s.booking.booking_date.strftime("%d-%b-%Y") if s.booking and s.booking.booking_date else "",
            "client": str(s.booking.client) if s.booking and s.booking.client else "Unknown",
            "service_type": service_label(s),
            "description": s.get_service_description() if hasattr(s, "get_service_description") else str(s),
            "amount": float(s.sales_amount or 0),
            "processed_by": s.created_by.get_full_name() if getattr(s, "created_by", None) else "-",
        })

    next_cursor = None
    if has_more:
        last = rows[-1]
        next_cursor = {
            "date": last.booking.booking_date.isoformat(),
            "id": last.pk,
        }

    return JsonResponse({
        "rows": payload,
        "has_more": has_more,
        "next_cursor": next_cursor,
    })
