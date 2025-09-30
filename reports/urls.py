# reports/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Main report page
    path("owner-reports/", views.owner_reports, name="owner_reports"),

    # Data APIs (JSON)
    path("owner-reports/monthly/", views.monthly_profit_data, name="monthly_profit_data"),
    path("owner-reports/staff/", views.staff_profit_data, name="staff_profit_data"),
    # path("owner-reports/service/", views.service_wise_table, name="service_wise_table"),

    # Filters
    path("owner-reports/filter-data/", views.report_filters_data, name="report_filters_data"),
    path("owner-reports/filtered/", views.filtered_report, name="filtered_report"),

    # Client report
    path("owner-reports/bookings-report/", views.bookings_report, name="bookings_report"),

]
