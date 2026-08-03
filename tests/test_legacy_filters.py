"""Regression tests for the legacy filter endpoints.

Both returned HTTP 500 on every call: they chained .values_list("year") onto
.dates("booking_date", "year"), which already yields date objects, so Django
raised FieldError("Cannot resolve keyword 'year' into field").

The golden master pinned that 500 as current behaviour. These tests pin the
fix, and -- unlike the golden master fixture, which has no legacy payments --
they create one so the year list is actually populated. An endpoint that
returns [] would pass even if the conversion were still wrong.
"""
from datetime import date
from decimal import Decimal

from django.test import Client as HttpClient, TestCase

from bookings.models import Booking
from payments.models import PaymentReceived

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
        self.http = HttpClient()
        self.http.force_login(self.fixture.users["owner"])

    def test_reports_legacy_filters_returns_years(self):
        response = self.http.get("/reports/api/report-filters-legacy/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(set(payload["years"]), self.expected_years)
        # Plain ints, not dates -- that conversion is the part that was broken.
        for year in payload["years"]:
            self.assertIsInstance(year, int)
        self.assertEqual(len(payload["months"]), 12)

    def test_core_staff_legacy_filters_returns_years(self):
        response = self.http.get("/staff/legacy/filters/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        for year in payload["years"]:
            self.assertIsInstance(year, int)
        self.assertEqual(len(payload["months"]), 12)
