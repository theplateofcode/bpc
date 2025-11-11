from django.urls import path
from . import views


urlpatterns = [
    # --- Payment Installment & Details URLs ---
    path("home/", views.payments_home, name="payments_home"),
    path("details/<int:booking_id>/", views.payment_details_modal, name="details"),
    path("add/<int:booking_id>/", views.payment_add_installment, name="add"),
    path("mark-full/<int:booking_id>/", views.payment_mark_full, name="mark_full"),

    # --- Payment Approval URLs ---
    path("approvals/", views.payment_approvals, name="approvals"),
    path("approve/<int:pk>/", views.payment_approve, name="approve"),
    path("reject/<int:pk>/", views.payment_reject, name="reject"),

    # --- Modes of Payment (CRUD) URLs ---
    path('', views.modes_of_payment, name='modes_of_payment'),

    path('new/', views.create_mode, name='create_mode'),

    path('<int:pk>/edit/', views.update_mode, name='update_mode'),

    path('<int:pk>/delete/', views.delete_mode, name='delete_mode'), 

    path("accountant-dashboard/", views.accountant_dashboard, name="accountant_dashboard"),

]