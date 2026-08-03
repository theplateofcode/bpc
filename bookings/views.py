from django.http import JsonResponse
from django.db.models import Q
from django.contrib.auth import get_user_model
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.core.exceptions import PermissionDenied
from django.template.loader import render_to_string
from django.core.paginator import Paginator
from xhtml2pdf import pisa
from decimal import Decimal
from .models import Booking, BookingService
from .forms import BookingForm
from services.models import ServiceList

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Status
from .forms import StatusForm
from django.contrib.auth.decorators import login_required



def is_owner_or_admin(user):
    return user.is_authenticated and (getattr(user, 'role', '') == 'OWNER' or getattr(user, 'role', '') == 'ADMIN')


def can_modify_bookings(user):
    return user.is_authenticated and getattr(user, 'role', '') in ['OWNER', 'ADMIN']



@login_required(login_url='/users/login/')
@user_passes_test(is_owner_or_admin)
def status_list(request):
    statuses = Status.objects.all()
    return render(request, 'status_list.html', {'statuses': statuses})



@login_required(login_url='/users/login/')
@user_passes_test(is_owner_or_admin)
def status_create(request):
    if request.method == 'POST':
        form = StatusForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('status_list')
    else:
        form = StatusForm()
    return render(request, 'forms/status_form.html', {'form': form})



@login_required(login_url='/users/login/')
@user_passes_test(is_owner_or_admin)
def status_update(request, pk):
    status = get_object_or_404(Status, pk=pk)
    if request.method == 'POST':
        form = StatusForm(request.POST, instance=status)
        if form.is_valid():
            form.save()
            return redirect('status_list')
    else:
        form = StatusForm(instance=status)
    return render(request, 'forms/status_form.html', {'form': form})



@login_required(login_url='/users/login/')
@user_passes_test(is_owner_or_admin)
def status_delete(request, pk):
    status = get_object_or_404(Status, pk=pk)
    if request.method == 'POST':
        status.delete()
        return redirect('status_list')
    return render(request, 'forms/status_confirm_delete.html', {'status': status})


from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from decimal import Decimal
from .models import Booking

from django.db.models import (
    Sum, Q, DecimalField, F, Case, When, Value, 
    Min, Max, Avg, Count
)
from django.db.models.functions import Coalesce, Least
from urllib.parse import urlencode


BOOKINGS_PAGE_SIZE = 20
BOOKING_FILTERABLE_COLUMNS = {
    "booking_id": "text",
    "created_by": "text",
    "booking_date": "date",
    "client_name": "text",
    "services": "text",
    "total_p_cost": "number",
    "total_s_cost": "number",
    "total_gst": "number",
    "net_profit": "number",
    "status": "text",
}


def _booking_base_queryset(request):
    # with_service_rows() prefetches the seven service tables (and their modes)
    # that the money properties read. Without it each rendered row costs 76
    # queries; with it the whole page costs a fixed handful.
    qs = (
        Booking.objects
        .select_related("client", "created_by", "status")
        .prefetch_related("services")
        .with_service_rows()
    )

    if request.user.role in ["OWNER", "ADMIN"]:
        pass
    else:
        qs = qs.filter(created_by=request.user)

    mode_filter = request.GET.get("mode")
    if mode_filter:
        qs = qs.filter(
            Q(tickets__mode=mode_filter) |
            Q(visas__mode=mode_filter) |
            Q(passports__mode=mode_filter) |
            Q(insurances__mode=mode_filter) |
            Q(hotels__mode=mode_filter) |
            Q(sightseeings__mode=mode_filter) |
            Q(transfers__mode=mode_filter)
        ).distinct()

    return qs


def _booking_services_text(booking):
    return ", ".join(service_name for service_name, _ in booking.get_service_statuses())


def _booking_created_by_text(booking):
    if not booking.created_by:
        return ""
    return booking.created_by.get_full_name() or booking.created_by.username or str(booking.created_by)


def _booking_client_name_text(booking):
    return str(booking.client) if booking.client else ""


def _booking_status_text(booking):
    return booking.status.name if booking.status else ""


def _booking_sort_filter_value(booking, col):
    if col == "booking_id":
        return booking.booking_id or ""
    if col == "created_by":
        return _booking_created_by_text(booking)
    if col == "booking_date":
        return booking.booking_date
    if col == "client_name":
        return _booking_client_name_text(booking)
    if col == "services":
        return _booking_services_text(booking)
    if col == "total_p_cost":
        return booking.purchase_total
    if col == "total_s_cost":
        return booking.sales_total
    if col == "total_gst":
        return booking.sales_gst
    if col == "net_profit":
        return booking.net_profit
    if col == "status":
        return _booking_status_text(booking)
    return ""


def _normalize_text(value):
    if value is None:
        return ""
    return str(value).strip().lower()


def _normalize_number(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _matches_filter(actual, col_type, op, expected_raw):
    if expected_raw in (None, ""):
        return True

    if col_type == "number":
        actual_num = _normalize_number(actual)
        expected_num = _normalize_number(expected_raw)
        if actual_num is None or expected_num is None:
            return False
        if op == "eq":
            return actual_num == expected_num
        if op == "gt":
            return actual_num > expected_num
        if op == "lt":
            return actual_num < expected_num
        if op == "gte":
            return actual_num >= expected_num
        if op == "lte":
            return actual_num <= expected_num
        return True

    if col_type == "date":
        actual_text = actual.isoformat() if actual else ""
        if op == "eq":
            return actual_text == expected_raw
        if op == "gt":
            return actual_text > expected_raw
        if op == "lt":
            return actual_text < expected_raw
        return True

    actual_text = _normalize_text(actual)
    expected_text = _normalize_text(expected_raw)
    if op == "equals":
        return actual_text == expected_text
    return expected_text in actual_text


def _sort_key_for_booking(booking, col):
    value = _booking_sort_filter_value(booking, col)
    col_type = BOOKING_FILTERABLE_COLUMNS.get(col, "text")
    if col_type == "number":
        return (_normalize_number(value) is None, _normalize_number(value) or Decimal("0"))
    if col_type == "date":
        return (value is None, value)
    return _normalize_text(value)


def _build_rows_context(request):
    sort_col = request.GET.get("sort_col", "booking_id")
    sort_dir = request.GET.get("sort_dir", "desc")
    page_number = request.GET.get("page", 1)

    qs = _booking_base_queryset(request)
    needs_python_processing = sort_col in {"created_by", "client_name", "services", "total_p_cost", "total_s_cost", "total_gst", "net_profit"}

    active_filters = []
    for col, col_type in BOOKING_FILTERABLE_COLUMNS.items():
        op = request.GET.get(f"f_{col}_op", "contains" if col_type == "text" else "eq")
        val = request.GET.get(f"f_{col}_val", "")
        if val:
            active_filters.append({"col": col, "op": op, "val": val, "type": col_type})
            if col in {"created_by", "client_name", "services", "total_p_cost", "total_s_cost", "total_gst", "net_profit"}:
                needs_python_processing = True

    if not needs_python_processing:
        if sort_col == "booking_date":
            qs = qs.order_by("booking_date" if sort_dir == "asc" else "-booking_date", "id" if sort_dir == "asc" else "-id")
        elif sort_col == "booking_id":
            qs = qs.order_by("booking_id" if sort_dir == "asc" else "-booking_id")
        elif sort_col == "status":
            qs = qs.order_by("status__name" if sort_dir == "asc" else "-status__name", "id" if sort_dir == "asc" else "-id")

        for item in active_filters:
            col = item["col"]
            op = item["op"]
            val = item["val"]
            if col == "booking_id":
                if op == "equals":
                    qs = qs.filter(booking_id__iexact=val)
                else:
                    qs = qs.filter(booking_id__icontains=val)
            elif col == "booking_date":
                lookup = {"eq": "booking_date", "gt": "booking_date__gt", "lt": "booking_date__lt"}.get(op, "booking_date")
                qs = qs.filter(**{lookup: val})
            elif col == "status":
                if op == "equals":
                    qs = qs.filter(status__name__iexact=val)
                else:
                    qs = qs.filter(status__name__icontains=val)

        paginator = Paginator(qs, BOOKINGS_PAGE_SIZE)
        page_obj = paginator.get_page(page_number)
    else:
        bookings_list = list(qs)
        for item in active_filters:
            bookings_list = [
                booking for booking in bookings_list
                if _matches_filter(
                    _booking_sort_filter_value(booking, item["col"]),
                    item["type"],
                    item["op"],
                    item["val"],
                )
            ]

        reverse = sort_dir == "desc"
        bookings_list.sort(key=lambda booking: _sort_key_for_booking(booking, sort_col), reverse=reverse)
        paginator = Paginator(bookings_list, BOOKINGS_PAGE_SIZE)
        page_obj = paginator.get_page(page_number)

    query_params = request.GET.copy()
    query_params.pop("page", None)
    next_querystring = ""
    if page_obj.has_next():
        next_params = query_params.copy()
        next_params["page"] = page_obj.next_page_number()
        next_querystring = urlencode(next_params, doseq=True)

    return {
        "page_obj": page_obj,
        "current_mode": request.GET.get("mode"),
        "sort_col": sort_col,
        "sort_dir": sort_dir,
        "next_querystring": next_querystring,
    }


@login_required(login_url='/users/login/')
def bookings(request):
    context = _build_rows_context(request)
    context["can_modify_bookings"] = can_modify_bookings(request.user)
    return render(request, 'bookings.html', context)


@login_required(login_url='/users/login/')
def booking_rows(request):
    return render(request, 'bookings/_booking_rows.html', _build_rows_context(request))

User = get_user_model()


@login_required(login_url='/users/login/')
def create_booking(request):
    service_list = ServiceList.objects.all()
    assignable_users = User.objects.filter(is_active=True)

    if request.method == 'POST':
        form = BookingForm(request.POST)
        if form.is_valid():
            # Get client ID from hidden input
            client_id = request.POST.get('client')
            if not client_id:
                form.add_error(None, "Client is required")
                return render(request, 'forms/create_booking.html', {
                    'form': form,
                    'service_list': service_list,
                    'assignable_users': assignable_users
                })

            # Save main booking
            booking = form.save(commit=False)
            booking.created_by = request.user
            booking.client_id = client_id  # Set client directly
            booking.save()

            # Save service assignments
            selected_services = request.POST.getlist('services')
            for service_id in selected_services:
                user_id = request.POST.get(f'assigned_to_{service_id}')
                if user_id:
                    BookingService.objects.create(
                        booking=booking,
                        service_id=service_id,
                        assigned_to_id=user_id
                    )

            return redirect('bookings')
    else:
        form = BookingForm()

    return render(request, 'forms/create_booking.html', {
        'form': form,
        'service_list': service_list,
        'assignable_users': assignable_users
    })




@login_required(login_url='/users/login/')
def edit_booking(request, pk):
    if not can_modify_bookings(request.user):
        raise PermissionDenied("You do not have permission to edit bookings.")

    booking = get_object_or_404(Booking, pk=pk)
    
    # Prepare context data (needed for both GET and POST)
    service_list = ServiceList.objects.all()
    assignable_users = User.objects.filter(is_active=True)
    selected_services = list(booking.services.values_list('id', flat=True))
    assignments = {
        bs.service_id: bs.assigned_to_id
        for bs in BookingService.objects.filter(booking=booking)
    }

    if request.method == 'POST':
        form = BookingForm(request.POST, instance=booking)
        if form.is_valid():
            # Save form data first
            booking = form.save(commit=False)
            
            # Handle client update
            client_id = request.POST.get('client')
            if client_id:
                try:
                    booking.client_id = int(client_id)
                except (ValueError, TypeError):
                    # Handle invalid client ID
                    pass
            booking.save()
            
            # Handle services and assignments
            service_ids = request.POST.getlist('services')
            booking.services.set(service_ids)
            
            for service_id in service_ids:
                assignee_id = request.POST.get(f'assigned_to_{service_id}')
                booking_service, _ = BookingService.objects.get_or_create(
                    booking=booking,
                    service_id=service_id
                )
                booking_service.assigned_to_id = assignee_id or None
                booking_service.save()
            
            return redirect('bookings')
    else:
        form = BookingForm(instance=booking)
    
    # Return response for both cases:
    # 1. GET requests
    # 2. POST requests with invalid form
    return render(request, 'forms/edit_booking.html', {
        'form': form,
        'booking': booking,
        'service_list': service_list,
        'assignable_users': assignable_users,
        'selected_services': selected_services,
        'assignments': assignments,
    })

from django.db import transaction

@login_required(login_url='/users/login/')
def delete_booking(request, pk):
    if not can_modify_bookings(request.user):
        raise PermissionDenied("You do not have permission to delete bookings.")

    booking = get_object_or_404(Booking, pk=pk)
    if request.method == 'POST':
        try:
            with transaction.atomic():
                booking.delete()
            return redirect('bookings')
        except Exception as e:
            # Handle error appropriately
            return render(request, 'error.html', {'error': str(e)})
    return render(request, 'forms/delete_booking.html', {'booking': booking})




# PDF Generation Views and Helpers


def service_summary(qs, service_type=None):
    summary = []
    gst_rate = Decimal('0.18')
    for obj in qs:
        is_cash = hasattr(obj, 'mode') and getattr(obj.mode, 'name', '').lower() == 'cash'
        base_amount = obj.sales_amount - obj.purchase_amount

        # GST logic
        if service_type == 'Tickets':
            gst = base_amount * gst_rate
        else:
            gst = Decimal('0') if is_cash else base_amount * gst_rate

        profit = base_amount - gst

        # TCS logic (for package services only)
        tcs = Decimal('0')
        if service_type in ['Hotels', 'Transfers', 'Sightseeings']:
            if not is_cash and getattr(obj, 'travel_type', '').lower() == 'international':
                tcs = obj.sales_amount * Decimal('0.02')

        travel_type = getattr(obj, 'travel_type', None)
        mode_name = getattr(obj.mode, 'name', '-') if hasattr(obj, 'mode') else '-'

        summary.append({
            'id': obj.id,
            'purchase': obj.purchase_amount,
            'sales': obj.sales_amount,
            'gst': gst,
            'profit': profit,
            'tcs_amount': tcs,
            'supplier': obj.supplier if hasattr(obj, 'supplier') else None,
            'type': obj._meta.verbose_name.title(),
            'attachment': getattr(obj, 'attachment', None),
            'travel_type': travel_type,
            'mode': mode_name,  # <-- Add this line
        })
    return summary

def booking_pdf(request, booking_id):
    # Joins supplier (rendered per row) and mode (read by service_summary and by
    # booking.tcs_amount) in the same pass as the service rows themselves.
    booking = get_object_or_404(
        Booking.objects.select_related('client').with_service_rows('supplier'),
        id=booking_id,
    )
    client = booking.client
    #get me the supplier details iterable from each supplier in each service
    if not client:
        return HttpResponse('Client not found', status=404)
    if not booking:
        return HttpResponse('Booking not found', status=404)

    services_data = {
        'Tickets': service_summary(booking.tickets.all()),
        'Visas': service_summary(booking.visas.all()),
        'Hotels': service_summary(booking.hotels.all()),
        'Insurances': service_summary(booking.insurances.all()),
        'Transfers': service_summary(booking.transfers.all()),
        'Sightseeings': service_summary(booking.sightseeings.all()),
        'Passports': service_summary(booking.passports.all()),
    }

    all_services = [s for service_list in services_data.values()
                    for s in service_list]

    totals = {
        'total_purchase': sum(s['purchase'] for s in all_services),
        'total_sales': sum(s['sales'] for s in all_services),
        'total_tcs': booking.tcs_amount,
        'total_gst': sum(s['gst'] for s in all_services),
        'net_profit': sum(s['profit'] for s in all_services),
    }

    context = {
        'booking': booking,
        'client': client,
        'services_data': services_data,
        'totals': totals,
    }

    html = render_to_string('bookings/booking_pdf.html', context)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'inline;filename="Booking_{booking.booking_id}.pdf"'

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('PDF generation error')
    return response


# bookings/views.py


