from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from datetime import datetime
from bookings.models import Booking
from payments.models import PaymentReceived
from django.contrib.auth import get_user_model

User = get_user_model()


def to_float(val):
    try:
        return float(val or 0)
    except Exception:
        return 0.0


# ---------------------------
# Main Page
# ---------------------------
@login_required
def owner_actual_reports(request):
    """Render the Actual Profit report page."""
    return render(request, "owner_reports_actual.html")


# ---------------------------
# Filtered Report (Cards + Summaries)
# ---------------------------
@login_required
def filtered_actual_report(request):
    service = request.GET.get("service")
    employee = request.GET.get("employee")
    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    # --- Only approved bookings ---
    bookings = Booking.objects.filter(
        id__in=PaymentReceived.objects.filter(approved=True)
        .values_list("booking_id", flat=True)
        .distinct()
    ).select_related("client", "created_by")

    # --- Filters ---
    if year:
        bookings = bookings.filter(booking_date__year=year)
    if month:
        try:
            month_num = datetime.strptime(month, "%B").month
            bookings = bookings.filter(booking_date__month=month_num)
        except ValueError:
            pass
    if service:
        bookings = bookings.filter(services__name=service)
    if employee:
        bookings = bookings.filter(created_by_id=employee)
    if client:
        bookings = bookings.filter(client_id=client)
    if supplier:
        bookings = bookings.filter(services__supplier_id=supplier)

    results = {
        "totals": {
            "sales_cash": 0.0, "sales_non_cash": 0.0,
            "purchase_cash": 0.0, "purchase_non_cash": 0.0,
            "profit_cash": 0.0, "profit_non_cash": 0.0,
            "discount": 0.0, "bookings": 0,
        },
        "service_summary": {},
        "employee_summary": {},
    }

    # ---------------------------
    # Main Loop
    # ---------------------------
    for booking in bookings:
        payments = PaymentReceived.objects.filter(booking=booking, approved=True)
        if not payments.exists():
            continue

        # --- Actuals from approved payments ---
        actual_sales = sum(to_float(p.amount) for p in payments)
        total_discount = sum(to_float(p.discount) for p in payments)  # ✅ accountant-entered discount
        total_purchase = float(booking.purchase_total or 0)

        total_profit = actual_sales - total_purchase

        # --- Split by mode ---
        cash_sales = sum(to_float(p.amount)
                         for p in payments if p.mode and "cash" in p.mode.name.lower())
        non_cash_sales = actual_sales - cash_sales

        cash_purchase = float(
            total_purchase * (cash_sales / actual_sales)) if actual_sales else 0
        non_cash_purchase = total_purchase - cash_purchase

        cash_profit = cash_sales - cash_purchase
        non_cash_profit = non_cash_sales - non_cash_purchase

        # --- Totals (cards) ---
        results["totals"]["sales_cash"] += cash_sales
        results["totals"]["sales_non_cash"] += non_cash_sales
        results["totals"]["purchase_cash"] += cash_purchase
        results["totals"]["purchase_non_cash"] += non_cash_purchase
        results["totals"]["profit_cash"] += cash_profit
        results["totals"]["profit_non_cash"] += non_cash_profit
        results["totals"]["discount"] += total_discount
        results["totals"]["bookings"] += 1

        # --- Service Summary ---
        for svc in booking.services.all():
            name = svc.name
            sdata = results["service_summary"].setdefault(name, {
                "sales_cash": 0.0, "sales_non_cash": 0.0,
                "purchase_cash": 0.0, "purchase_non_cash": 0.0,
                "profit_cash": 0.0, "profit_non_cash": 0.0,
                "discount": 0.0,
            })
            sdata["sales_cash"] += cash_sales
            sdata["sales_non_cash"] += non_cash_sales
            sdata["purchase_cash"] += cash_purchase
            sdata["purchase_non_cash"] += non_cash_purchase
            sdata["profit_cash"] += cash_profit
            sdata["profit_non_cash"] += non_cash_profit
            sdata["discount"] += total_discount

        # --- Employee Summary ---
        emp = booking.created_by.get_full_name() or booking.created_by.username
        edata = results["employee_summary"].setdefault(emp, {
            "sales_cash": 0.0, "sales_non_cash": 0.0,
            "purchase_cash": 0.0, "purchase_non_cash": 0.0,
            "profit_cash": 0.0, "profit_non_cash": 0.0,
            "discount": 0.0,
        })
        edata["sales_cash"] += cash_sales
        edata["sales_non_cash"] += non_cash_sales
        edata["purchase_cash"] += cash_purchase
        edata["purchase_non_cash"] += non_cash_purchase
        edata["profit_cash"] += cash_profit
        edata["profit_non_cash"] += non_cash_profit
        edata["discount"] += total_discount

    # --- Totals Row ---
    def add_total(block):
        totals = {k: 0.0 for k in [
            "sales_cash", "sales_non_cash",
            "purchase_cash", "purchase_non_cash",
            "profit_cash", "profit_non_cash", "discount",
        ]}
        for v in block.values():
            for k in totals:
                totals[k] += v[k]
        block["TOTAL"] = totals

    add_total(results["service_summary"])
    add_total(results["employee_summary"])

    return JsonResponse(results)


# ---------------------------
# Booking-wise Summary (Client Table)
# ---------------------------
@login_required
def bookings_report(request):
    
    service = request.GET.get("service")
    employee = request.GET.get("employee")
    year = request.GET.get("year")
    month = request.GET.get("month")
    client = request.GET.get("client")
    supplier = request.GET.get("supplier")

    bookings = Booking.objects.filter(
        id__in=PaymentReceived.objects.filter(approved=True)
        .values_list("booking_id", flat=True)
        .distinct()
    ).select_related("client", "created_by")

    # --- Apply filters ---
    if year:
        bookings = bookings.filter(booking_date__year=year)
    if month:
        try:
            month_num = datetime.strptime(month, "%B").month
            bookings = bookings.filter(booking_date__month=month_num)
        except ValueError:
            pass
    if service:
        bookings = bookings.filter(services__name=service)
    if employee:
        bookings = bookings.filter(created_by_id=employee)
    if client:
        bookings = bookings.filter(client_id=client)
    if supplier:
        bookings = bookings.filter(services__supplier_id=supplier)

    data = []

    for booking in bookings:
        payments = PaymentReceived.objects.filter(booking=booking, approved=True)
        if not payments.exists():
            continue

        # --- 1️⃣ Actual values from approved payments ---
        actual_sales = sum(to_float(p.amount) for p in payments)
        total_discount = sum(to_float(p.discount) for p in payments)  # ✅ exact from DB
        total_purchase = float(booking.purchase_total or 0)
        total_profit = actual_sales - total_purchase

        # --- 2️⃣ Split by mode ---
        cash_sales = sum(to_float(p.amount)
                         for p in payments if p.mode and "cash" in p.mode.name.lower())
        non_cash_sales = actual_sales - cash_sales

        cash_purchase = float(
            total_purchase * (cash_sales / actual_sales)) if actual_sales else 0
        non_cash_purchase = total_purchase - cash_purchase

        cash_profit = cash_sales - cash_purchase
        non_cash_profit = non_cash_sales - non_cash_purchase

        # --- 3️⃣ Build service details ---
        services_data = []
        for svc in booking.services.all():
            services_data.append({
                "service": svc.name,
                "mode": ", ".join({p.mode.name for p in payments if p.mode}),
                "sales": actual_sales,
                "purchase": total_purchase,
                "profit": total_profit,
                "discount": total_discount,  # ✅ shown clearly in modal
                "entered_by": booking.created_by.get_full_name(),
            })
        

        # --- 4️⃣ Booking summary row ---
        data.append({
            "booking_id": booking.booking_id,
            "booking_date": booking.booking_date.strftime("%d-%b-%Y") if booking.booking_date else "",
            "created_by": booking.created_by.get_full_name(),
            "client_name": f"{booking.client.first_name} {booking.client.last_name}" if booking.client else "Unknown",
            "services": services_data,
            "totals": {
                "sales_cash": cash_sales, "sales_non_cash": non_cash_sales,
                "purchase_cash": cash_purchase, "purchase_non_cash": non_cash_purchase,
                "profit_cash": cash_profit, "profit_non_cash": non_cash_profit,
                "discount": total_discount,
            },
        })
        
    return JsonResponse({"data": data})
