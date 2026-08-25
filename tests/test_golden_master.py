"""Golden master: pins the CURRENT behaviour of the financial logic and the
report endpoints, so a refactor can prove it changed nothing.

    # run the suite
    python manage.py test tests --settings=main.settings_test

    # regenerate the snapshot (ONLY when a change in output is intended)
    UPDATE_GOLDEN=1 python manage.py test tests --settings=main.settings_test

The snapshot lives in tests/golden_master.json and is committed. If a refactor
alters any number, any ordering, or any endpoint payload, the diff shows up there.
"""
import json
import os
import re
from decimal import Decimal
from pathlib import Path

from django.test import Client as HttpClient, TestCase
from django.urls import reverse

from bookings.models import Booking

from . import seed

SNAPSHOT_PATH = Path(__file__).parent / "golden_master.json"

# Report endpoints return floats. Summing the same values in a different order
# can shift the last binary digit without any behavioural change, so compare at
# a precision far beyond what money needs but far below float noise.
FLOAT_PLACES = 6


def canon(value):
    """Recursively normalise a payload into something JSON-diffable and stable."""
    if isinstance(value, dict):
        return {str(k): canon(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [canon(v) for v in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, Decimal):
        # normalize() before formatting so Decimal('7000') and Decimal('7000.00')
        # compare equal. They are the same number; only the trailing-zero scale
        # differs, and that differs by *backend* -- SQLite's SUM() drops the
        # scale where MySQL's SUM(DECIMAL(12,2)) keeps it. Comparing raw
        # representations would fail the suite on a difference the production
        # database does not even have. Any actual change in value still fails.
        return f"{value.normalize():f}"
    if isinstance(value, float):
        return round(value, FLOAT_PLACES)
    return value


# Query-string permutations exercised against the report endpoints. Each is a
# (label, params) pair; the label becomes the snapshot key.
REPORT_PARAM_SETS = [
    ("all", {}),
    ("year_2025", {"year": "2025"}),
    ("year_2024", {"year": "2024"}),
    ("month_january", {"year": "2025", "month": "January"}),
    ("month_bad", {"month": "NotAMonth"}),
    ("service_hotel", {"service": "Hotel"}),
    ("service_ticket", {"service": "Ticket"}),
]

# Sort/filter permutations for the bookings list. These are the paths that
# currently fall back to loading the entire table into Python.
BOOKING_LIST_CASES = [
    ("default", {}),
    ("sort_booking_id_asc", {"sort_col": "booking_id", "sort_dir": "asc"}),
    ("sort_booking_date_asc", {"sort_col": "booking_date", "sort_dir": "asc"}),
    ("sort_booking_date_desc", {"sort_col": "booking_date", "sort_dir": "desc"}),
    ("sort_status_asc", {"sort_col": "status", "sort_dir": "asc"}),
    ("sort_created_by_asc", {"sort_col": "created_by", "sort_dir": "asc"}),
    ("sort_client_name_asc", {"sort_col": "client_name", "sort_dir": "asc"}),
    ("sort_services_asc", {"sort_col": "services", "sort_dir": "asc"}),
    ("sort_total_p_cost_asc", {"sort_col": "total_p_cost", "sort_dir": "asc"}),
    ("sort_total_p_cost_desc", {"sort_col": "total_p_cost", "sort_dir": "desc"}),
    ("sort_total_s_cost_desc", {"sort_col": "total_s_cost", "sort_dir": "desc"}),
    ("sort_total_gst_desc", {"sort_col": "total_gst", "sort_dir": "desc"}),
    ("sort_net_profit_asc", {"sort_col": "net_profit", "sort_dir": "asc"}),
    ("sort_net_profit_desc", {"sort_col": "net_profit", "sort_dir": "desc"}),
    ("filter_net_profit_gt_0", {"f_net_profit_op": "gt", "f_net_profit_val": "0"}),
    ("filter_net_profit_lt_0", {"f_net_profit_op": "lt", "f_net_profit_val": "0"}),
    ("filter_p_cost_gte_1000", {"f_total_p_cost_op": "gte", "f_total_p_cost_val": "1000"}),
    ("filter_client_contains", {"f_client_name_op": "contains", "f_client_name_val": "First1"}),
    ("filter_client_equals_miss", {"f_client_name_op": "equals", "f_client_name_val": "nope"}),
    ("filter_booking_id_contains", {"f_booking_id_op": "contains", "f_booking_id_val": "B-00"}),
    ("filter_status_equals_closed", {"f_status_op": "equals", "f_status_val": "closed"}),
    ("filter_booking_date_gt", {"f_booking_date_op": "gt", "f_booking_date_val": "2025-01-01"}),
    ("filter_services_contains", {"f_services_op": "contains", "f_services_val": "Hotel"}),
    ("combo_filter_and_sort", {
        "f_status_op": "equals", "f_status_val": "closed",
        "sort_col": "net_profit", "sort_dir": "desc",
    }),
    # Mixed path: `services` can only be sorted in Python, but the money filter
    # alongside it still has to agree with the SQL-side answer.
    ("combo_services_sort_money_filter", {
        "sort_col": "services", "sort_dir": "asc",
        "f_net_profit_op": "gt", "f_net_profit_val": "0",
    }),
    ("combo_created_by_sort_client_filter", {
        "sort_col": "created_by", "sort_dir": "desc",
        "f_client_name_op": "contains", "f_client_name_val": "last",
    }),
    ("filter_net_profit_not_a_number", {"f_net_profit_op": "gt", "f_net_profit_val": "abc"}),
    ("sort_created_by_desc", {"sort_col": "created_by", "sort_dir": "desc"}),
    ("sort_client_name_desc", {"sort_col": "client_name", "sort_dir": "desc"}),
]

MONEY_PROPERTIES = [
    "purchase_total",
    "sales_total",
    "tcs_amount",
    "invoice_amount",
    "gross_profit",
    "sales_gst",
    "net_profit",
]

ROW_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
ROW_RE = re.compile(r'<tr data-booking-id="(\d+)">(.*?)</tr>', re.S)


class GoldenMasterTests(TestCase):
    """Snapshot the whole financial surface, then assert it never moves."""

    @classmethod
    def setUpTestData(cls):
        cls.fixture = seed.build()

    def setUp(self):
        # raise_request_exception=False so an endpoint that 500s gets recorded as
        # a 500 instead of aborting the run. Some already do -- see the notes in
        # tests/README.md. The snapshot must capture what the app does today,
        # bugs included, or it is not a faithful baseline.
        self.http = HttpClient(raise_request_exception=False)
        self.http.force_login(self.fixture.users["owner"])

    # ------------------------------------------------------------------
    # snapshot builders
    # ------------------------------------------------------------------

    def _snapshot_model_properties(self):
        """The heart of it: every computed money value, per booking."""
        out = {}
        for booking in Booking.objects.order_by("id"):
            entry = {p: canon(getattr(booking, p)) for p in MONEY_PROPERTIES}
            entry["all_services_finished"] = booking.all_services_finished()
            entry["service_statuses"] = canon(booking.get_service_statuses())
            out[booking.booking_id] = entry
        return out

    def _snapshot_booking_list(self):
        """Ordering and rendered cell values for every sort/filter path."""
        url = reverse("booking_rows")
        out = {}
        for label, params in BOOKING_LIST_CASES:
            resp = self.http.get(url, params)
            self.assertEqual(resp.status_code, 200, f"{label} returned {resp.status_code}")
            html = resp.content.decode()
            rows = []
            for booking_pk, body in ROW_RE.findall(html):
                cells = [
                    re.sub(r"<[^>]+>", " ", c).strip()
                    for c in ROW_CELL_RE.findall(body)
                ]
                cells = [re.sub(r"\s+", " ", c) for c in cells]
                # cells[1] is booking_id, [6:10] are the four money columns
                rows.append({
                    "booking_id": cells[1] if len(cells) > 1 else "",
                    "money": cells[6:10],
                })
            out[label] = rows
        return out

    def _snapshot_endpoints(self):
        """Every read-only JSON report endpoint, across filter permutations."""
        # Only the routed surface. The before-payments and legacy reports were
        # retired -- their views still exist but nothing routes to them, so
        # requesting these paths would just record a wall of 404s and prove
        # nothing. See reports/urls.py for what was retired and why.
        endpoints = [
            ("actual.filtered", "/reports/owner/actual/data/"),
            ("actual.bookings", "/reports/owner/actual/bookings/"),
            ("reports.filters", "/reports/owner-reports/filter-data/"),
            ("core.staff_actual_filtered", "/staff-reports-actual/filtered/"),
            ("core.staff_actual_bookings", "/staff-reports-actual/bookings/"),
            ("core.employee_filters", "/employee/filters/"),
            ("gst.data", "/etc/gst/data/"),
            ("tcs.data", "/etc/tcs/data/"),
        ]
        out = {}
        for name, path in endpoints:
            for label, params in REPORT_PARAM_SETS:
                key = f"{name}[{label}]"
                resp = self.http.get(path, params)
                record = {"status": resp.status_code}
                if resp.status_code == 200 and "json" in resp.get("Content-Type", ""):
                    record["body"] = canon(json.loads(resp.content))
                out[key] = record

        # The staff reports only ever show services the logged-in user is
        # assigned to. Requested as the owner -- who has no assignments -- they
        # come back empty, so every entry above proves nothing about them.
        # Request them again as staff who DO have assignments.
        staff_endpoints = [
            ("staff.filtered", "/staff-reports-actual/filtered/"),
            ("staff.bookings", "/staff-reports-actual/bookings/"),
        ]
        for username in ("staff1", "staff2"):
            staff_client = HttpClient(raise_request_exception=False)
            staff_client.force_login(self.fixture.users[username])
            for name, path in staff_endpoints:
                for label, params in REPORT_PARAM_SETS:
                    key = f"{name}@{username}[{label}]"
                    resp = staff_client.get(path, params)
                    record = {"status": resp.status_code}
                    if resp.status_code == 200 and "json" in resp.get("Content-Type", ""):
                        record["body"] = canon(json.loads(resp.content))
                    out[key] = record

        return out

    def build_snapshot(self):
        return {
            "model_properties": self._snapshot_model_properties(),
            "booking_list": self._snapshot_booking_list(),
            "endpoints": self._snapshot_endpoints(),
        }

    # ------------------------------------------------------------------
    # the test
    # ------------------------------------------------------------------

    def test_behaviour_matches_snapshot(self):
        current = self.build_snapshot()

        if os.environ.get("UPDATE_GOLDEN") or not SNAPSHOT_PATH.exists():
            SNAPSHOT_PATH.write_text(
                json.dumps(current, indent=2, sort_keys=True), encoding="utf-8"
            )
            self.skipTest(f"Snapshot written to {SNAPSHOT_PATH.name} -- rerun to compare.")

        expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))

        # Compare section by section so a failure names the area that moved.
        for section in ("model_properties", "booking_list", "endpoints"):
            with self.subTest(section=section):
                self.assertEqual(
                    expected.get(section), current.get(section),
                    f"{section} changed vs the golden master",
                )
