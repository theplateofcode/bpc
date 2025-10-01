from django.urls import path
from .views import (
    employee_dashboard,
    manage_groups,
    employee_filtered_report,
    employee_bookings_report,
    employee_report_filters_data,
)

urlpatterns = [
    # Employee home dashboard
    path("", employee_dashboard, name="home"),

    # Groups (superusers/staff only)
    path("manage-groups/", manage_groups, name="manage_groups"),

    # Employee reports (AJAX endpoints)
    path("employee/filtered/", employee_filtered_report, name="employee_filtered_report"),
    path("employee/bookings/", employee_bookings_report, name="employee_bookings_report"),
    path("employee/filters/", employee_report_filters_data, name="employee_report_filters_data"),
]
