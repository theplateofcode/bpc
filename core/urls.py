from django.urls import path
from .views import (
    home,
    manage_groups,
    employee_filtered_report,  # noqa: F401  -- route commented out, see note
    employee_bookings_report,  # noqa: F401  -- route commented out, see note
    employee_report_filters_data,
)
from . import views_legacy  # noqa: F401  -- routes commented out, see note
from . import views_actual

# ---------------------------------------------------------------------------
# Only the ACTUALS report is routed for staff. Same reasoning as reports/urls.py:
# the retired views stay in the file, nothing points at them.
#
# employee_report_filters_data STAYS ROUTED -- staff_actual_profit.html reverses
# it for the filter dropdowns, so removing it breaks the staff report page.
# ---------------------------------------------------------------------------

urlpatterns = [
    # Home. Sends each role to the report it actually works from.
    path("", home, name="home"),

    # Groups (superusers/staff only)
    path("manage-groups/", manage_groups, name="manage_groups"),

    # -- Staff actuals (live) --------------------------------------------
    path("staff-reports-actual/", views_actual.staff_actual_reports, name="staff_actual_reports"),
    path("staff-reports-actual/filtered/", views_actual.staff_filtered_actual_report, name="staff_filtered_actual_report"),
    path("staff-reports-actual/bookings/", views_actual.staff_bookings_report, name="staff_bookings_report"),

    # -- Filter dropdowns for the staff actuals page (live, see note) -----
    path("employee/filters/", employee_report_filters_data, name="employee_report_filters_data"),

    # -- Retired: before-payments employee reports ------------------------
    # path("employee/filtered/", employee_filtered_report, name="employee_filtered_report"),
    # path("employee/bookings/", employee_bookings_report, name="employee_bookings_report"),

    # -- Retired: staff legacy reports ------------------------------------
    # path("staff/legacy/", views_legacy.staff_legacy_reports, name="staff_legacy_reports"),
    # path("staff/legacy/filters/", views_legacy.staff_legacy_filters_data, name="staff_legacy_filters_data"),
    # path("staff/legacy/summary/", views_legacy.staff_legacy_summary, name="staff_legacy_summary"),
    # path("staff/legacy/bookings/", views_legacy.staff_legacy_bookings, name="staff_legacy_bookings"),
]
