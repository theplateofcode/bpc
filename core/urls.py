from django.urls import path
from .views import (
    employee_dashboard,
    manage_groups,
    employee_filtered_report,
    employee_bookings_report,
    employee_report_filters_data,
)
from . import views_legacy
from . import views_actual

urlpatterns = [
    # Employee home dashboard
    path("", employee_dashboard, name="home"),
    

    # Groups (superusers/staff only)
    path("manage-groups/", manage_groups, name="manage_groups"),

    # Employee reports (AJAX endpoints)
    path("employee/filtered/", employee_filtered_report, name="employee_filtered_report"),
    path("employee/bookings/", employee_bookings_report, name="employee_bookings_report"),
    path("employee/filters/", employee_report_filters_data, name="employee_report_filters_data"),

    #actual report filters
    path("staff-reports-actual/", views_actual.staff_actual_reports, name="staff_actual_reports"),
    path("staff-reports-actual/filtered/", views_actual.staff_filtered_actual_report, name="staff_filtered_actual_report"),
    path("staff-reports-actual/bookings/", views_actual.staff_bookings_report, name="staff_bookings_report"),

     # Staff Legacy
    path("staff/legacy/", views_legacy.staff_legacy_reports, name="staff_legacy_reports"),
    path("staff/legacy/filters/", views_legacy.staff_legacy_filters_data, name="staff_legacy_filters_data"),
    path("staff/legacy/summary/", views_legacy.staff_legacy_summary, name="staff_legacy_summary"),
    path("staff/legacy/bookings/", views_legacy.staff_legacy_bookings, name="staff_legacy_bookings"),
]
