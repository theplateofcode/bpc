from django.urls import path
from . import views
from .views import (
    carrier_list, carrier_create, carrier_update, carrier_delete
)

urlpatterns = [
    # Carrier URLs
    path('carriers/', carrier_list, name='carrier_list'),
    path('carriers/new/', carrier_create, name='carrier_create'),
    path('carriers/<int:pk>/edit/', carrier_update, name='carrier_update'),
    path('carriers/<int:pk>/delete/', carrier_delete, name='carrier_delete'),
    
    # Service Finish URLs (New)
    path('<str:service_type>/<int:pk>/finish/', views.mark_service_finished, name='mark_service_finished'),
    
    # Ticket URLs
    path('tickets/', views.tickets, name='tickets'),
    path('ticket-entries/<int:booking_id>/', views.ticket_entries, name='ticket_entries'),
    path('tickets/create/<int:booking_id>/', views.create_ticket, name='create_ticket'),
    path('tickets/edit/<int:ticket_id>/', views.edit_ticket, name='edit_ticket'),
    path('tickets/delete/<int:ticket_id>/', views.delete_ticket, name='delete_ticket'),
    
    # Passport URLs
    path('passports/', views.passports, name='passports'),
    path('passport-entries/<int:booking_id>/', views.passport_entries, name='passport_entries'),
    path('passports/create/<int:booking_id>/', views.create_passport, name='create_passport'),
    path('passports/edit/<int:passport_id>/', views.edit_passport, name='edit_passport'),
    path('passports/delete/<int:passport_id>/', views.delete_passport, name='delete_passport'),
    
    # Visa URLs
    path('visas/', views.visas, name='visas'),
    path('visa-entries/<int:booking_id>/', views.visa_entries, name='visa_entries'),
    path('visas/create/<int:booking_id>/', views.create_visa, name='create_visa'),
    path('visas/edit/<int:visa_id>/', views.edit_visa, name='edit_visa'),
    path('visas/delete/<int:visa_id>/', views.delete_visa, name='delete_visa'),
    
    # Insurance URLs
    path('insurances/', views.insurances, name='insurances'),
    path('insurance-entries/<int:booking_id>/', views.insurance_entries, name='insurance_entries'),
    path('insurances/create/<int:booking_id>/', views.create_insurance, name='create_insurance'),
    path('insurances/edit/<int:insurance_id>/', views.edit_insurance, name='edit_insurance'),
    path('insurances/delete/<int:insurance_id>/', views.delete_insurance, name='delete_insurance'),
    
    # Hotel URLs
    path('hotels/', views.hotels, name='hotels'),
    path('hotel-entries/<int:booking_id>/', views.hotel_entries, name='hotel_entries'),
    path('hotels/create/<int:booking_id>/', views.create_hotel, name='create_hotel'),
    path('hotels/edit/<int:hotel_id>/', views.edit_hotel, name='edit_hotel'),
    path('hotels/delete/<int:hotel_id>/', views.delete_hotel, name='delete_hotel'),
    
    # Sightseeing URLs
    path('sightseeings/', views.sightseeings, name='sightseeings'),
    path('sightseeing-entries/<int:booking_id>/', views.sightseeing_entries, name='sightseeing_entries'),
    path('sightseeings/create/<int:booking_id>/', views.create_sightseeing, name='create_sightseeing'),
    path('sightseeings/edit/<int:sightseeing_id>/', views.edit_sightseeing, name='edit_sightseeing'),
    path('sightseeings/delete/<int:sightseeing_id>/', views.delete_sightseeing, name='delete_sightseeing'),
    
    # Transfer URLs
    path('transfers/', views.transfers, name='transfers'),
    path('transfer-entries/<int:booking_id>/', views.transfer_entries, name='transfer_entries'),
    path('transfers/create/<int:booking_id>/', views.create_transfer, name='create_transfer'),
    path('transfers/edit/<int:transfer_id>/', views.edit_transfer, name='edit_transfer'),
    path('transfers/delete/<int:transfer_id>/', views.delete_transfer, name='delete_transfer'),
    
    # Autocomplete URLs
    path('carriers/autocomplete/', views.carrier_autocomplete, name='carrier_autocomplete'),
    path('carriers/create-ajax/', views.create_carrier_ajax, name='create_carrier_ajax'),
    path('suppliers/autocomplete/', views.supplier_autocomplete, name='supplier_autocomplete'),
    path('suppliers/create-ajax/', views.create_supplier_ajax, name='create_supplier_ajax'),
    path('modes/autocomplete/', views.mode_autocomplete, name='mode_autocomplete'),
    path('modes/create-ajax/', views.create_mode_ajax, name='create_mode_ajax'),
]
