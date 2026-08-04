"""The home page sends each role to the report it works from.

Owners and admins land on the owner actuals report, accountants on their
to-do queue, everyone else on the staff actuals report. The old generic
dashboard is no longer routed.
"""
from django.test import Client as HttpClient, TestCase

from . import seed


class HomeRoutingTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.fixture = seed.build()

    def _get_home_as(self, user):
        http = HttpClient(raise_request_exception=False)
        http.force_login(user)
        return http.get("/")

    def test_owner_gets_the_owner_actuals_report(self):
        response = self._get_home_as(self.fixture.users["owner"])

        self.assertEqual(response.status_code, 200)
        self.assertIn("owner_reports_actual.html",
                      [t.name for t in response.templates if t.name])

    def test_staff_gets_the_staff_actuals_report(self):
        response = self._get_home_as(self.fixture.users["staff1"])

        self.assertEqual(response.status_code, 200)
        self.assertIn("staff_actual_profit.html",
                      [t.name for t in response.templates if t.name])

    def test_admin_gets_the_owner_actuals_report(self):
        response = self._get_home_as(self.fixture.users["admin1"])

        self.assertEqual(response.status_code, 200)
        self.assertIn("owner_reports_actual.html",
                      [t.name for t in response.templates if t.name])

    def test_accountant_is_sent_to_the_accounts_queue(self):
        response = self._get_home_as(self.fixture.users["acct"])

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/todo/", response.url)

    def test_retired_reports_are_no_longer_routed(self):
        """Retired paths must 404, not 500 -- and not quietly still work."""
        http = HttpClient(raise_request_exception=False)
        http.force_login(self.fixture.users["owner"])

        for path in (
            "/reports/owner-reports/",
            "/reports/owner-reports/filtered/",
            "/reports/owner-reports/bookings-report/",
            "/reports/owner-reports-legacy/",
            "/reports/api/filtered-legacy-report/",
            "/employee/filtered/",
            "/employee/bookings/",
            "/staff/legacy/",
            "/staff/legacy/summary/",
        ):
            with self.subTest(path=path):
                self.assertEqual(http.get(path).status_code, 404)

    def test_pages_that_extend_base_still_render(self):
        """base.html reverses the nav links; a stale one would 500 every page."""
        http = HttpClient(raise_request_exception=False)
        http.force_login(self.fixture.users["owner"])

        for path in ("/bookings/", "/reports/owner/actual/", "/staff-reports-actual/"):
            with self.subTest(path=path):
                self.assertEqual(http.get(path).status_code, 200)
