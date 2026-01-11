# reports/urls.py
from django.urls import path
from . import views
from . import views_actual
from . import views_legacy

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

    # Actuals reports
    path("owner/actual/", views_actual.owner_actual_reports, name="owner_actual_reports"),
    path("owner/actual/data/", views_actual.filtered_actual_report, name="filtered_actual_report"),
    path("owner/actual/bookings/", views_actual.bookings_report, name="bookings_report"),

    # Legacy reports
    path("owner-reports-legacy/", views_legacy.owner_legacy_reports, name="owner_legacy_reports"),
    path("owner-reports-legacy/filters/", views_legacy.report_filters_data_legacy, name="report_filters_data_legacy"),
    path("owner-reports-legacy/summary/", views_legacy.filtered_legacy_report, name="filtered_legacy_report"),
    path("owner-reports-legacy/bookings/", views_legacy.bookings_report_legacy, name="bookings_report_legacy"),

]
