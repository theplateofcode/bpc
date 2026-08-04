# reports/urls.py
from django.urls import path
from . import views
from . import views_actual
from . import views_legacy  # noqa: F401  -- routes commented out below, see note

# ---------------------------------------------------------------------------
# Only the ACTUALS report is routed for owners.
#
# Two families of report were retired here. The view code is left in place --
# nothing is deleted -- but nothing routes to it, so it cannot be reached and
# cannot drift out of step. Restoring one means uncommenting its line and
# putting the link back in templates/base.html.
#
#   BEFORE-PAYMENTS reports (views.py)
#     owner_reports, monthly_profit_data, staff_profit_data, filtered_report,
#     bookings_report. These took sales from the service rows rather than from
#     payments received, and applied no GST or TCS at all, so their "profit" was
#     gross margin where every other screen shows net. Two different answers to
#     the same question was the reason to retire them.
#
#   LEGACY reports (views_legacy.py)
#     For bookings whose payments were recorded with no service attached. On the
#     production snapshot that is 168 bookings dated 2025-05-17 to 2025-12-30 and
#     none since -- the practice stopped in December. Those rows stay in the
#     database untouched; they are simply no longer reportable through the UI.
#
# report_filters_data STAYS ROUTED. It sits in views.py alongside the retired
# reports, but owner_reports_actual.html reverses it to fill its filter
# dropdowns. Commenting it out raises NoReverseMatch and takes that page down.
# ---------------------------------------------------------------------------

urlpatterns = [
    # -- Owner actuals (live) --------------------------------------------
    path("owner/actual/", views_actual.owner_actual_reports, name="owner_actual_reports"),
    path("owner/actual/data/", views_actual.filtered_actual_report, name="filtered_actual_report"),
    path("owner/actual/bookings/", views_actual.bookings_report, name="bookings_report"),

    # -- Filter dropdowns for the actuals page (live -- see note above) ---
    path("owner-reports/filter-data/", views.report_filters_data, name="report_filters_data"),

    # -- Retired: before-payments reports ---------------------------------
    # path("owner-reports/", views.owner_reports, name="owner_reports"),
    # path("owner-reports/monthly/", views.monthly_profit_data, name="monthly_profit_data"),
    # path("owner-reports/staff/", views.staff_profit_data, name="staff_profit_data"),
    # path("owner-reports/filtered/", views.filtered_report, name="filtered_report"),
    # path("owner-reports/bookings-report/", views.bookings_report, name="bookings_report_pre"),

    # -- Retired: legacy reports ------------------------------------------
    # path("owner-reports-legacy/", views_legacy.owner_legacy_reports, name="owner_legacy_reports"),
    # path("api/report-filters-legacy/", views_legacy.report_filters_data_legacy, name="report_filters_data_legacy"),
    # path("api/filtered-legacy-report/", views_legacy.filtered_legacy_report, name="filtered_legacy_report"),
    # path("api/bookings-report-legacy/", views_legacy.bookings_report_legacy, name="bookings_report_legacy"),
]
