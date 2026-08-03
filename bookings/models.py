from decimal import Decimal
from django.db import models
from django.db.models import (
    Case, CharField, DecimalField, ExpressionWrapper, F, OuterRef, Prefetch, Q,
    Subquery, Sum, Value, When,
)
from django.db.models.functions import Cast, Coalesce, Concat, Least, Lower, Trim
from django.conf import settings

# bookings/models.py


# ---------------------------------------------------------------------------
# Python-side equivalents of the aggregate/filter calls the money properties
# used to make.
#
# Each property below used to run its own .aggregate(Sum(...)) per service
# table, which meant one query per service per property -- 76 queries to render
# a single row of the bookings table. These helpers do the identical arithmetic
# over rows that are already in memory, so a page that prefetches its service
# rows pays nothing extra per booking.
#
# They are written to be correct with or without prefetching: `self.tickets.all()`
# returns the prefetch cache when one exists and issues a query when it does not,
# so nothing breaks if a caller forgets to prefetch -- it just gets slower.
# ---------------------------------------------------------------------------

def _sum_amount(rows, field, keep=None):
    """Equivalent of .aggregate(Sum(field))['..'] or Decimal('0').

    Matches the ORM on both edges that matter here: an empty set totals to
    Decimal('0') rather than None, and NULL amounts are skipped rather than
    raising.
    """
    total = Decimal('0')
    for row in rows:
        if keep is not None and not keep(row):
            continue
        value = getattr(row, field)
        if value is not None:
            total += value
    return total


def _not_cash_exact(row):
    """Mirrors .exclude(mode__name='Cash') -- note the exact, cased match."""
    mode = row.mode
    return not (mode is not None and mode.name == 'Cash')


def _not_cash_iexact(row):
    """Mirrors .exclude(mode__name__iexact='cash')."""
    mode = row.mode
    return not (mode is not None and (mode.name or '').lower() == 'cash')


def _is_international(row):
    """Mirrors .filter(travel_type__iexact='international')."""
    travel_type = row.travel_type
    return travel_type is not None and travel_type.lower() == 'international'


# The seven service relations every money property walks, with the related name
# each one hangs off Booking by.
SERVICE_RELATIONS = (
    'tickets', 'visas', 'passports', 'insurances',
    'hotels', 'sightseeings', 'transfers',
)


# Output type for the SQL-side money expressions below. Wide enough that the
# intermediate products (a 2dp amount times a 2dp rate gives 4dp) never
# overflow before the comparison happens.
_MONEY = DecimalField(max_digits=20, decimal_places=4)
_ZERO = Value(Decimal('0'), output_field=_MONEY)


def _relation_sum(model, field, exclude=None, keep=None):
    """SUM(field) over one service table for the booking being annotated.

    A correlated subquery rather than a JOIN on purpose: Booking has seven
    multi-valued service relations, and joining more than one of them in a
    single aggregate query multiplies the rows, silently inflating every total.
    Subqueries each stand alone, so the arithmetic stays correct.
    """
    rows = model.objects.filter(booking=OuterRef('pk'))
    if exclude is not None:
        rows = rows.exclude(exclude)
    if keep is not None:
        rows = rows.filter(keep)
    totals = rows.values('booking').annotate(total=Sum(field)).values('total')
    return Coalesce(Subquery(totals, output_field=_MONEY), _ZERO, output_field=_MONEY)


def _money(expression):
    return ExpressionWrapper(expression, output_field=_MONEY)


class BookingQuerySet(models.QuerySet):
    """Queryset helpers that make the money properties cheap to render."""

    def with_service_rows(self, *also_select_related):
        """Prefetch everything the money properties touch.

        Each service row's `mode` is select_related in the same pass, because
        the cash/non-cash tests read `row.mode.name` -- without it, dodging the
        aggregate queries would just trade them for one query per row.

        Pass extra relation names to join them in the same pass, e.g.
        with_service_rows('supplier') for a view that also renders suppliers.
        """
        from services.models import (
            Hotel, Insurance, Passport, SightSeeing, Ticket, Transfer, Visa,
        )

        models_by_relation = {
            'tickets': Ticket,
            'visas': Visa,
            'passports': Passport,
            'insurances': Insurance,
            'hotels': Hotel,
            'sightseeings': SightSeeing,
            'transfers': Transfer,
        }
        related = ('mode',) + tuple(also_select_related)
        return self.prefetch_related(*(
            Prefetch(relation, queryset=model.objects.select_related(*related))
            for relation, model in models_by_relation.items()
        ))

    def with_money_totals(self):
        """Annotate the money figures so the database can sort and filter on them.

        These mirror the properties of the same name. They exist so a request
        that sorts or filters by Net Profit does not have to load every booking
        into Python to find out which twenty belong on the page.

        Displayed values still come from the properties, which do exact Python
        Decimal arithmetic. These annotations decide *which rows and in what
        order*; the properties decide *what the user sees*. Keeping the split
        means the figures on screen are bit-for-bit what they were before.

        Annotation names are prefixed `db_` because Django assigns annotations
        onto the instance, and a name matching a property would collide with it.
        """
        from services.models import (
            Hotel, Insurance, Passport, SightSeeing, Ticket, Transfer, Visa,
        )

        not_cash = Q(mode__name='Cash')                       # matches the properties
        not_cash_i = Q(mode__name__iexact='cash')             # tcs uses the looser test
        international = Q(travel_type__iexact='international')

        def totals(field):
            return _money(
                _relation_sum(Ticket, field) +
                _relation_sum(Visa, field, exclude=not_cash) +
                _relation_sum(Passport, field, exclude=not_cash) +
                _relation_sum(Insurance, field, exclude=not_cash) +
                _relation_sum(Hotel, field, exclude=not_cash) +
                _relation_sum(SightSeeing, field, exclude=not_cash) +
                _relation_sum(Transfer, field, exclude=not_cash)
            )

        tcs_base = (
            _relation_sum(Hotel, 'sales_amount', exclude=not_cash_i, keep=international) +
            _relation_sum(Transfer, 'sales_amount', exclude=not_cash_i, keep=international) +
            _relation_sum(SightSeeing, 'sales_amount', exclude=not_cash_i, keep=international)
        )

        qs = self.annotate(
            db_purchase_total=totals('purchase_amount'),
            db_sales_total=totals('sales_amount'),
            db_tcs_amount=_money(tcs_base * Value(Decimal('0.02'), output_field=_MONEY)),
        )
        qs = qs.annotate(
            db_gross_profit=_money(F('db_sales_total') - F('db_purchase_total')),
            db_invoice_amount=_money(F('db_sales_total') + F('db_tcs_amount')),
        )
        # sales_gst is min(5% of invoice, 18% of gross profit) -- including when
        # gross profit is negative, which makes the GST negative too. Least()
        # reproduces that rather than clamping it.
        qs = qs.annotate(
            db_sales_gst=_money(Least(
                _money(F('db_invoice_amount') * Value(Decimal('0.05'), output_field=_MONEY)),
                _money(F('db_gross_profit') * Value(Decimal('0.18'), output_field=_MONEY)),
            )),
        )
        return qs.annotate(
            db_net_profit=_money(F('db_gross_profit') - F('db_sales_gst')),
        )

    def with_sort_text(self):
        """Annotate the text columns the list can sort and filter on.

        Each one reproduces the string the Python path built, lower-cased to
        match `_normalize_text`. Doing the lower-casing explicitly rather than
        leaning on collation keeps the ordering identical on MySQL and SQLite.
        """
        # `_booking_created_by_text`: full name, falling back to username,
        # falling back to empty when the booking has no creator.
        full_name = Trim(Concat(
            Coalesce(F('created_by__first_name'), Value('')),
            Value(' '),
            Coalesce(F('created_by__last_name'), Value('')),
            output_field=CharField(),
        ))
        qs = self.annotate(_full_name=full_name)
        qs = qs.annotate(
            created_by_text=Case(
                When(created_by__isnull=True, then=Value('')),
                When(_full_name='', then=F('created_by__username')),
                default=F('_full_name'),
                output_field=CharField(),
            ),
        )

        # `_booking_client_name_text` is str(Client), i.e. "C-0007 - First Last".
        # The id is zero-padded to four digits and left alone beyond that, which
        # is what f"{id:04d}" does -- LPAD would truncate a five-digit id.
        client_pk = Cast(F('client_id'), output_field=CharField())
        padded_id = Case(
            When(client_id__lt=10, then=Concat(Value('000'), client_pk)),
            When(client_id__lt=100, then=Concat(Value('00'), client_pk)),
            When(client_id__lt=1000, then=Concat(Value('0'), client_pk)),
            default=client_pk,
            output_field=CharField(),
        )
        qs = qs.annotate(
            client_name_text=Concat(
                Value('C-'), padded_id, Value(' - '),
                Coalesce(F('client__first_name'), Value('')),
                Value(' '),
                Coalesce(F('client__last_name'), Value('')),
                output_field=CharField(),
            ),
        )

        return qs.annotate(
            created_by_sort=Lower('created_by_text'),
            client_name_sort=Lower('client_name_text'),
            status_sort=Lower(Coalesce(F('status__name'), Value(''))),
            booking_id_sort=Lower(Coalesce(F('booking_id'), Value(''))),
        )


class Status(models.Model):
    name = models.CharField(max_length=50, unique=True)

    class Meta:
        verbose_name = "Status"
        verbose_name_plural = "Statuses"
        ordering = ['name']

    def __str__(self):
        return self.name


class Mode(models.Model):
    name = models.CharField(max_length=50, unique=True)

    class Meta:
        verbose_name = "Payment Mode"
        verbose_name_plural = "Payment Modes"
        ordering = ['name']

    def __str__(self):
        return self.name


class Booking(models.Model):
    SERVICE_FLAG_MAP = {
        "ticket": "tickets_finished",
        "visa": "visas_finished",
        "hotel": "hotels_finished",
        "insurance": "insurances_finished",
        "transfer": "transfers_finished",
        "sightseeing": "sightseeings_finished",
        "passport": "passports_finished",
    }

    def all_services_finished(self):
        for service in self.services.all():
            finished_flag = self.SERVICE_FLAG_MAP.get(service.code.lower())
            if finished_flag and not getattr(self, finished_flag, False):
                return False
        return True

    objects = BookingQuerySet.as_manager()

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='bookings',
        null=True
    )
    booking_id = models.CharField(max_length=10, unique=True, blank=True)
    client = models.ForeignKey('clients.Client', on_delete=models.RESTRICT)
    booking_date = models.DateField()
    number_of_adults = models.IntegerField()
    number_of_children = models.IntegerField(default=0)
    tour_start_date = models.DateField(blank=True, null=True)
    tour_end_date = models.DateField(blank=True, null=True)
    services = models.ManyToManyField(
        'services.ServiceList',
        through='BookingService',
        related_name='bookings'
    )
    status = models.ForeignKey(
        Status,
        on_delete=models.PROTECT,
        default=2
    )
    accounts_done = models.BooleanField(
        default=False, verbose_name="Accounts Processed")

    # Service completion flags
    # keep the choice field instead of boolean

    tickets_finished = models.BooleanField(default=False)
    visas_finished = models.BooleanField(default=False)
    hotels_finished = models.BooleanField(default=False)
    insurances_finished = models.BooleanField(default=False)
    transfers_finished = models.BooleanField(default=False)
    sightseeings_finished = models.BooleanField(default=False)
    passports_finished = models.BooleanField(default=False)

    def get_service_statuses(self):
    # Map ServiceList code to booking flag and display name
        code_to_flag = {
            "ticket":      ("tickets_finished", "Tickets"),
            "visa":        ("visas_finished", "Visas"),
            "hotel":       ("hotels_finished", "Hotels"),
            "insurance":   ("insurances_finished", "Insurances"),
            "transfer":    ("transfers_finished", "Transfers"),
            "sightseeing": ("sightseeings_finished", "Sightseeings"),
            "passport":    ("passports_finished", "Passports"),
        }
        statuses = []
        for service in self.services.all():
            code = service.code.lower()
            flag, display = code_to_flag.get(code, (None, service.name))
            if flag:
                finished = getattr(self, flag, False)
                statuses.append((display, finished))
        return statuses

    def save(self, *args, **kwargs):
        if not self.booking_id:
            last = Booking.objects.order_by('id').last()
            last_num = last.id if last else 0
            self.booking_id = f"B-{last_num + 1:04d}"
        super().save(*args, **kwargs)
    
    def delete(self, *args, **kwargs):
        # 1. Delete all service entries
        self.tickets.all().delete()
        self.visas.all().delete()
        self.hotels.all().delete()
        self.insurances.all().delete()
        self.transfers.all().delete()
        self.sightseeings.all().delete()
        self.passports.all().delete()
        
        # 2. Clear many-to-many relationships
        self.services.clear()
        
        # 3. Delete BookingService through model instances
        self.bookingservice_set.all().delete()
        
        # 4. Delete the booking
        super().delete(*args, **kwargs)

    def __str__(self):
        return self.booking_id

    def _service_rows(self, relation):
        """Rows of one service relation, with `mode` already loaded.

        When the caller went through with_service_rows() this returns the
        prefetch cache and costs nothing. Otherwise it falls back to a single
        query per relation with `mode` joined -- the join matters, because the
        cash tests read `row.mode.name`, and without it an un-prefetched caller
        would pay one extra query per service row.
        """
        manager = getattr(self, relation)
        if relation in getattr(self, '_prefetched_objects_cache', {}):
            return manager.all()
        return manager.select_related('mode')

    def _amount_total(self, field):
        """Shared shape of purchase_total and sales_total.

        The two differed only in which column they summed, so the inclusion
        rules now live in one place: tickets always count, everything else
        counts only when it is not cash.
        """
        total = Decimal('0')
        # Tickets (always included)
        total += _sum_amount(self._service_rows('tickets'), field)

        # Visa/Passport/Insurance (exclude cash)
        total += _sum_amount(self._service_rows('visas'), field, _not_cash_exact)
        total += _sum_amount(self._service_rows('passports'), field, _not_cash_exact)
        total += _sum_amount(self._service_rows('insurances'), field, _not_cash_exact)

        # Package services (exclude cash)
        total += self._package_total(field)
        return total

    def _package_total(self, field):
        return (
            _sum_amount(self._service_rows('hotels'), field, _not_cash_exact) +
            _sum_amount(self._service_rows('sightseeings'), field, _not_cash_exact) +
            _sum_amount(self._service_rows('transfers'), field, _not_cash_exact)
        )

    @property
    def purchase_total(self):
        return self._amount_total('purchase_amount')

    @property
    def _package_purchase_total(self):
        return self._package_total('purchase_amount')

    @property
    def sales_total(self):
        return self._amount_total('sales_amount')

    @property
    def _package_sales_total(self):
        return self._package_total('sales_amount')

    # bookings/models.py
    @property
    def invoice_amount(self):
        return self.sales_total + self.tcs_amount 

    @property
    def tcs_amount(self):
        # TCS applies only to international, non-cash package services.
        # Note this uses a case-insensitive cash test, where purchase_total and
        # sales_total above use a case-sensitive one. That difference is carried
        # over from the original queries deliberately -- see the note in
        # tests/README.md before unifying them.
        def qualifying(rows):
            return _sum_amount(
                rows, 'sales_amount',
                lambda row: _not_cash_iexact(row) and _is_international(row),
            )

        total = (
            qualifying(self._service_rows('hotels')) +
            qualifying(self._service_rows('transfers')) +
            qualifying(self._service_rows('sightseeings'))
        )
        return total * Decimal('0.02')

    @property
    def gross_profit(self):
        return self.sales_total - self.purchase_total

    @property
    def sales_gst(self):
        gst_invoice = self.invoice_amount * Decimal('0.05')  # 5% of invoice
        gst_profit = self.gross_profit * Decimal('0.18')     # 18% of gross profit
        return min(gst_invoice, gst_profit)

    @property
    def net_profit(self):
        return self.gross_profit - self.sales_gst
    


class BookingService(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE)
    service = models.ForeignKey(
        'services.ServiceList', on_delete=models.CASCADE)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('booking', 'service')

    def __str__(self):
        return f"{self.booking.booking_id} - {self.service.name}"

# bookings/models.py
import os
from django.db import models
from services.models import ServiceList  # Your existing service model
from clients.models import Client  # Your existing client model
from suppliers.models import Supplier  # Your existing supplier model
from bookings.models import Booking  # Your existing booking model

from django.utils import timezone
from django.utils.text import slugify

def booking_document_path(instance, filename):
    booking_id = instance.booking.booking_id if instance.booking else 'no_booking'
    return os.path.join("booking_documents", booking_id, filename)

import os
from django.utils import timezone
from django.utils.text import slugify



class BookingDocument(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='documents')
    service = models.ForeignKey(ServiceList, on_delete=models.PROTECT)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    document = models.FileField(upload_to=booking_document_path)  # Use the simplified function
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Document for {self.booking.booking_id}"
