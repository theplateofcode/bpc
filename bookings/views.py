from django.http import JsonResponse
from django.db.models import Q
from django.contrib.auth import get_user_model
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.template.loader import render_to_string
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


@login_required(login_url='/users/login/')
def bookings(request):
    # Role-based filtering
    if request.user.role in ['OWNER', 'ADMIN']:
        bookings = Booking.objects.all().prefetch_related(
            'tickets', 'passports', 'visas', 'insurances',
            'hotels', 'sightseeings', 'transfers'
        )
    else:
        bookings = Booking.objects.filter(created_by=request.user).prefetch_related(
            'tickets', 'passports', 'visas', 'insurances',
            'hotels', 'sightseeings', 'transfers'
        )

    # Payment mode filtering
    mode_filter = request.GET.get('mode')
    if mode_filter:
        bookings = bookings.filter(
            Q(tickets__mode=mode_filter) |
            Q(visas__mode=mode_filter) |
            Q(passports__mode=mode_filter) |
            Q(insurances__mode=mode_filter) |
            Q(hotels__mode=mode_filter) |
            Q(sightseeings__mode=mode_filter) |
            Q(transfers__mode=mode_filter)
        ).distinct()

    return render(request, 'bookings.html', {
        'bookings': bookings,
        'current_mode': mode_filter
    })

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
    booking = get_object_or_404(Booking, pk=pk)
    if request.method == 'POST':
        form = BookingForm(request.POST, instance=booking)
        if form.is_valid():
            form.save()
            return redirect('bookings')
    else:
        form = BookingForm(instance=booking)

    # These are required for the service assignment grid:
    service_list = ServiceList.objects.all()
    assignable_users = User.objects.filter(is_active=True)
    selected_services = list(booking.services.values_list('id', flat=True))
    assignments = {
        bs.service_id: bs.assigned_to_id
        for bs in BookingService.objects.filter(booking=booking)
    }

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
                tcs = obj.sales_amount * Decimal('0.05')

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
            'attachment': obj.attachment if hasattr(obj, 'attachment') else None,
            'travel_type': travel_type,
            'mode': mode_name,  # <-- Add this line
        })
    return summary

def booking_pdf(request, booking_id):
    booking = get_object_or_404(Booking.objects.prefetch_related(
        'tickets__supplier',
        'visas__supplier',
        'hotels__supplier',
        'insurances__supplier',
        'transfers__supplier',
        'sightseeings__supplier',
        'passports__supplier'
    ), id=booking_id)
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


