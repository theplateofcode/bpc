"""Does the rewritten money code still agree with the ORM query it replaced?

purchase_total and sales_total used to run
`.exclude(mode__name='Cash').aggregate(Sum(...))` per service table. They now
sum prefetched rows in Python, testing `row.mode.name == 'Cash'`.

Those two are only equivalent if the database compares strings the way Python
does -- and MySQL's default collation (utf8mb4_0900_ai_ci) does not. It is
case-insensitive, so `exclude(mode__name='Cash')` there also excludes a mode
named 'CASH', while `== 'Cash'` in Python does not.

This test runs the original query chain alongside the property and asserts they
still agree. It is worth running under
--settings=main.settings_test_mysql, because on SQLite both are
case-sensitive and it cannot fail.
"""
from datetime import date
from decimal import Decimal
from unittest import skipUnless

from django.db import connection
from django.db.models import Sum
from django.test import TestCase

from bookings.models import Booking, Status
from clients.models import Client
from payments.models import Mode
from services.models import ServiceList, Visa
from suppliers.models import Supplier
from users.models import User

CASH_EXCLUDING_RELATIONS = (
    "visas", "passports", "insurances", "hotels", "sightseeings", "transfers",
)


def orm_purchase_total(booking):
    """The aggregate chain purchase_total ran before it was rewritten."""
    zero = Decimal("0")
    total = booking.tickets.aggregate(t=Sum("purchase_amount"))["t"] or zero
    for relation in CASH_EXCLUDING_RELATIONS:
        total += (
            getattr(booking, relation)
            .exclude(mode__name="Cash")
            .aggregate(t=Sum("purchase_amount"))["t"]
            or zero
        )
    return total


def orm_sales_total(booking):
    zero = Decimal("0")
    total = booking.tickets.aggregate(t=Sum("sales_amount"))["t"] or zero
    for relation in CASH_EXCLUDING_RELATIONS:
        total += (
            getattr(booking, relation)
            .exclude(mode__name="Cash")
            .aggregate(t=Sum("sales_amount"))["t"]
            or zero
        )
    return total


class CashRuleEquivalenceTests(TestCase):
    """One visa row, one payment mode, spelled various ways."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(username="u", password="x")
        cls.status = Status.objects.create(name="open")
        cls.service = ServiceList.objects.create(code="visa", name="Visa")
        cls.supplier = Supplier.objects.create(name="S", category=cls.service)
        cls.client_row = Client.objects.create(
            first_name="A", last_name="B", contact_number="900000001"
        )

    def _booking_with_visa(self, mode_name):
        mode = Mode.objects.create(name=mode_name)
        booking = Booking.objects.create(
            created_by=self.user, client=self.client_row,
            booking_date=date(2025, 1, 1), number_of_adults=1, status=self.status,
        )
        Visa.objects.create(
            booking=booking, date="2025-01-01T00:00:00Z", supplier=self.supplier,
            mode=mode, purchase_amount=Decimal("100.00"),
            sales_amount=Decimal("150.00"), created_by=self.user,
        )
        # Re-fetch so the property reads rows the same way a view would.
        return Booking.objects.with_service_rows().get(pk=booking.pk)

    def assert_agrees(self, mode_name):
        booking = self._booking_with_visa(mode_name)
        self.assertEqual(
            orm_purchase_total(booking), booking.purchase_total,
            f"purchase_total disagrees with the query it replaced "
            f"for a mode named {mode_name!r}",
        )
        self.assertEqual(
            orm_sales_total(booking), booking.sales_total,
            f"sales_total disagrees with the query it replaced "
            f"for a mode named {mode_name!r}",
        )

    def test_canonical_casing(self):
        # Agrees on every backend -- the spelling matches exactly.
        self.assert_agrees("Cash")

    @skipUnless(connection.vendor == "mysql",
                "the code follows MySQL's case-insensitive collation, which "
                "SQLite does not share; run with --settings=main.settings_test_mysql")
    def test_upper_casing(self):
        self.assert_agrees("CASH")

    @skipUnless(connection.vendor == "mysql",
                "the code follows MySQL's case-insensitive collation, which "
                "SQLite does not share; run with --settings=main.settings_test_mysql")
    def test_lower_casing(self):
        self.assert_agrees("cash")

    def test_non_cash_mode_is_unaffected(self):
        booking = self._booking_with_visa("Card")
        self.assertEqual(booking.purchase_total, Decimal("100.00"))
        self.assertEqual(orm_purchase_total(booking), booking.purchase_total)
