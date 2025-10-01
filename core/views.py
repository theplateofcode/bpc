from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from itertools import chain
from datetime import datetime
from django.db.models import Value, CharField
from services.models import Hotel, Insurance, Passport, SightSeeing, Ticket, Transfer, Visa
from bookings.models import Booking
from suppliers.models import Supplier


@login_required(login_url='/users/login/')
def clients(request):
    return render(request, 'clients.html')


User = get_user_model()


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def manage_groups(request):
    groups = Group.objects.all().order_by('name')
    users = User.objects.all().order_by('username')

    if request.method == "POST":
        group_id = request.POST.get('group_id')
        user_ids = request.POST.getlist('users')
        group = get_object_or_404(Group, id=group_id)
        group.user_set.set(User.objects.filter(id__in=user_ids))
        return redirect('manage_groups')

    return render(request, 'manage_groups.html', {
        'groups': groups,
        'users': users,
    })


@login_required
def employee_dashboard(request):
    """Main dashboard for logged-in employees (non-superusers)."""
    if request.user.is_superuser:
        return render(request, "owner_reports.html")
    return render(request, "home.html")


# ---------------------------
# Filters (for dropdowns)
# ---------------------------
@login_required
def employee_report_filters_data(request):
    user = request.user

    services = ["Hotel", "Insurance", "Passport", "Sightseeing", "Ticket", "Transfer", "Visa"]

    # Collect years/months from this employee’s bookings
    all_dates = Booking.objects.filter(created_by=user).values_list("booking_date", flat=True)
    years, months = set(), set()
    for d in all_dates:
        if d:
            years.add(d.year)
            months.add(d.strftime("%B"))

    # Clients linked to this employee
    clients = Booking.objects.filter(created_by=user).values(
        "client_id", "client__first_name", "client__last_name"
    ).distinct()

    # Show all suppliers (simpler, prevents 500)
    suppliers = Supplier.objects.values("id", "name")

    return JsonResponse({
        "services": services,
        "years": sorted(years),
        "months": sorted(
            months,
            key=lambda m: [
                "January","February","March","April","May","June",
                "July","August","September","October","November","December"
            ].index(m)
        ),
        "clients": [
            {"id": c["client_id"], "name": f"{c['client__first_name']} {c['client__last_name']}"}
            for c in clients if c["client_id"]
        ],
        "suppliers": list(suppliers),
    })

# ---------------------------
# Filtered report (cards + service summary)
# ---------------------------
@login_required
def employee_filtered_report(request):
    user = request.user
    service_filter = request.GET.get("service")
    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    client_booking_ids = None
    if client:
        client_booking_ids = set(
            Booking.objects.filter(client_id=client).values_list("id", flat=True)
        )

    services_map = {
        "Hotel": Hotel, "Insurance": Insurance, "Passport": Passport,
        "Sightseeing": SightSeeing, "Ticket": Ticket,
        "Transfer": Transfer, "Visa": Visa,
    }

    all_services = []
    for name, model in services_map.items():
        if service_filter and service_filter != name:
            continue
        qs = model.objects.filter(created_by=user)
        rows = qs.values(
            "date", "sales_amount", "purchase_amount", "mode__name",
            "booking_id", "supplier_id"
        ).annotate(service_name=Value(name, output_field=CharField()))
        all_services.extend(list(rows))

    results = {
        "totals": {
            "sales_cash": 0.0, "sales_non_cash": 0.0,
            "purchase_cash": 0.0, "purchase_non_cash": 0.0,
            "profit_cash": 0.0, "profit_non_cash": 0.0,
            "bookings": set(),
        },
        "service_summary": {},
    }

    for s in all_services:
        if not s["date"]:
            continue
        if year and str(s["date"].year) != year:
            continue
        if month and s["date"].strftime("%B") != month:
            continue
        if supplier and str(s["supplier_id"]) != supplier:
            continue
        if client_booking_ids and s["booking_id"] not in client_booking_ids:
            continue

        sales = float(s["sales_amount"] or 0)
        purchase = float(s["purchase_amount"] or 0)
        profit = sales - purchase
        mode = "cash" if s["mode__name"] == "Cash" else "non_cash"

        results["totals"][f"sales_{mode}"] += sales
        results["totals"][f"purchase_{mode}"] += purchase
        results["totals"][f"profit_{mode}"] += profit
        results["totals"]["bookings"].add(s["booking_id"])

        service_name = s["service_name"]
        if service_name not in results["service_summary"]:
            results["service_summary"][service_name] = {
                "sales_cash": 0.0, "sales_non_cash": 0.0,
                "purchase_cash": 0.0, "purchase_non_cash": 0.0,
                "profit_cash": 0.0, "profit_non_cash": 0.0,
                "bookings": set(),
            }
        results["service_summary"][service_name][f"sales_{mode}"] += sales
        results["service_summary"][service_name][f"purchase_{mode}"] += purchase
        results["service_summary"][service_name][f"profit_{mode}"] += profit
        results["service_summary"][service_name]["bookings"].add(s["booking_id"])

    results["totals"]["bookings"] = len(results["totals"]["bookings"])
    for k, v in results["service_summary"].items():
        v["bookings"] = len(v["bookings"])

    return JsonResponse(results)


# ---------------------------
# Bookings report (table)
# ---------------------------
@login_required
def employee_bookings_report(request):
    user = request.user
    client_id = request.GET.get("client")
    year = request.GET.get("year")
    month = request.GET.get("month")
    supplier = request.GET.get("supplier")
    service_filter = request.GET.get("service")

    bookings = Booking.objects.filter(created_by=user).select_related("client", "created_by")

    if client_id:
        bookings = bookings.filter(client_id=client_id)
    if year:
        bookings = bookings.filter(booking_date__year=year)
    if month:
        try:
            month_num = datetime.strptime(month, "%B").month
            bookings = bookings.filter(booking_date__month=month_num)
        except ValueError:
            pass

    data = []
    for booking in bookings:
        booking_info = {
            "booking_id": booking.booking_id,
            "booking_date": booking.booking_date.strftime("%d-%b-%Y") if booking.booking_date else "",
            "created_by": booking.created_by.get_full_name() or booking.created_by.username,
            "client_name": f"{booking.client.first_name} {booking.client.last_name}" if booking.client else "Unknown",
            "services": [],
        }

        all_services = chain(
            Hotel.objects.filter(booking=booking, created_by=user).values("sales_amount", "purchase_amount", "mode__name").annotate(service_name=Value("Hotel", output_field=CharField())),
            Insurance.objects.filter(booking=booking, created_by=user).values("sales_amount", "purchase_amount", "mode__name").annotate(service_name=Value("Insurance", output_field=CharField())),
            Passport.objects.filter(booking=booking, created_by=user).values("sales_amount", "purchase_amount", "mode__name").annotate(service_name=Value("Passport", output_field=CharField())),
            SightSeeing.objects.filter(booking=booking, created_by=user).values("sales_amount", "purchase_amount", "mode__name").annotate(service_name=Value("Sightseeing", output_field=CharField())),
            Ticket.objects.filter(booking=booking, created_by=user).values("sales_amount", "purchase_amount", "mode__name").annotate(service_name=Value("Ticket", output_field=CharField())),
            Transfer.objects.filter(booking=booking, created_by=user).values("sales_amount", "purchase_amount", "mode__name").annotate(service_name=Value("Transfer", output_field=CharField())),
            Visa.objects.filter(booking=booking, created_by=user).values("sales_amount", "purchase_amount", "mode__name").annotate(service_name=Value("Visa", output_field=CharField())),
        )

        sales_cash = sales_non = purchase_cash = purchase_non = 0.0
        for s in all_services:
            if service_filter and service_filter != s["service_name"]:
                continue

            sales = float(s["sales_amount"] or 0)
            purchase = float(s["purchase_amount"] or 0)
            profit = sales - purchase
            mode = "cash" if s["mode__name"] == "Cash" else "non_cash"

            if mode == "cash":
                sales_cash += sales
                purchase_cash += purchase
            else:
                sales_non += sales
                purchase_non += purchase

            booking_info["services"].append({
                "service": s["service_name"],
                "mode": s["mode__name"],
                "sales": sales,
                "purchase": purchase,
                "profit": profit,
            })

        booking_info["totals"] = {
            "sales_cash": sales_cash, "sales_non_cash": sales_non,
            "purchase_cash": purchase_cash, "purchase_non_cash": purchase_non,
            "profit_cash": sales_cash - purchase_cash,
            "profit_non_cash": sales_non - purchase_non,
        }

        data.append(booking_info)

    return JsonResponse({"data": data})
