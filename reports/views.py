from django.http import JsonResponse
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import render
from django.db.models import Value, CharField
from itertools import chain
from collections import defaultdict
from datetime import datetime

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
# Main Report Page (Owner)
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
        profit = float((s["sales_amount"] or 0) - (s["purchase_amount"] or 0))
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
        profit = float((s["sales_amount"] or 0) - (s["purchase_amount"] or 0))
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
# Filters (dropdown data)
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
        "months": sorted(months, key=lambda m: [
            "January","February","March","April","May","June",
            "July","August","September","October","November","December"
        ].index(m)),
        "clients": [{"id": c["client_id"], "name": f"{c['client__first_name']} {c['client__last_name']}"} for c in clients if c["client_id"]],
        "suppliers": list(suppliers),
    })


# ---------------------------
# Filtered Report (cards + service summary + employee summary)
# ---------------------------
# The seven service tables in the exact order the reports below used to chain
# them. The order is load-bearing: the totals are accumulated as floats, and
# float addition is not associative, so re-ordering could shift a trailing digit.
_SERVICE_VALUE_SOURCES = (
    ("Hotel", Hotel),
    ("Insurance", Insurance),
    ("Passport", Passport),
    ("Sightseeing", SightSeeing),
    ("Ticket", Ticket),
    ("Transfer", Transfer),
    ("Visa", Visa),
)


def _service_value_rows_by_booking(booking_ids):
    """Every service row for these bookings, grouped by booking id.

    Replaces the seven per-booking queries the loops used to run -- the same
    rows, the same order within each booking, fetched seven times in total
    rather than seven times per booking.
    """
    booking_ids = list(booking_ids)
    grouped = defaultdict(list)
    if not booking_ids:
        return grouped

    for label, model in _SERVICE_VALUE_SOURCES:
        for chunk in (booking_ids[i:i + 1000] for i in range(0, len(booking_ids), 1000)):
            rows = (
                model.objects
                .filter(booking_id__in=chunk)
                .values("sales_amount", "purchase_amount", "mode__name",
                        "created_by_id", "booking_id")
                .annotate(service_name=Value(label, output_field=CharField()))
                .order_by("id")
            )
            for row in rows:
                grouped[row["booking_id"]].append(row)
    return grouped


@user_passes_test(superuser_only)
def filtered_report(request):
    service_filter = request.GET.get("service")
    employee = request.GET.get("employee")
    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    # Start totals
    results = {
        "totals": {
            "sales_cash": 0.0, "sales_non_cash": 0.0,
            "purchase_cash": 0.0, "purchase_non_cash": 0.0,
            "profit_cash": 0.0, "profit_non_cash": 0.0,
            "bookings": 0,
        },
        "service_summary": {},
        "employee_summary": {},
    }

    # --- Step 1: Get the bookings (same filters as bookings_report) ---
    # Ordered explicitly: this queryset is iterated straight into the response,
    # and without ORDER BY the row order is whatever index the planner picks --
    # which the indexes added for performance can silently change.
    bookings = Booking.objects.all().select_related("client", "created_by").order_by("id")

    if client:
        bookings = bookings.filter(client_id=client)
    if employee:
        bookings = bookings.filter(created_by_id=employee)
    if year:
        bookings = bookings.filter(booking_date__year=year)
    if month:
        try:
            month_num = datetime.strptime(month, "%B").month
            bookings = bookings.filter(booking_date__month=month_num)
        except ValueError:
            pass
    if supplier:
        bookings = bookings.filter(
            id__in=[
                b.id for b in Booking.objects.filter(
                    id__in=bookings.values_list("id", flat=True),
                    services__supplier_id=supplier
                )
            ]
        )

    results["totals"]["bookings"] = bookings.distinct().count()

    # --- Step 2: Walk through each booking’s services ---
    bookings = list(bookings)
    service_rows = _service_value_rows_by_booking(booking.id for booking in bookings)
    for booking in bookings:
        all_services = service_rows.get(booking.id, [])

        for s in all_services:
            if service_filter and service_filter != s["service_name"]:
                continue

            sale = float(s["sales_amount"] or 0)
            purc = float(s["purchase_amount"] or 0)
            profit = sale - purc
            mode = "cash" if s["mode__name"] == "Cash" else "non_cash"

            # --- Totals (these are your cards!) ---
            results["totals"][f"sales_{mode}"] += sale
            results["totals"][f"purchase_{mode}"] += purc
            results["totals"][f"profit_{mode}"] += profit   # ✅ HERE — profit matches Client Bookings row

            # --- Service summary ---
            svc = s["service_name"]
            if svc not in results["service_summary"]:
                results["service_summary"][svc] = {
                    "bookings": set(),
                    "sales_cash": 0.0, "sales_non_cash": 0.0,
                    "purchase_cash": 0.0, "purchase_non_cash": 0.0,
                    "profit_cash": 0.0, "profit_non_cash": 0.0,
                }
            results["service_summary"][svc]["bookings"].add(booking.id)
            results["service_summary"][svc][f"sales_{mode}"] += sale
            results["service_summary"][svc][f"purchase_{mode}"] += purc
            results["service_summary"][svc][f"profit_{mode}"] += profit

            # --- Employee summary ---
            emp = s["created_by_id"]
            if emp not in results["employee_summary"]:
                results["employee_summary"][emp] = {
                    "sales_cash": 0.0, "sales_non_cash": 0.0,
                    "purchase_cash": 0.0, "purchase_non_cash": 0.0,
                    "profit_cash": 0.0, "profit_non_cash": 0.0,
                }
            results["employee_summary"][emp][f"sales_{mode}"] += sale
            results["employee_summary"][emp][f"purchase_{mode}"] += purc
            results["employee_summary"][emp][f"profit_{mode}"] += profit

    # --- Step 3: Finalize summaries ---
    for k, v in results["service_summary"].items():
        v["bookings"] = len(v["bookings"])

    # Totals row for service summary
    svc_total = {
        "sales_cash": sum(v["sales_cash"] for v in results["service_summary"].values()),
        "sales_non_cash": sum(v["sales_non_cash"] for v in results["service_summary"].values()),
        "purchase_cash": sum(v["purchase_cash"] for v in results["service_summary"].values()),
        "purchase_non_cash": sum(v["purchase_non_cash"] for v in results["service_summary"].values()),
        "profit_cash": sum(v["profit_cash"] for v in results["service_summary"].values()),
        "profit_non_cash": sum(v["profit_non_cash"] for v in results["service_summary"].values()),
        "bookings": sum(v["bookings"] for v in results["service_summary"].values()),
    }
    results["service_summary"]["TOTAL"] = svc_total

    # Totals row for employee summary
    emp_total = {
        "sales_cash": sum(v["sales_cash"] for v in results["employee_summary"].values()),
        "sales_non_cash": sum(v["sales_non_cash"] for v in results["employee_summary"].values()),
        "purchase_cash": sum(v["purchase_cash"] for v in results["employee_summary"].values()),
        "purchase_non_cash": sum(v["purchase_non_cash"] for v in results["employee_summary"].values()),
        "profit_cash": sum(v["profit_cash"] for v in results["employee_summary"].values()),
        "profit_non_cash": sum(v["profit_non_cash"] for v in results["employee_summary"].values()),
    }
    results["employee_summary"]["TOTAL"] = emp_total

    # Replace employee IDs with names
    emp_named = {}
    for emp_id, vals in results["employee_summary"].items():
        if emp_id == "TOTAL":
            emp_named["TOTAL"] = vals
            continue
        try:
            user = User.objects.get(id=emp_id)
            emp_named[user.get_full_name() or user.username] = vals
        except User.DoesNotExist:
            emp_named[f"User {emp_id}"] = vals
    results["employee_summary"] = emp_named

    return JsonResponse(results)

# ---------------------------
# Bookings Report (Client Bookings Summary)
# ---------------------------
@user_passes_test(superuser_only)
def bookings_report(request):
    employee = request.GET.get("employee")
    client_id = request.GET.get("client")
    year = request.GET.get("year")
    month = request.GET.get("month")
    supplier = request.GET.get("supplier")
    service_filter = request.GET.get("service")

    # Ordered explicitly: this queryset is iterated straight into the response,
    # and without ORDER BY the row order is whatever index the planner picks --
    # which the indexes added for performance can silently change.
    bookings = Booking.objects.all().select_related("client", "created_by").order_by("id")

    if client_id:
        bookings = bookings.filter(client_id=client_id)
    if employee:
        bookings = bookings.filter(created_by_id=employee)
    if year:
        bookings = bookings.filter(booking_date__year=year)
    if month:
        try:
            month_num = datetime.strptime(month, "%B").month
            bookings = bookings.filter(booking_date__month=month_num)
        except ValueError:
            pass
    if supplier:
        bookings = bookings.filter(
            id__in=[
                b.id for b in Booking.objects.filter(
                    id__in=bookings.values_list("id", flat=True),
                    services__supplier_id=supplier
                )
            ]
        )

    data = []
    bookings = list(bookings)
    service_rows = _service_value_rows_by_booking(booking.id for booking in bookings)

    # "entered by" used to be looked up one query at a time, inside the loop over
    # service rows -- on real data that was 1,215 queries for a single request.
    # One query for the whole page instead. get_full_name() is evaluated here so
    # the loop only does a dict lookup.
    staff_names = {
        user.id: user.get_full_name()
        for user in User.objects.only("id", "first_name", "last_name")
    }

    for booking in bookings:
        booking_info = {
            "booking_id": booking.booking_id,
            "booking_date": booking.booking_date.strftime("%d-%b-%Y") if booking.booking_date else "",
            "created_by": booking.created_by.get_full_name() if booking.created_by else "Unknown",
            "client_name": f"{booking.client.first_name} {booking.client.last_name}" if booking.client else "Unknown",
            "services": [],
        }

        all_services = service_rows.get(booking.id, [])

        sales_cash = sales_non = purchase_cash = purchase_non = 0.0
        profit_cash = profit_non = 0.0

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
                profit_cash += profit
            else:
                sales_non += sales
                purchase_non += purchase
                profit_non += profit

            staff_name = staff_names.get(s["created_by_id"], "Unknown")

            booking_info["services"].append({
                "service": s["service_name"],
                "mode": s["mode__name"],
                "sales": sales,
                "purchase": purchase,
                "profit": profit,
                "entered_by": staff_name,
            })

        booking_info["totals"] = {
            "sales_cash": sales_cash, "sales_non_cash": sales_non,
            "purchase_cash": purchase_cash, "purchase_non_cash": purchase_non,
            "profit_cash": profit_cash, "profit_non_cash": profit_non,
        }
        data.append(booking_info)

    return JsonResponse({"data": data})
