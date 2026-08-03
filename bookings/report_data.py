"""Bulk row loader for the actuals reports.

The reports used to walk bookings, then services, asking the database a fresh
question at every step: purchase totals, tax rows, approved payments, the
service creator, whether a supplier appears. That came to 82 queries per
booking and grew linearly -- 32,803 of them at 400 bookings.

Every one of those questions is answerable from rows that could have been
fetched once. This class fetches them once (nine queries, plus one per extra
thousand bookings) and hands them back grouped the way the reports ask for them.

It deliberately does no arithmetic. The two report modules that use it compute
cash/non-cash splits and taxes slightly differently from each other -- core uses
`icontains("cash")` where reports uses `iexact`, among other things -- so the
sums stay where they are and only the fetching is shared. Anything else would
quietly change one of them.
"""
from collections import defaultdict

from payments.models import PaymentReceived
from services.models import (
    Hotel, Insurance, Passport, SightSeeing, Ticket, Transfer, Visa,
)

# Same mapping the report modules use, kept here so the loader knows which
# tables to read.
SERVICE_MODELS_BY_CODE = {
    "hotel": Hotel,
    "transfer": Transfer,
    "sightseeing": SightSeeing,
    "ticket": Ticket,
    "visa": Visa,
    "insurance": Insurance,
    "passport": Passport,
}

# Databases have a practical ceiling on how many values an IN () clause can
# take, and a very large one is slow even where it is allowed.
CHUNK_SIZE = 1000


def _chunked(items, size=CHUNK_SIZE):
    items = list(items)
    for start in range(0, len(items), size):
        yield items[start:start + size]


class ReportRows:
    """Every row the actuals reports need, grouped for lookup."""

    def __init__(self, booking_ids):
        self.booking_ids = list(booking_ids)

        # booking_id -> [BookingService], in a stable order
        self._assignments = defaultdict(list)
        # (booking_id, service_code) -> [service row]
        self._service_rows = defaultdict(list)
        # (booking_id, service_id) -> [approved PaymentReceived]
        self._approved_payments = defaultdict(list)
        # booking_id -> {service_id, ...} with at least one pending payment
        self._pending_service_ids = defaultdict(set)
        # booking_id -> True when an approved payment has no service attached
        self._legacy_approved = set()

        if self.booking_ids:
            self._load_assignments()
            self._load_service_rows()
            self._load_payments()

    # -- loading ---------------------------------------------------------

    def _load_assignments(self):
        from bookings.models import BookingService

        for chunk in _chunked(self.booking_ids):
            rows = (
                BookingService.objects
                .filter(booking_id__in=chunk)
                .select_related("service", "assigned_to")
                .order_by("id")
            )
            for row in rows:
                self._assignments[row.booking_id].append(row)

    def _load_service_rows(self):
        for code, model in SERVICE_MODELS_BY_CODE.items():
            for chunk in _chunked(self.booking_ids):
                rows = (
                    model.objects
                    .filter(booking_id__in=chunk)
                    .select_related("mode", "created_by")
                    # `.first()` on an unordered queryset orders by pk, so the
                    # report's "who entered this" lookup picks the lowest id.
                    # Ordering by id here keeps that answer the same.
                    .order_by("id")
                )
                for row in rows:
                    self._service_rows[(row.booking_id, code)].append(row)

    def _load_payments(self):
        for chunk in _chunked(self.booking_ids):
            rows = (
                PaymentReceived.objects
                .filter(booking_id__in=chunk)
                .select_related("mode")
                .order_by("id")
            )
            for row in rows:
                if row.approved:
                    if row.service_id is None:
                        self._legacy_approved.add(row.booking_id)
                    else:
                        self._approved_payments[(row.booking_id, row.service_id)].append(row)
                elif row.service_id is not None:
                    self._pending_service_ids[row.booking_id].add(row.service_id)

    # -- lookups ---------------------------------------------------------

    def assignments_for(self, booking_id):
        """BookingService rows for one booking."""
        return self._assignments.get(booking_id, [])

    def assigned_service_ids(self, booking_id):
        """Distinct service ids assigned to a booking, in first-seen order.

        Mirrors .values_list("service_id", flat=True).distinct().
        """
        seen = []
        for row in self.assignments_for(booking_id):
            if row.service_id not in seen:
                seen.append(row.service_id)
        return seen

    def service_rows(self, booking_id, service_code):
        """Rows of one service table for one booking, lowest id first."""
        return self._service_rows.get((booking_id, service_code), [])

    def first_service_row(self, booking_id, service_code):
        """Equivalent of model.objects.filter(booking_id=...).first()."""
        rows = self.service_rows(booking_id, service_code)
        return rows[0] if rows else None

    def approved_payments(self, booking_id, service_id):
        return self._approved_payments.get((booking_id, service_id), [])

    def has_approved_payment(self, booking_id, service_id):
        return bool(self._approved_payments.get((booking_id, service_id)))

    def has_pending_payment(self, booking_id, service_ids):
        """True when any of these services has an unapproved payment."""
        pending = self._pending_service_ids.get(booking_id)
        if not pending:
            return False
        return any(service_id in pending for service_id in service_ids)

    def has_legacy_approved_payment(self, booking_id):
        """Approved payment with no service attached -- the legacy-mixed marker."""
        return booking_id in self._legacy_approved

    def has_supplier(self, booking_id, service_code, supplier_id):
        """Equivalent of filter(booking_id=..., supplier_id=...).exists()."""
        if supplier_id in (None, ""):
            return True
        supplier_id = int(supplier_id)
        return any(
            row.supplier_id == supplier_id
            for row in self.service_rows(booking_id, service_code)
        )
