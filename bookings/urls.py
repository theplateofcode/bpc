from .views import bookings, create_booking, edit_booking, delete_booking, booking_pdf
from .views import status_list, status_create, status_update, status_delete
from django.urls import path

urlpatterns = [
    path('', bookings, name='bookings'),
    path('create/', create_booking, name='create_booking'),
    path('<int:pk>/edit/', edit_booking, name='edit_booking'),
    path('<int:pk>/delete/', delete_booking, name='delete_booking'),
    path('<int:booking_id>/pdf/', booking_pdf, name='booking_pdf'),
    path('status/', status_list, name='status_list'),
    path('status/new/', status_create, name='status_create'),
    path('status/<int:pk>/edit/', status_update, name='status_update'),
    path('status/<int:pk>/delete/', status_delete, name='status_delete'),
]   
