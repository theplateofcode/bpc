from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from datetime import datetime
from bookings.models import Booking
from payments.models import PaymentReceived

def to_float(v): 
    try: return float(v or 0)
    except: return 0.0

@login_required
def staff_actual_reports(request):
    return render(request, "staff_actual_profit.html")

@login_required
def staff_filtered_actual_report(request):
    user=request.user
    service=request.GET.get("service");year=request.GET.get("year")
    month=request.GET.get("month");client=request.GET.get("client")
    supplier=request.GET.get("supplier")

    bookings=Booking.objects.filter(created_by=user,
        id__in=PaymentReceived.objects.filter(approved=True).values_list("booking_id",flat=True))
    if year: bookings=bookings.filter(booking_date__year=year)
    if month:
        try: bookings=bookings.filter(booking_date__month=datetime.strptime(month,"%B").month)
        except: pass
    if service: bookings=bookings.filter(services__name=service)
    if client: bookings=bookings.filter(client_id=client)
    if supplier: bookings=bookings.filter(services__supplier_id=supplier)

    res={"totals":{"sales_cash":0,"sales_non_cash":0,"purchase_cash":0,"purchase_non_cash":0,
                   "profit_cash":0,"profit_non_cash":0,"discount":0,"bookings":0},
         "service_summary":{}}

    for b in bookings:
        pays=PaymentReceived.objects.filter(booking=b,approved=True)
        if not pays.exists(): continue
        total_sales=sum(to_float(p.amount) for p in pays)
        total_disc=sum(to_float(p.discount) for p in pays)
        total_purchase=float(b.purchase_total or 0)
        cash_sales=sum(to_float(p.amount) for p in pays if p.mode and "cash" in p.mode.name.lower())
        non_cash_sales=total_sales-cash_sales
        cash_pur=total_purchase*(cash_sales/total_sales) if total_sales else 0
        non_cash_pur=total_purchase-cash_pur
        cash_profit=cash_sales-cash_pur; non_cash_profit=non_cash_sales-non_cash_pur

        res["totals"]["sales_cash"]+=cash_sales;res["totals"]["sales_non_cash"]+=non_cash_sales
        res["totals"]["purchase_cash"]+=cash_pur;res["totals"]["purchase_non_cash"]+=non_cash_pur
        res["totals"]["profit_cash"]+=cash_profit;res["totals"]["profit_non_cash"]+=non_cash_profit
        res["totals"]["discount"]+=total_disc;res["totals"]["bookings"]+=1

        for svc in b.services.all():
            sname=svc.name
            s=res["service_summary"].setdefault(sname,{"sales_cash":0,"sales_non_cash":0,"purchase_cash":0,
                                                      "purchase_non_cash":0,"profit_cash":0,"profit_non_cash":0,"discount":0})
            s["sales_cash"]+=cash_sales; s["sales_non_cash"]+=non_cash_sales
            s["purchase_cash"]+=cash_pur; s["purchase_non_cash"]+=non_cash_pur
            s["profit_cash"]+=cash_profit; s["profit_non_cash"]+=non_cash_profit
            s["discount"]+=total_disc

    return JsonResponse(res)

@login_required
def staff_bookings_report(request):
    user=request.user
    service=request.GET.get("service");year=request.GET.get("year")
    month=request.GET.get("month");client=request.GET.get("client")
    supplier=request.GET.get("supplier")

    bookings=Booking.objects.filter(created_by=user,
        id__in=PaymentReceived.objects.filter(approved=True).values_list("booking_id",flat=True))
    if year: bookings=bookings.filter(booking_date__year=year)
    if month:
        try: bookings=bookings.filter(booking_date__month=datetime.strptime(month,"%B").month)
        except: pass
    if service: bookings=bookings.filter(services__name=service)
    if client: bookings=bookings.filter(client_id=client)
    if supplier: bookings=bookings.filter(services__supplier_id=supplier)

    data=[]
    for b in bookings:
        pays=PaymentReceived.objects.filter(booking=b,approved=True)
        if not pays.exists(): continue
        actual_sales=sum(to_float(p.amount) for p in pays)
        total_disc=sum(to_float(p.discount) for p in pays)
        total_purchase=float(b.purchase_total or 0)
        total_profit=actual_sales-total_purchase
        cash_sales=sum(to_float(p.amount) for p in pays if p.mode and "cash" in p.mode.name.lower())
        non_cash_sales=actual_sales-cash_sales
        cash_pur=total_purchase*(cash_sales/actual_sales) if actual_sales else 0
        non_cash_pur=total_purchase-cash_pur
        cash_profit=cash_sales-cash_pur; non_cash_profit=non_cash_sales-non_cash_pur

        services=[{"service":svc.name,"mode":", ".join({p.mode.name for p in pays if p.mode}),
                   "sales":actual_sales,"purchase":total_purchase,"profit":total_profit,
                   "discount":total_disc} for svc in b.services.all()]
        data.append({"booking_id":b.booking_id,"booking_date":b.booking_date.strftime("%d-%b-%Y") if b.booking_date else "",
                     "client_name":f"{b.client.first_name} {b.client.last_name}" if b.client else "Unknown",
                     "services":services,"totals":{"sales_cash":cash_sales,"sales_non_cash":non_cash_sales,
                     "purchase_cash":cash_pur,"purchase_non_cash":non_cash_pur,"profit_cash":cash_profit,
                     "profit_non_cash":non_cash_profit,"discount":total_disc}})
    return JsonResponse({"data":data})
