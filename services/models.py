from django.db import models
from django.conf import settings

class ServiceList(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name

# services/models.py
# removed currently to implement direct flag from bookings ##1
# class ServiceStatus(models.TextChoices):
#     DRAFT = 'draft', 'Draft'
#     READY_FOR_ACCOUNTS = 'ready', 'Ready for Accounts'
#     PROCESSED = 'processed', 'Processed'

# Carrier model (for airlines, etc.)
class Carrier(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = "Carrier"
        verbose_name_plural = "Carriers"
        ordering = ['name']

    def __str__(self):
        return self.name


class ServiceEntry(models.Model):
    """The shape every service table shares.

    Ticket, Passport, Visa, Insurance, Hotel, SightSeeing and Transfer were
    seven near-identical copies of the same eleven fields, the same reference-id
    generator and the same profit property. They stay seven separate tables --
    this is an abstract base, so no schema changes and no data moves -- but the
    definition now lives in one place.

    The `%(class)s` placeholders expand to the concrete model name, which
    reproduces every existing related_name exactly: `%(class)ss` gives
    booking.tickets / .visas / .hotels / .sightseeings and so on, and
    `%(class)s_suppliers` gives supplier.ticket_suppliers and its siblings.
    `mode` and `created_by` have no related_name here, matching the originals,
    so each child keeps its default `<model>_set` accessor.

    Subclasses set `booking_id_field` and `booking_id_prefix`; everything else
    is inherited.
    """

    #: Name of the concrete model's unique reference column, e.g.
    #: "ticket_booking_id". Each table names it differently, so it cannot move
    #: into the base without renaming columns.
    booking_id_field = None
    #: Two-letter prefix for generated references, e.g. "TI" -> "TI-0001".
    booking_id_prefix = None

    booking = models.ForeignKey(
        'bookings.Booking',
        on_delete=models.RESTRICT,
        related_name='%(class)ss'
    )
    date = models.DateTimeField()
    supplier = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.PROTECT,  # Required
        related_name='%(class)s_suppliers'
    )
    mode = models.ForeignKey(
        'payments.Mode',
        on_delete=models.PROTECT,  # Required
    )
    purchase_amount = models.DecimalField(max_digits=12, decimal_places=2)
    sales_amount = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.TextField(blank=True, null=True)
    attachment = models.FileField(upload_to='service_attachments/', blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    finished = models.BooleanField(default=False)          # Set by operational team
    accounts_processed = models.BooleanField(default=False)  # Set by accounts team

    class Meta:
        abstract = True

    @property
    def reference(self):
        """The generated id, whatever this table happens to call its column."""
        return getattr(self, self.booking_id_field)

    def save(self, *args, **kwargs):
        # Unchanged from the seven copies this replaces, including the race:
        # two concurrent saves read the same last row and generate the same
        # reference, and one of them fails on the unique constraint. Fixing
        # that changes behaviour, so it is left alone here.
        if not getattr(self, self.booking_id_field):
            last = type(self).objects.all().order_by('id').last()
            last_reference = getattr(last, self.booking_id_field, None) if last else None
            if last and last_reference:
                new_num = int(last_reference.split('-')[-1]) + 1
            else:
                new_num = 1
            setattr(self, self.booking_id_field,
                    f"{self.booking_id_prefix}-{new_num:04d}")
        super().save(*args, **kwargs)

    @property
    def profit(self):
        return (self.sales_amount or 0) - (self.purchase_amount or 0)

    def __str__(self):
        return f"{self.reference} ({self.booking})"


class PackageServiceEntry(ServiceEntry):
    """Service entries that are domestic or international.

    Only these three carry travel_type, and only these three attract TCS.
    """

    TRAVEL_TYPE_CHOICES = [
        ('domestic', 'Domestic'),
        ('international', 'International'),
    ]

    travel_type = models.CharField(max_length=20, choices=TRAVEL_TYPE_CHOICES)

    class Meta:
        abstract = True


# The accounts screens scan on these two flags:
# filter(accounts_processed=True) and filter(finished=True,
# accounts_processed=False). Both are equality tests, so one composite led by
# accounts_processed serves each. Index names must be unique per table, so the
# Meta stays on the concrete models.

# TICKET
class Ticket(ServiceEntry):
    booking_id_field = 'ticket_booking_id'
    booking_id_prefix = 'TI'

    ticket_booking_id = models.CharField(max_length=10, unique=True, blank=True)
    carrier = models.ForeignKey(
        Carrier,
        on_delete=models.SET_NULL,
        null=True,  # Carrier is optional
        blank=True,
        related_name='tickets'
    )

    class Meta:
        indexes = [
            models.Index(fields=["accounts_processed", "finished"],
                         name="ticket_acct_finished_idx"),
        ]


# PASSPORT
class Passport(ServiceEntry):
    booking_id_field = 'passport_booking_id'
    booking_id_prefix = 'PA'

    passport_booking_id = models.CharField(max_length=10, unique=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["accounts_processed", "finished"],
                         name="passport_acct_fin_idx"),
        ]


# VISA
class Visa(ServiceEntry):
    booking_id_field = 'visa_booking_id'
    booking_id_prefix = 'VI'

    visa_booking_id = models.CharField(max_length=10, unique=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["accounts_processed", "finished"],
                         name="visa_acct_fin_idx"),
        ]


# INSURANCE
class Insurance(ServiceEntry):
    booking_id_field = 'insurance_booking_id'
    booking_id_prefix = 'IN'

    insurance_booking_id = models.CharField(max_length=10, unique=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["accounts_processed", "finished"],
                         name="insurance_acct_fin_idx"),
        ]


# HOTEL
class Hotel(PackageServiceEntry):
    booking_id_field = 'hotel_booking_id'
    booking_id_prefix = 'HO'

    hotel_booking_id = models.CharField(max_length=10, unique=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["accounts_processed", "finished"],
                         name="hotel_acct_fin_idx"),
            # TCS sums international, non-cash rows for one booking.
            models.Index(fields=["booking", "travel_type"],
                         name="hotel_bk_travel_idx"),
        ]


# SIGHTSEEING
class SightSeeing(PackageServiceEntry):
    booking_id_field = 'sightseeing_booking_id'
    booking_id_prefix = 'SS'

    sightseeing_booking_id = models.CharField(max_length=10, unique=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["accounts_processed", "finished"],
                         name="sightsee_acct_fin_idx"),
            models.Index(fields=["booking", "travel_type"],
                         name="sightsee_bk_travel_idx"),
        ]


# TRANSFER
class Transfer(PackageServiceEntry):
    booking_id_field = 'transfer_booking_id'
    booking_id_prefix = 'TR'

    transfer_booking_id = models.CharField(max_length=10, unique=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["accounts_processed", "finished"],
                         name="transfer_acct_fin_idx"),
            models.Index(fields=["booking", "travel_type"],
                         name="transfer_bk_travel_idx"),
        ]
