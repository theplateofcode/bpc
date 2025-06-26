from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import user_passes_test
from django.views.generic import ListView
from django.utils.decorators import method_decorator
from decimal import Decimal
from services.models import Ticket, Visa, Hotel, Transfer, Passport, Insurance, SightSeeing
from bookings.models import Booking
from bookings.views import service_summary
from services.utils.decorators import get_service_model
from collections import defaultdict
from django.contrib.auth.decorators import login_required


def is_accountant(user):
    return user.is_authenticated and getattr(user, 'role', '').upper() == 'ACCOUNTANT'



@method_decorator(user_passes_test(is_accountant), name='dispatch')
class AccountTodoView(ListView):
    template_name = 'todo_services.html'
    context_object_name = 'services'

    def get_queryset(self):
        services = []
        for model in [Ticket, Visa, Hotel, Transfer, Passport, Insurance, SightSeeing]:
            services.extend(
                model.objects.filter(finished=True, accounts_processed=False)
                .select_related('booking__client', 'booking__created_by', 'created_by')
            )
        return sorted(services, key=lambda x: x.booking.booking_date)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        group_by = self.request.GET.get('group_by', '')
        grouped_services = {}
        
        if group_by == 'booking':
            # Group by Booking with service status
            for service in context['services']:
                booking = service.booking
                if booking not in grouped_services:
                    grouped_services[booking] = []
                grouped_services[booking].append(service)
        
        elif group_by == 'user':
            # Group by Service Created By
            for service in context['services']:
                user = service.created_by or 'Unassigned'
                if user not in grouped_services:
                    grouped_services[user] = []
                grouped_services[user].append(service)
        
        context['group_by'] = group_by
        context['grouped_services'] = grouped_services
        return context


@login_required(login_url='/users/login/')
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
        'total_purchase': sum(s['purchase'] for s in all_services),
        'total_sales': sum(s['sales'] for s in all_services),
        'total_gst': sum(s['gst'] for s in all_services),
        'net_profit': sum(s['profit'] for s in all_services),
        'total_tcs': booking.tcs_amount,
    }

    context = {
        'booking': booking,
        'client': client,
        'services_data': services_data,
        'totals': totals,
        'show_pdf_controls': True,
    }

    if request.method == 'POST':
        # Mark service as processed by accounts
        service.accounts_processed = True
        service.save()
        return redirect('accounts_todo')

    return render(request, 'process_service.html', context)

@user_passes_test(is_accountant)
def processed_services(request):
    processed = []
    booking_tcs_map = {}

    for model in [Ticket, Visa, Hotel, Transfer, Passport, Insurance, SightSeeing]:
        # Get services processed by accounts
        services = model.objects.filter(accounts_processed=True).select_related('booking__client')
        processed.extend(services)
        
        for service in services:
            booking = service.booking
            if booking.id not in booking_tcs_map:
                booking_tcs_map[booking.id] = booking.tcs_amount

    processed = sorted(processed, key=lambda x: x.booking.booking_date, reverse=True)
    return render(request, 'processed_services.html', {
        'services': processed,
        'booking_tcs_map': booking_tcs_map,
    })
