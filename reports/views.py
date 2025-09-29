from django.http import JsonResponse
from django.contrib.auth.decorators import user_passes_test
from itertools import chain
from collections import defaultdict
from django.shortcuts import render
from django.db.models import Sum, Value, CharField
from django.utils.formats import number_format

from services.models import Hotel, Insurance, Passport, SightSeeing, Ticket, Transfer, Visa
from bookings.models import Booking
from suppliers.models import Supplier
from django.contrib.auth import get_user_model

User = get_user_model()

# ---------------------------
# Helpers
# ---------------------------
def superuser_only(user):
    return user.is_superuser

def add_totals_row(summary_dict, include_bookings=False):
    """Append a TOTAL row at the end of summaries."""
    if not summary_dict:
        return summary_dict
    total_row = defaultdict(float)
    if include_bookings:
        total_row["bookings"] = 0
    for v in summary_dict.values():
        for k, val in v.items():
            if isinstance(val, (int, float)):
                total_row[k] += val
        if include_bookings:
            total_row["bookings"] += v.get("bookings", 0)
    summary_dict["TOTAL"] = dict(total_row)
    return summary_dict


# ---------------------------
# Page view
# ---------------------------
@user_passes_test(superuser_only)
def owner_reports(request):
    return render(request, "owner_reports.html")


# ---------------------------
# Company-wide monthly profit chart
# ---------------------------
@user_passes_test(superuser_only)
def monthly_profit_data(request):
    all_services = chain(
        Hotel.objects.values("date", "sales_amount", "purchase_amount", "mode__name"),
        Insurance.objects.values("date", "sales_amount", "purchase_amount", "mode__name"),
        Passport.objects.values("date", "sales_amount", "purchase_amount", "mode__name"),
        SightSeeing.objects.values("date", "sales_amount", "purchase_amount", "mode__name"),
        Ticket.objects.values("date", "sales_amount", "purchase_amount", "mode__name"),
        Transfer.objects.values("date", "sales_amount", "purchase_amount", "mode__name"),
        Visa.objects.values("date", "sales_amount", "purchase_amount", "mode__name"),
    )

    stats = defaultdict(lambda: {"profit_cash": 0, "profit_non_cash": 0})
    for s in all_services:
        if not s["date"]:
            continue
        key = f"{s['date'].year}-{s['date'].month:02d}"
        profit = (s["sales_amount"] or 0) - (s["purchase_amount"] or 0)
        if s["mode__name"] == "Cash":
            stats[key]["profit_cash"] += profit
        else:
            stats[key]["profit_non_cash"] += profit

    labels, profit_cash, profit_non_cash = [], [], []
    for ym in sorted(stats.keys()):
        year, month = ym.split("-")
        labels.append(f"{month}-{year}")
        profit_cash.append(stats[ym]["profit_cash"])
        profit_non_cash.append(stats[ym]["profit_non_cash"])

    return JsonResponse({
        "labels": labels,
        "datasets": [
            {"label": "Profit Cash", "data": profit_cash, "backgroundColor": "#00aaff"},
            {"label": "Profit Non-Cash", "data": profit_non_cash, "backgroundColor": "#55cc55"},
        ]
    })


# ---------------------------
# Staff-wise profit summary
# ---------------------------
@user_passes_test(superuser_only)
def staff_profit_data(request):
    staff_users = User.objects.filter(role="STAFF").values("id", "first_name", "last_name")
    all_services = chain(
        Hotel.objects.values("date", "sales_amount", "purchase_amount", "mode__name", "created_by_id"),
        Insurance.objects.values("date", "sales_amount", "purchase_amount", "mode__name", "created_by_id"),
        Passport.objects.values("date", "sales_amount", "purchase_amount", "mode__name", "created_by_id"),
        SightSeeing.objects.values("date", "sales_amount", "purchase_amount", "mode__name", "created_by_id"),
        Ticket.objects.values("date", "sales_amount", "purchase_amount", "mode__name", "created_by_id"),
        Transfer.objects.values("date", "sales_amount", "purchase_amount", "mode__name", "created_by_id"),
        Visa.objects.values("date", "sales_amount", "purchase_amount", "mode__name", "created_by_id"),
    )

    stats = defaultdict(lambda: defaultdict(lambda: {"cash": 0, "non_cash": 0}))
    months_set = set()

    for s in all_services:
        if not s["date"] or not s["created_by_id"]:
            continue
        ym = f"{s['date'].strftime('%b-%y')}"
        months_set.add(ym)
        profit = (s["sales_amount"] or 0) - (s["purchase_amount"] or 0)
        if s["mode__name"] == "Cash":
            stats[s["created_by_id"]][ym]["cash"] += profit
        else:
            stats[s["created_by_id"]][ym]["non_cash"] += profit

    months = sorted(list(months_set), key=lambda m: (
        int(m.split("-")[1]),
        ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"].index(m.split("-")[0])
    ))

    datasets_cash, datasets_non_cash, table_data = [], [], []
    total_company_profit = 0
    for u in staff_users:
        uid, uname = u["id"], f"{u['first_name']} {u['last_name']}".strip()
        cash_data = [stats[uid][m]["cash"] for m in months]
        noncash_data = [stats[uid][m]["non_cash"] for m in months]
        datasets_cash.append({"label": uname, "data": cash_data})
        datasets_non_cash.append({"label": uname, "data": noncash_data})
        total_cash, total_non_cash = sum(cash_data), sum(noncash_data)
        total_profit = total_cash + total_non_cash
        total_company_profit += total_profit
        table_data.append({"staff": uname, "cash": total_cash, "non_cash": total_non_cash, "total": total_profit})

    for row in table_data:
        row["contribution"] = round((row["total"] / total_company_profit) * 100, 2) if total_company_profit > 0 else 0

    return JsonResponse({
        "labels": months,
        "datasets": {"cash": datasets_cash, "non_cash": datasets_non_cash},
        "table": table_data
    })


# ---------------------------
# Service-wise totals (for the static service table)
# ---------------------------
@user_passes_test(superuser_only)
def service_wise_table(request):
    services = {
        "Hotel": Hotel.objects.all(),
        "Insurance": Insurance.objects.all(),
        "Passport": Passport.objects.all(),
        "Sightseeing": SightSeeing.objects.all(),
        "Ticket": Ticket.objects.all(),
        "Transfer": Transfer.objects.all(),
        "Visa": Visa.objects.all(),
    }

    data = []
    for name, qs in services.items():
        purchase_cash = qs.filter(mode__name="Cash").aggregate(total=Sum("purchase_amount"))["total"] or 0
        purchase_non = qs.exclude(mode__name="Cash").aggregate(total=Sum("purchase_amount"))["total"] or 0
        sales_cash = qs.filter(mode__name="Cash").aggregate(total=Sum("sales_amount"))["total"] or 0
        sales_non = qs.exclude(mode__name="Cash").aggregate(total=Sum("sales_amount"))["total"] or 0
        profit_cash, profit_non = sales_cash - purchase_cash, sales_non - purchase_non
        data.append({
            "service": name,
            "purchase_cash": number_format(purchase_cash, use_l10n=True),
            "purchase_non_cash": number_format(purchase_non, use_l10n=True),
            "sales_cash": number_format(sales_cash, use_l10n=True),
            "sales_non_cash": number_format(sales_non, use_l10n=True),
            "profit_cash": number_format(profit_cash, use_l10n=True),
            "profit_non_cash": number_format(profit_non, use_l10n=True),
            "purchase_total": number_format(purchase_cash + purchase_non, use_l10n=True),
            "sales_total": number_format(sales_cash + sales_non, use_l10n=True),
            "profit_total": number_format(profit_cash + profit_non, use_l10n=True),
        })
    return JsonResponse({"data": data})


# ---------------------------
# Filters (dropdown sources)
# ---------------------------
@user_passes_test(superuser_only)
def report_filters_data(request):
    services = ["Hotel", "Insurance", "Passport", "Sightseeing", "Ticket", "Transfer", "Visa"]
    employees = list(User.objects.filter(role="STAFF").values("id", "first_name", "last_name"))
    all_dates = chain(
        Hotel.objects.values_list("date", flat=True),
        Insurance.objects.values_list("date", flat=True),
        Passport.objects.values_list("date", flat=True),
        SightSeeing.objects.values_list("date", flat=True),
        Ticket.objects.values_list("date", flat=True),
        Transfer.objects.values_list("date", flat=True),
        Visa.objects.values_list("date", flat=True),
    )
    years, months = set(), set()
    for d in all_dates:
        if d:
            years.add(d.year)
            months.add(d.strftime("%B"))
    clients = Booking.objects.values("client_id", "client__first_name", "client__last_name").distinct()
    suppliers = Supplier.objects.values("id", "name").distinct()
    return JsonResponse({
        "services": services,
        "employees": [{"id": e["id"], "name": f"{e['first_name']} {e['last_name']}"} for e in employees],
        "years": sorted(years),
        "months": sorted(months, key=lambda m: ["January","February","March","April","May","June","July","August","September","October","November","December"].index(m)),
        "clients": [{"id": c["client_id"], "name": f"{c['client__first_name']} {c['client__last_name']}"} for c in clients if c["client_id"]],
        "suppliers": list(suppliers),
    })


# ---------------------------
# Filtered Report (applies all filters + adds TOTAL rows)
# ---------------------------
@user_passes_test(superuser_only)
def filtered_report(request):
    service_filter = request.GET.get("service")
    employee = request.GET.get("employee")
    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    # Build a quick set of booking IDs for client filter (if any)
    client_booking_ids = None
    if client:
        client_booking_ids = set(
            Booking.objects.filter(client_id=client).values_list("id", flat=True)
        )

    # Map service name -> model
    services_map = {
        "Hotel": Hotel,
        "Insurance": Insurance,
        "Passport": Passport,
        "Sightseeing": SightSeeing,
        "Ticket": Ticket,
        "Transfer": Transfer,
        "Visa": Visa,
    }

    # Collect rows from the chosen service(s) and annotate service_name
    all_services = []
    for name, model in services_map.items():
        if service_filter and service_filter != name:
            continue
        qs = model.objects.all()
        rows = qs.values(
            "date",
            "sales_amount",
            "purchase_amount",
            "mode__name",
            "created_by_id",
            "booking_id",
            "supplier_id",
        ).annotate(service_name=Value(name, output_field=CharField()))
        all_services.extend(list(rows))

    results = {
        "totals": {
            "sales_cash": 0.0,
            "sales_non_cash": 0.0,
            "purchase_cash": 0.0,
            "purchase_non_cash": 0.0,
            "profit_cash": 0.0,
            "profit_non_cash": 0.0,
            "bookings": set(),
        },
        "service_summary": {},
        "employee_summary": {},
    }

    for s in all_services:
        if not s["date"]:
            continue

        # Apply filters
        if year and str(s["date"].year) != year:
            continue
        if month and s["date"].strftime("%B") != month:
            continue
        if employee and str(s["created_by_id"]) != employee:
            continue
        if supplier and str(s["supplier_id"]) != supplier:
            continue
        if client_booking_ids is not None and s["booking_id"] not in client_booking_ids:
            continue

        profit = float((s["sales_amount"] or 0) - (s["purchase_amount"] or 0))
        mode = "cash" if s["mode__name"] == "Cash" else "non_cash"

        results["totals"][f"sales_{mode}"] += float(s["sales_amount"] or 0)
        results["totals"][f"purchase_{mode}"] += float(s["purchase_amount"] or 0)
        results["totals"][f"profit_{mode}"] += profit
        results["totals"]["bookings"].add(s["booking_id"])

        # Service summary
        service_name = s["service_name"]
        if service_name not in results["service_summary"]:
            results["service_summary"][service_name] = {
                "bookings": set(),
                "sales_cash": 0.0,
                "sales_non_cash": 0.0,
                "purchase_cash": 0.0,
                "purchase_non_cash": 0.0,
                "profit_cash": 0.0,
                "profit_non_cash": 0.0,
            }
        results["service_summary"][service_name]["bookings"].add(s["booking_id"])
        results["service_summary"][service_name][f"sales_{mode}"] += float(
            s["sales_amount"] or 0
        )
        results["service_summary"][service_name][f"purchase_{mode}"] += float(
            s["purchase_amount"] or 0
        )
        results["service_summary"][service_name][f"profit_{mode}"] += profit

        # Employee summary
        emp_id = s["created_by_id"]
        if emp_id not in results["employee_summary"]:
            results["employee_summary"][emp_id] = {
                "sales_cash": 0.0,
                "sales_non_cash": 0.0,
                "purchase_cash": 0.0,
                "purchase_non_cash": 0.0,
                "profit_cash": 0.0,
                "profit_non_cash": 0.0,
            }
        results["employee_summary"][emp_id][f"sales_{mode}"] += float(
            s["sales_amount"] or 0
        )
        results["employee_summary"][emp_id][f"purchase_{mode}"] += float(
            s["purchase_amount"] or 0
        )
        results["employee_summary"][emp_id][f"profit_{mode}"] += profit

    # finalize distinct bookings count
    results["totals"]["bookings"] = len(results["totals"]["bookings"])

    # convert service booking sets to counts
    for k, v in results["service_summary"].items():
        v["bookings"] = len(v["bookings"])

    # append TOTAL rows
    results["service_summary"] = add_totals_row(
        results["service_summary"], include_bookings=True
    )
    results["employee_summary"] = add_totals_row(results["employee_summary"])

    # 🔹 Replace employee IDs with full names
    emp_summary_named = {}
    for emp_id, vals in results["employee_summary"].items():
        if emp_id == "TOTAL":  # keep total row as is
            emp_summary_named["TOTAL"] = vals
            continue
        try:
            user = User.objects.get(id=emp_id)
            emp_name = user.get_full_name() or user.username
        except User.DoesNotExist:
            emp_name = f"User {emp_id}"
        emp_summary_named[emp_name] = vals
    results["employee_summary"] = emp_summary_named

    return JsonResponse(results)

# ---------------------------
# Client Bookings Report (per selected client)
# ---------------------------
@user_passes_test(superuser_only)
def client_bookings_report(request):
    client_id = request.GET.get("client")
    if not client_id:
        return JsonResponse({"data": []})

    bookings = Booking.objects.filter(client_id=client_id).select_related("client", "created_by", "status")

    data = []
    for booking in bookings:
        booking_info = {
            "booking_id": booking.booking_id,
            "booking_date": booking.booking_date.strftime("%d-%b-%Y") if booking.booking_date else "",
            "created_by": booking.created_by.get_full_name() if getattr(booking, "created_by", None) else "Unknown",
            "services": [],
        }

        all_services = chain(
            Hotel.objects.filter(booking=booking).values("sales_amount", "purchase_amount", "mode__name", "created_by_id").annotate(service_name=Value("Hotel", output_field=CharField())),
            Insurance.objects.filter(booking=booking).values("sales_amount", "purchase_amount", "mode__name", "created_by_id").annotate(service_name=Value("Insurance", output_field=CharField())),
            Passport.objects.filter(booking=booking).values("sales_amount", "purchase_amount", "mode__name", "created_by_id").annotate(service_name=Value("Passport", output_field=CharField())),
            SightSeeing.objects.filter(booking=booking).values("sales_amount", "purchase_amount", "mode__name", "created_by_id").annotate(service_name=Value("Sightseeing", output_field=CharField())),
            Ticket.objects.filter(booking=booking).values("sales_amount", "purchase_amount", "mode__name", "created_by_id").annotate(service_name=Value("Ticket", output_field=CharField())),
            Transfer.objects.filter(booking=booking).values("sales_amount", "purchase_amount", "mode__name", "created_by_id").annotate(service_name=Value("Transfer", output_field=CharField())),
            Visa.objects.filter(booking=booking).values("sales_amount", "purchase_amount", "mode__name", "created_by_id").annotate(service_name=Value("Visa", output_field=CharField())),
        )

        sales_cash = sales_non = purchase_cash = purchase_non = 0.0

        for s in all_services:
            profit = float((s["sales_amount"] or 0) - (s["purchase_amount"] or 0))
            first_last = User.objects.filter(id=s["created_by_id"]).values_list("first_name", "last_name").first()
            staff_name = " ".join(first_last) if first_last else "Unknown"

            mode = "cash" if s["mode__name"] == "Cash" else "non_cash"
            if mode == "cash":
                sales_cash += float(s["sales_amount"] or 0)
                purchase_cash += float(s["purchase_amount"] or 0)
            else:
                sales_non += float(s["sales_amount"] or 0)
                purchase_non += float(s["purchase_amount"] or 0)

            booking_info["services"].append({
                "service": s["service_name"],
                "mode": s["mode__name"],
                "sales": s["sales_amount"],
                "purchase": s["purchase_amount"],
                "profit": profit,
                "entered_by": staff_name,
            })

        booking_info["totals"] = {
            "sales_cash": sales_cash, "sales_non_cash": sales_non,
            "purchase_cash": purchase_cash, "purchase_non_cash": purchase_non,
            "profit_cash": sales_cash - purchase_cash,
            "profit_non_cash": sales_non - purchase_non,
        }

        data.append(booking_info)

    return JsonResponse({"data": data})
