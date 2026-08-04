"""Regression tests for the legacy filter endpoints.

Both returned HTTP 500 on every call: they chained .values_list("year") onto
.dates("booking_date", "year"), which already yields date objects, so Django
raised FieldError("Cannot resolve keyword 'year' into field").

The golden master pinned that 500 as current behaviour. These tests pin the
fix, and -- unlike the golden master fixture, which has no legacy payments --
they create one so the year list is actually populated. An endpoint that
returns [] would pass even if the conversion were still wrong.
"""
import json
from datetime import date
from decimal import Decimal

from django.test import RequestFactory, TestCase

from bookings.models import Booking
from core.views_legacy import staff_legacy_filters_data
from payments.models import PaymentReceived
from reports.views_legacy import report_filters_data_legacy

from . import seed


class LegacyFilterEndpointTests(TestCase):
    """A legacy booking is one with an approved payment and no service."""

    @classmethod
    def setUpTestData(cls):
        cls.fixture = seed.build()
        owner = cls.fixture.users["owner"]

        # "Legacy-only" means the booking has a payment with service NULL and
        # none with a service attached, so it has to be a booking the fixture
        # left without payments. bookings[3] is one, dated 2025.
        legacy_bookings = [cls.fixture.bookings[3]]

        # A second booking in a different year, so the response contains more
        # than one entry and the list conversion is genuinely exercised.
        older = Booking.objects.create(
            created_by=owner,
            client=cls.fixture.clients[0],
            booking_date=date(2023, 6, 9),
            number_of_adults=1,
            status=cls.fixture.statuses["closed"],
        )
        legacy_bookings.append(older)

        for booking in legacy_bookings:
            PaymentReceived.objects.create(
                booking=booking,
                service=None,  # this is what marks the payment as legacy
                mode=cls.fixture.modes["Card"],
                amount=Decimal("1000"),
                received_on=booking.booking_date,
                received_by=owner,
                approved=True,
                approved_by=owner,
            )

        cls.expected_years = {2023, 2025}

    def setUp(self):
        pass  # views are called directly; no HTTP client needed

    def _call(self, view):
        """Call the view directly.

        The legacy routes are commented out, so these cannot be reached by URL
        any more. The views themselves are still in the codebase, and the fix
        should stay correct in case they are ever re-enabled -- so the test
        calls them directly instead of deleting the coverage.
        """
        request = RequestFactory().get("/")
        request.user = self.fixture.users["owner"]
        return json.loads(view(request).content)

    def test_reports_legacy_filters_returns_years(self):
        payload = self._call(report_filters_data_legacy)

        self.assertEqual(set(payload["years"]), self.expected_years)
        # Plain ints, not dates -- that conversion is the part that was broken.
        for year in payload["years"]:
            self.assertIsInstance(year, int)
        self.assertEqual(len(payload["months"]), 12)

    def test_core_staff_legacy_filters_returns_years(self):
        payload = self._call(staff_legacy_filters_data)

        for year in payload["years"]:
            self.assertIsInstance(year, int)
        self.assertEqual(len(payload["months"]), 12)
