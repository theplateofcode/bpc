from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required

from .models import (
    Ticket, Visa, Carrier, Passport, Insurance, Transfer,
    Hotel, ServiceList, SightSeeing
)
from .forms import (
    TicketForm, VisaForm, PassportForm,
    TransferForm, InsuranceForm, HotelForm, SightSeeingForm
)
from .utils.decorators import group_required, get_service_model

from suppliers.models import Supplier
from payments.models import Mode
from bookings.models import Booking, Status

from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Carrier
from .forms import CarrierForm

def is_owner_or_admin(user):
    return user.is_authenticated and (getattr(user, 'role', '') == 'OWNER' or getattr(user, 'role', '') == 'ADMIN')

def all_services_finished(booking):
        """Check if all service types are marked finished"""
        return all([
            booking.tickets_finished,
            booking.visas_finished,
            booking.hotels_finished,
            booking.insurances_finished,
            booking.transfers_finished,
            booking.sightseeings_finished,
            booking.passports_finished,
        ])


@login_required
@user_passes_test(is_owner_or_admin)
def carrier_list(request):
    carriers = Carrier.objects.all()
    return render(request, 'carriers/carriers_list.html', {'carriers': carriers})

@login_required
@user_passes_test(is_owner_or_admin)
def carrier_create(request):
    if request.method == 'POST':
        form = CarrierForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('carrier_list')
    else:
        form = CarrierForm()
    return render(request, 'carriers/carrier_form.html', {'form': form})

@login_required
@user_passes_test(is_owner_or_admin)
def carrier_update(request, pk):
    carrier = get_object_or_404(Carrier, pk=pk)
    if request.method == 'POST':
        form = CarrierForm(request.POST, instance=carrier)
        if form.is_valid():
            form.save()
            return redirect('carrier_list')
    else:
        form = CarrierForm(instance=carrier)
    return render(request, 'carriers/carrier_form.html', {'form': form})

@login_required
@user_passes_test(is_owner_or_admin)
def carrier_delete(request, pk):
    carrier = get_object_or_404(Carrier, pk=pk)
    if request.method == 'POST':
        carrier.delete()
        return redirect('carrier_list')
    return render(request, 'carriers/carrier_confirm_delete.html', {'carrier': carrier})

# Helper function to update booking flags
def update_booking_flag(booking, service_type):
    """Update the booking flag when all services of a type are finished"""
    # Map service model to booking flag name
    flag_map = {
        'ticket': 'tickets_finished',
        'visa': 'visas_finished',
        'hotel': 'hotels_finished',
        'insurance': 'insurances_finished',
        'transfer': 'transfers_finished',
        'sightseeing': 'sightseeings_finished',
        'passport': 'passports_finished',
    }
    
    flag_name = flag_map.get(service_type)
    if flag_name:
        # Check if all services of this type are finished
        service_model = get_service_model(service_type)
        unfinished_services = service_model.objects.filter(
            booking=booking,
            finished=False
        ).exists()
        
        # Update flag if no unfinished services remain
        if not unfinished_services:
            setattr(booking, flag_name, True)
            booking.save()
            
            # Check if all services are finished
            if all([
                booking.tickets_finished,
                booking.visas_finished,
                booking.hotels_finished,
                booking.insurances_finished,
                booking.transfers_finished,
                booking.sightseeings_finished,
                booking.passports_finished
            ]):
                booking.status = Status.objects.get(name='Closed')
                booking.save()

# Service marking views
# services/views.py
def mark_service_finished(request, service_type, pk):
    model = get_service_model(service_type)
    
    # Check if PK is for a service instance or booking
    try:
        # Try to get service instance
        service = model.objects.get(pk=pk)
        is_booking = False
    except model.DoesNotExist:
        # If not found, assume it's a booking ID
        booking = get_object_or_404(Booking, pk=pk)
        is_booking = True

    if request.method == 'POST':
        if is_booking:
            # Batch finishing for booking
            services = model.objects.filter(booking=booking)
            for s in services:
                s.finished = True
                s.save()
            
            # Update booking flag
            flag_name = f"{service_type}s_finished"
            setattr(booking, flag_name, True)
            booking.save()
            
            # Check if booking should be closed
            if booking.all_services_finished():
                booking.status = Status.objects.get(name='Closed')
                booking.save()
            
            return redirect(f'{service_type}_entries', booking_id=booking.id)
        else:
            # Single service finishing
            service.finished = True
            service.save()
            return redirect(f'{service_type}_entries', booking_id=service.booking.id)
    
    return redirect('home')


@group_required('Ticket_Dept')
def tickets(request):
    statuses = Status.objects.all().order_by('name')
    selected_status = request.GET.get('status', 'open')
    
    # Get Ticket service object
    ticket_service = ServiceList.objects.filter(name__iexact="Ticket").first()
    
    # Get bookings where user is assigned to Ticket service
    assigned_bookings = Booking.objects.filter(
        bookingservice__service=ticket_service,
        bookingservice__assigned_to=request.user
    ).distinct()

    # Apply status filter
    if selected_status.lower() != 'all':
        status_obj = Status.objects.filter(name__iexact=selected_status).first()
        if status_obj:
            assigned_bookings = assigned_bookings.filter(status=status_obj)

    return render(request, 'ticket/tickets.html', {
        'bookings': assigned_bookings,
        'statuses': statuses,
        'selected_status': selected_status,
    })





# --- Create Ticket Entry ---
@group_required('Ticket_Dept')
def create_ticket(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    # get all categoriessupplier categories
    supplier_categories = ServiceList.objects.all()
    if request.method == 'POST':
        form = TicketForm(request.POST, request.FILES)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.booking = booking
            ticket.created_by = request.user
            ticket.save()
            return redirect('ticket_entries', booking_id=booking.id)
    else:
        form = TicketForm(initial={'booking': booking})
    return render(request, 'ticket/forms/create.html', {'form': form, 'booking': booking, "supplier_categories": supplier_categories,})

@group_required('Ticket_Dept')# --- Edit Ticket Entry ---
def edit_ticket(request, ticket_id):
    ticket = get_object_or_404(Ticket, pk=ticket_id)
    booking = ticket.booking
    if request.method == 'POST':
        form = TicketForm(request.POST,request.FILES, instance=ticket)
        if form.is_valid():
            form.save()
            return redirect('ticket_entries', booking_id=booking.id)
    else:
        form = TicketForm(instance=ticket)
    return render(request, 'ticket/forms/edit.html', {'form': form, 'booking': booking, 'ticket': ticket})

@group_required('Ticket_Dept')# --- Delete Ticket Entry ---
def delete_ticket(request, ticket_id):
    ticket = get_object_or_404(Ticket, pk=ticket_id)
    booking_id = ticket.booking.id
    if request.method == 'POST':
        ticket.delete()
        return redirect('ticket_entries', booking_id=booking_id)
    return render(request, 'ticket/forms/delete.html', {'ticket': ticket})

@group_required('Passport_Dept')
def passports(request):
    statuses = Status.objects.all().order_by('name')
    selected_status = request.GET.get('status', 'open')
    passport_service = ServiceList.objects.get(name="Passport")
    
    assigned_bookings = Booking.objects.filter(
        bookingservice__service=passport_service,
        bookingservice__assigned_to=request.user
    ).distinct()

    if selected_status.lower() != 'all':
        status_obj = Status.objects.filter(name__iexact=selected_status).first()
        if status_obj:
            assigned_bookings = assigned_bookings.filter(status=status_obj)

    return render(request, 'passport/passport.html', {
        'bookings': assigned_bookings,
        'statuses': statuses,
        'selected_status': selected_status,
    })




# --- Create Ticket Entry ---
@group_required('Passport_Dept')
def create_passport(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    # get all categoriessupplier categories
    supplier_categories = ServiceList.objects.all()
    if request.method == 'POST':
        form = PassportForm(request.POST, request.FILES)
        if form.is_valid():
            passport = form.save(commit=False)
            passport.booking = booking
            passport.created_by = request.user

            passport.save()
            return redirect('passport_entries', booking_id=booking.id)
    else:
        form = PassportForm(initial={'booking': booking})
    return render(request, 'passport/forms/create.html', {'form': form, 'booking': booking, "supplier_categories": supplier_categories,})

# --- Edit Ticket Entry ---
@group_required('Passport_Dept')
def edit_passport(request, passport_id):
    passport = get_object_or_404(Passport, pk=passport_id)
    booking = passport.booking
    if request.method == 'POST':
        form = PassportForm(request.POST,request.FILES, instance=passport)
        if form.is_valid():
            form.save()
            return redirect('passport_entries', booking_id=booking.id)
    else:
        form = PassportForm(instance=passport)
    return render(request, 'passport/forms/edit.html', {'form': form, 'booking': booking, 'passport': passport})

# --- Delete Ticket Entry ---
@group_required('Passport_Dept')
def delete_passport(request, ticket_id):
    passport = get_object_or_404(Passport, pk=ticket_id)
    booking_id = passport.booking.id
    if request.method == 'POST':
        passport.delete()
        return redirect('passport_entries', booking_id=booking_id)
    return render(request, 'passport/forms/delete.html', {'passport': passport})



# ======================
# ==== Visa Views ======
# ======================
@group_required('Visa_Dept')
def visas(request):
    statuses = Status.objects.all().order_by('name')
    selected_status = request.GET.get('status', 'open')
    visa_service = ServiceList.objects.get(name="Visa")
    
    assigned_bookings = Booking.objects.filter(
        bookingservice__service=visa_service,
        bookingservice__assigned_to=request.user
    ).distinct()

    if selected_status.lower() != 'all':
        status_obj = Status.objects.filter(name__iexact=selected_status).first()
        if status_obj:
            assigned_bookings = assigned_bookings.filter(status=status_obj)

    return render(request, 'visa/visas.html', {
        'bookings': assigned_bookings,
        'statuses': statuses,
        'selected_status': selected_status,
    })



@group_required('Visa_Dept')
def create_visa(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    supplier_categories = ServiceList.objects.all()
    
    if request.method == 'POST':
        form = VisaForm(request.POST,request.FILES,)
        if form.is_valid():
            visa = form.save(commit=False)
            visa.booking = booking
            visa.created_by = request.user

            visa.save()
            return redirect('visa_entries', booking_id=booking.id)
    else:
        form = VisaForm(initial={'booking': booking})
        
    return render(request, 'visa/forms/create.html', {
        'form': form,
        'booking': booking,
        "supplier_categories": supplier_categories,
    })

@group_required('Visa_Dept')
def edit_visa(request, visa_id):
    visa = get_object_or_404(Visa, pk=visa_id)
    booking = visa.booking
    
    if request.method == 'POST':
        form = VisaForm(request.POST,request.FILES, instance=visa)
        if form.is_valid():
            form.save()
            return redirect('visa_entries', booking_id=booking.id)
    else:
        form = VisaForm(instance=visa)
        
    return render(request, 'visa/forms/edit.html', {
        'form': form,
        'booking': booking,
        'visa': visa,
    })

@group_required('Visa_Dept')
def delete_visa(request, visa_id):
    visa = get_object_or_404(Visa, pk=visa_id)
    booking_id = visa.booking.id
    
    if request.method == 'POST':
        visa.delete()
        return redirect('visa_entries', booking_id=booking_id)
        
    return render(request, 'visa/forms/delete.html', {'visa': visa})

# ======================
# === Insurance Views ==
# ======================
@group_required('Insurance_Dept')
def insurances(request):
    statuses = Status.objects.all().order_by('name')
    selected_status = request.GET.get('status', 'open')
    insurance_service = ServiceList.objects.get(name="Insurance")
    
    assigned_bookings = Booking.objects.filter(
        bookingservice__service=insurance_service,
        bookingservice__assigned_to=request.user
    ).distinct()

    if selected_status.lower() != 'all':
        status_obj = Status.objects.filter(name__iexact=selected_status).first()
        if status_obj:
            assigned_bookings = assigned_bookings.filter(status=status_obj)

    return render(request, 'insurance/insurances.html', {
        'bookings': assigned_bookings,
        'statuses': statuses,
        'selected_status': selected_status,
    })



@group_required('Insurance_Dept')
def create_insurance(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    supplier_categories = ServiceList.objects.all()
    
    if request.method == 'POST':
        form = InsuranceForm(request.POST,request.FILES,)
        if form.is_valid():
            insurance = form.save(commit=False)
            insurance.booking = booking
            insurance.created_by = request.user

            insurance.save()
            return redirect('insurance_entries', booking_id=booking.id)
    else:
        form = InsuranceForm(initial={'booking': booking})
        
    return render(request, 'insurance/forms/create.html', {
        'form': form,
        'booking': booking,
        "supplier_categories": supplier_categories,
    })

@group_required('Insurance_Dept')
def edit_insurance(request, insurance_id):
    insurance = get_object_or_404(Insurance, pk=insurance_id)
    booking = insurance.booking
    
    if request.method == 'POST':
        form = InsuranceForm(request.POST,request.FILES, instance=insurance)
        if form.is_valid():
            form.save()
            return redirect('insurance_entries', booking_id=booking.id)
    else:
        form = InsuranceForm(instance=insurance)
        
    return render(request, 'insurance/forms/edit.html', {
        'form': form,
        'booking': booking,
        'insurance': insurance,
    })

@group_required('Insurance_Dept')
def delete_insurance(request, insurance_id):
    insurance = get_object_or_404(Insurance, pk=insurance_id)
    booking_id = insurance.booking.id
    
    if request.method == 'POST':
        insurance.delete()
        return redirect('insurance_entries', booking_id=booking_id)
        
    return render(request, 'insurance/forms/delete.html', {'insurance': insurance})

def mark_insurance_ready(request, pk):
    insurance = get_object_or_404(Insurance, pk=pk)
    if request.method == 'POST':
        insurance.status = 'ready'  # or ServiceStatus.READY_FOR_ACCOUNTS if you use choices
        insurance.created_by = request.user

        insurance.save()
        messages.success(request, "Marked as ready for accounts.")
    return redirect('insurance_entries', booking_id=insurance.booking.id)

# ======================
# ==== Hotel Views =====
# ======================
@group_required('Hotel_Dept')
def hotels(request):
    statuses = Status.objects.all().order_by('name')
    selected_status = request.GET.get('status', 'open')
    hotel_service = ServiceList.objects.get(name="Hotel")
    
    assigned_bookings = Booking.objects.filter(
        bookingservice__service=hotel_service,
        bookingservice__assigned_to=request.user
    ).distinct()

    if selected_status.lower() != 'all':
        status_obj = Status.objects.filter(name__iexact=selected_status).first()
        if status_obj:
            assigned_bookings = assigned_bookings.filter(status=status_obj)

    return render(request, 'hotel/hotels.html', {
        'bookings': assigned_bookings,
        'statuses': statuses,
        'selected_status': selected_status,
    })



@group_required('Hotel_Dept')
def create_hotel(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    supplier_categories = ServiceList.objects.all()
    if request.method == 'POST':
        form = HotelForm(request.POST,request.FILES,)
        if form.is_valid():
            hotel = form.save(commit=False)
            hotel.booking = booking
            hotel.created_by = request.user

            hotel.save()
            return redirect('hotel_entries', booking_id=booking.id)
    else:
        form = HotelForm(initial={'booking': booking})
    return render(request, 'hotel/forms/create.html', {
        'form': form,
        'booking': booking,
        "supplier_categories": supplier_categories,
    })

@group_required('Hotel_Dept')
def edit_hotel(request, hotel_id):
    hotel = get_object_or_404(Hotel, pk=hotel_id)
    booking = hotel.booking
    if request.method == 'POST':
        form = HotelForm(request.POST,request.FILES, instance=hotel)
        if form.is_valid():
            form.save()
            return redirect('hotel_entries', booking_id=booking.id)
    else:
        form = HotelForm(instance=hotel)
    return render(request, 'hotel/forms/edit.html', {
        'form': form,
        'booking': booking,
        'hotel': hotel,
    })

@group_required('Hotel_Dept')
def delete_hotel(request, hotel_id):
    hotel = get_object_or_404(Hotel, pk=hotel_id)
    booking_id = hotel.booking.id
    if request.method == 'POST':
        hotel.delete()
        return redirect('hotel_entries', booking_id=booking_id)
    return render(request, 'hotel/forms/delete.html', {'hotel': hotel})


# ======================
# == Sightseeing Views =
# ======================
@group_required('Sightseeing_Dept')
def sightseeings(request):
    statuses = Status.objects.all().order_by('name')
    selected_status = request.GET.get('status', 'open')
    sightseeing_service = ServiceList.objects.get(name="Sightseeing")
    
    assigned_bookings = Booking.objects.filter(
        bookingservice__service=sightseeing_service,
        bookingservice__assigned_to=request.user
    ).distinct()

    if selected_status.lower() != 'all':
        status_obj = Status.objects.filter(name__iexact=selected_status).first()
        if status_obj:
            assigned_bookings = assigned_bookings.filter(status=status_obj)

    return render(request, 'sightseeing/sightseeings.html', {
        'bookings': assigned_bookings,
        'statuses': statuses,
        'selected_status': selected_status,
    })




@group_required('Sightseeing_Dept')
def create_sightseeing(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    supplier_categories = ServiceList.objects.all()
    if request.method == 'POST':
        form = SightSeeingForm(request.POST,request.FILES,)
        if form.is_valid():
            sightseeing = form.save(commit=False)
            sightseeing.booking = booking
            sightseeing.created_by = request.user

            sightseeing.save()
            return redirect('sightseeing_entries', booking_id=booking.id)
    else:
        form = SightSeeingForm(initial={'booking': booking})
    return render(request, 'sightseeing/forms/create.html', {
        'form': form,
        'booking': booking,
        "supplier_categories": supplier_categories,
    })

@group_required('Sightseeing_Dept')
def edit_sightseeing(request, sightseeing_id):
    sightseeing = get_object_or_404(SightSeeing, pk=sightseeing_id)
    booking = sightseeing.booking
    if request.method == 'POST':
        form = SightSeeingForm(request.POST,request.FILES, instance=sightseeing)
        if form.is_valid():
            form.save()
            return redirect('sightseeing_entries', booking_id=booking.id)
    else:
        form = SightSeeingForm(instance=sightseeing)
    return render(request, 'sightseeing/forms/edit.html', {
        'form': form,
        'booking': booking,
        'sightseeing': sightseeing,
    })

@group_required('Sightseeing_Dept')
def delete_sightseeing(request, sightseeing_id):
    sightseeing = get_object_or_404(SightSeeing, pk=sightseeing_id)
    booking_id = sightseeing.booking.id
    if request.method == 'POST':
        sightseeing.delete()
        return redirect('sightseeing_entries', booking_id=booking_id)
    return render(request, 'sightseeing/forms/delete.html', {'sightseeing': sightseeing})


# ======================
# === Transfer Views ===
# ======================
@group_required('Transfer_Dept')
def transfers(request):
    statuses = Status.objects.all().order_by('name')
    selected_status = request.GET.get('status', 'open')
    transfer_service = ServiceList.objects.get(name="Transfer")
    
    assigned_bookings = Booking.objects.filter(
        bookingservice__service=transfer_service,
        bookingservice__assigned_to=request.user
    ).distinct()

    if selected_status.lower() != 'all':
        status_obj = Status.objects.filter(name__iexact=selected_status).first()
        if status_obj:
            assigned_bookings = assigned_bookings.filter(status=status_obj)

    return render(request, 'transfer/transfers.html', {
        'bookings': assigned_bookings,
        'statuses': statuses,
        'selected_status': selected_status,
    })
 



@group_required('Transfer_Dept')
def create_transfer(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    supplier_categories = ServiceList.objects.all()
    if request.method == 'POST':
        form = TransferForm(request.POST,request.FILES,)
        if form.is_valid():
            transfer = form.save(commit=False)
            transfer.booking = booking
            transfer.created_by = request.user

            transfer.save()
            return redirect('transfer_entries', booking_id=booking.id)
    else:
        form = TransferForm(initial={'booking': booking})
    return render(request, 'transfer/forms/create.html', {
        'form': form,
        'booking': booking,
        "supplier_categories": supplier_categories,
    })

@group_required('Transfer_Dept')
def edit_transfer(request, transfer_id):
    transfer = get_object_or_404(Transfer, pk=transfer_id)
    booking = transfer.booking
    if request.method == 'POST':
        form = TransferForm(request.POST,request.FILES, instance=transfer)
        if form.is_valid():
            form.save()
            return redirect('transfer_entries', booking_id=booking.id)
    else:
        form = TransferForm(instance=transfer)
    return render(request, 'transfer/forms/edit.html', {
        'form': form,
        'booking': booking,
        'transfer': transfer,
    })

@group_required('Transfer_Dept')
def delete_transfer(request, transfer_id):
    transfer = get_object_or_404(Transfer, pk=transfer_id)
    booking_id = transfer.booking.id
    if request.method == 'POST':
        transfer.delete()
        return redirect('transfer_entries', booking_id=booking_id)
    return render(request, 'transfer/forms/delete.html', {'transfer': transfer})


from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from bookings.models import Booking, Status
from services.models import Ticket, Visa, Hotel, Transfer, Passport, Insurance, SightSeeing

def ticket_entries(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    tickets = booking.tickets.all()
    
    # Check if all tickets are finished
    all_finished = not tickets.filter(finished=False).exists()
    
    if request.method == 'POST' and all_finished and not booking.tickets_finished:
        booking.tickets_finished = True
        booking.save()
        
        # Check if all services are finished to close booking
        if booking.all_services_finished():
            booking.status = Status.objects.get(name='Closed')
            booking.save()
            messages.success(request, "All services completed! Booking closed.")
        
        return redirect('ticket_entries', booking_id=booking_id)
    
    return render(request, 'ticket/ticket_entries.html', {
        'booking': booking,
        'tickets': tickets,
        'all_finished': all_finished,
    })

def visa_entries(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    visas = booking.visas.all()
    all_finished = not visas.filter(finished=False).exists()
    
    if request.method == 'POST' and all_finished and not booking.visas_finished:
        booking.visas_finished = True
        booking.save()
        
        if booking.all_services_finished():
            booking.status = Status.objects.get(name='Closed')
            booking.save()
            messages.success(request, "All services completed! Booking closed.")
        
        return redirect('visa_entries', booking_id=booking_id)
    
    return render(request, 'visa/visa_entries.html', {
        'booking': booking,
        'visas': visas,
        'all_finished': all_finished,
    })

def hotel_entries(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    hotels = booking.hotels.all()
    all_finished = not hotels.filter(finished=False).exists()
    
    if request.method == 'POST' and all_finished and not booking.hotels_finished:
        booking.hotels_finished = True
        booking.save()
        
        if booking.all_services_finished():
            booking.status = Status.objects.get(name='Closed')
            booking.save()
            messages.success(request, "All services completed! Booking closed.")
        
        return redirect('hotel_entries', booking_id=booking_id)
    
    return render(request, 'hotel/hotel_entries.html', {
        'booking': booking,
        'hotels': hotels,
        'all_finished': all_finished,
    })

def insurance_entries(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    insurances = booking.insurances.all()
    all_finished = not insurances.filter(finished=False).exists()
    
    if request.method == 'POST' and all_finished and not booking.insurances_finished:
        booking.insurances_finished = True
        booking.save()
        
        if booking.all_services_finished():
            booking.status = Status.objects.get(name='Closed')
            booking.save()
            messages.success(request, "All services completed! Booking closed.")
        
        return redirect('insurance_entries', booking_id=booking_id)
    
    return render(request, 'insurance/insurance_entries.html', {
        'booking': booking,
        'insurances': insurances,
        'all_finished': all_finished,
    })

def transfer_entries(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    transfers = booking.transfers.all()
    all_finished = not transfers.filter(finished=False).exists()
    
    if request.method == 'POST' and all_finished and not booking.transfers_finished:
        booking.transfers_finished = True
        booking.save()
        
        if booking.all_services_finished():
            booking.status = Status.objects.get(name='Closed')
            booking.save()
            messages.success(request, "All services completed! Booking closed.")
        
        return redirect('transfer_entries', booking_id=booking_id)
    
    return render(request, 'transfer/transfer_entries.html', {
        'booking': booking,
        'transfers': transfers,
        'all_finished': all_finished,
    })

def sightseeing_entries(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    sightseeings = booking.sightseeings.all()
    all_finished = not sightseeings.filter(finished=False).exists()
    
    if request.method == 'POST' and all_finished and not booking.sightseeings_finished:
        booking.sightseeings_finished = True
        booking.save()
        
        if booking.all_services_finished():
            booking.status = Status.objects.get(name='Closed')
            booking.save()
            messages.success(request, "All services completed! Booking closed.")
        
        return redirect('sightseeing_entries', booking_id=booking_id)
    
    return render(request, 'sightseeing/sightseeing_entries.html', {
        'booking': booking,
        'sightseeings': sightseeings,
        'all_finished': all_finished,
    })

def passport_entries(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    passports = booking.passports.all()
    all_finished = not passports.filter(finished=False).exists()
    
    if request.method == 'POST' and all_finished and not booking.passports_finished:
        booking.passports_finished = True
        booking.save()
        
        if booking.all_services_finished():
            booking.status = Status.objects.get(name='Closed')
            booking.save()
            messages.success(request, "All services completed! Booking closed.")
        
        return redirect('passport_entries', booking_id=booking_id)
    
    return render(request, 'passport/passport_entries.html', {
        'booking': booking,
        'passports': passports,
        'all_finished': all_finished,
    })




def carrier_autocomplete(request):
    q = request.GET.get('q', '')
    lookup_id = request.GET.get('id')
    if lookup_id:
        carriers = Carrier.objects.filter(id=lookup_id)
    else:
        carriers = Carrier.objects.filter(name__icontains=q)[:10]
    results = [{'id': c.id, 'name': c.name} for c in carriers]
    return JsonResponse({'results': results})

def supplier_autocomplete(request):
    q = request.GET.get('q', '')
    lookup_id = request.GET.get('id')
    if lookup_id:
        suppliers = Supplier.objects.filter(id=lookup_id)
    else:
        suppliers = Supplier.objects.filter(name__icontains=q)[:10]
    results = [{'id': s.id, 'name': s.name} for s in suppliers]
    return JsonResponse({'results': results})


@csrf_exempt
def create_carrier_ajax(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        if not name:
            return JsonResponse({'success': False, 'error': 'Name is required'})
        carrier = Carrier.objects.create(name=name)
        return JsonResponse({'success': True, 'id': carrier.id, 'name': carrier.name})
    return JsonResponse({'success': False})

@csrf_exempt
def create_supplier_ajax(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        category_id = request.POST.get('category')
        
        if not name or not category_id:
            return JsonResponse({'success': False, 'error': 'All fields are required'})
        
        # Check for existing supplier with same name (case-insensitive)
        if Supplier.objects.filter(name__iexact=name).exists():
            return JsonResponse({
                'success': False,
                'error': 'Supplier already exists with this name'
            })
        
        try:
            category = ServiceList.objects.get(id=category_id)
            supplier = Supplier.objects.create(name=name, category=category)
            return JsonResponse({
                'success': True,
                'id': supplier.id,
                'name': supplier.name
            })
        except ServiceList.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Invalid category'})
    return JsonResponse({'success': False})


def mode_autocomplete(request):
    q = request.GET.get('q', '')
    lookup_id = request.GET.get('id')
    if lookup_id:
        modes = Mode.objects.filter(id=lookup_id)
    else:
        modes = Mode.objects.filter(name__icontains=q)[:10]
    results = [{'id': m.id, 'name': m.name} for m in modes]
    return JsonResponse({'results': results})

@csrf_exempt
def create_mode_ajax(request):
    if request.method == "POST":
        name = request.POST.get("name")
        if not name:
            return JsonResponse({"success": False, "error": "Name required."})
        mode = Mode.objects.create(name=name)
        return JsonResponse({"success": True, "id": mode.id, "name": mode.name})
    return JsonResponse({"success": False, "error": "Invalid request."})