from django.contrib import admin
from .models import (
    ServiceList, Carrier, Ticket, Passport, Visa, Insurance,
    Hotel, SightSeeing, Transfer
)

@admin.register(ServiceList)
class ServiceListAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return True
    def has_delete_permission(self, request, obj=None):
        return True

@admin.register(Carrier)
class CarrierAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        'ticket_booking_id', 'booking', 'date', 'carrier', 'supplier',
        'mode', 'purchase_amount', 'sales_amount', 'profit'
    )
    search_fields = ('ticket_booking_id', 'booking__booking_id', 'carrier__name', 'supplier__name')
    list_filter = ('carrier', 'supplier', 'mode')

    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(Passport)
class PassportAdmin(admin.ModelAdmin):
    list_display = (
        'passport_booking_id', 'booking', 'date', 'supplier',
        'mode', 'purchase_amount', 'sales_amount', 'profit'
    )
    search_fields = ('passport_booking_id', 'booking__booking_id', 'supplier__name')
    list_filter = ('supplier', 'mode')

    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(Visa)
class VisaAdmin(admin.ModelAdmin):
    list_display = (
        'visa_booking_id', 'booking', 'date', 'supplier',
        'mode', 'purchase_amount', 'sales_amount', 'profit'
    )
    search_fields = ('visa_booking_id', 'booking__booking_id', 'supplier__name')
    list_filter = ('supplier', 'mode')

    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(Insurance)
class InsuranceAdmin(admin.ModelAdmin):
    list_display = (
        'insurance_booking_id', 'booking', 'date', 'supplier',
        'mode', 'purchase_amount', 'sales_amount', 'profit'
    )
    search_fields = ('insurance_booking_id', 'booking__booking_id', 'supplier__name')
    list_filter = ('supplier', 'mode')

    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(Hotel)
class HotelAdmin(admin.ModelAdmin):
    list_display = (
        'hotel_booking_id', 'booking', 'date', 'supplier',
        'mode', 'purchase_amount', 'sales_amount', 'travel_type', 'profit'
    )
    search_fields = ('hotel_booking_id', 'booking__booking_id', 'supplier__name')
    list_filter = ('supplier', 'mode', 'travel_type')

    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(SightSeeing)
class SightSeeingAdmin(admin.ModelAdmin):
    list_display = (
        'sightseeing_booking_id', 'booking', 'date', 'supplier',
        'mode', 'purchase_amount', 'sales_amount', 'travel_type', 'profit'
    )
    search_fields = ('sightseeing_booking_id', 'booking__booking_id', 'supplier__name')
    list_filter = ('supplier', 'mode', 'travel_type')

    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(Transfer)
class TransferAdmin(admin.ModelAdmin):
    list_display = (
        'transfer_booking_id', 'booking', 'date', 'supplier',
        'mode', 'purchase_amount', 'sales_amount', 'travel_type', 'profit'
    )
    search_fields = ('transfer_booking_id', 'booking__booking_id', 'supplier__name')
    list_filter = ('supplier', 'mode', 'travel_type')

    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
