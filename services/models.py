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


# TICKET
class Ticket(models.Model):
    booking = models.ForeignKey(
        'bookings.Booking',
        on_delete=models.RESTRICT,
        related_name='tickets'
    )
    ticket_booking_id = models.CharField(max_length=10, unique=True, blank=True)
    date = models.DateTimeField(blank=False, null=False)
    carrier = models.ForeignKey(
        Carrier,
        on_delete=models.SET_NULL,
        null=True,  # Carrier is optional
        blank=True,
        related_name='tickets'
    )
    supplier = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.PROTECT,  # Required field
        related_name='ticket_suppliers'
    )
    mode = models.ForeignKey(
        'payments.Mode',
        on_delete=models.PROTECT,  # Required field
    )
    purchase_amount = models.DecimalField(max_digits=12, decimal_places=2, blank=False, null=False)
    sales_amount = models.DecimalField(max_digits=12, decimal_places=2, blank=False, null=False)
    notes = models.TextField(blank=True, null=True)
    attachment = models.FileField(upload_to='service_attachments/', blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    finished = models.BooleanField(default=False)          # Set by operational team
    accounts_processed = models.BooleanField(default=False)  # Set by accounts team  

    def save(self, *args, **kwargs):
        if not self.ticket_booking_id:
            last = Ticket.objects.all().order_by('id').last()
            if last and last.ticket_booking_id:
                last_num = int(last.ticket_booking_id.split('-')[-1])
                new_num = last_num + 1
            else:
                new_num = 1
            self.ticket_booking_id = f"TI-{new_num:04d}"
        super().save(*args, **kwargs)

    @property
    def profit(self):
        return (self.sales_amount or 0) - (self.purchase_amount or 0)

    def __str__(self):
        return f"{self.ticket_booking_id} ({self.booking})"

# PASSPORT
class Passport(models.Model):
    booking = models.ForeignKey(
        'bookings.Booking',
        on_delete=models.RESTRICT,
        related_name='passports'
    )
    passport_booking_id = models.CharField(max_length=10, unique=True, blank=True)
    date = models.DateTimeField()
    supplier = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.PROTECT,  # Required
        related_name='passport_suppliers'
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
    def save(self, *args, **kwargs):
        if not self.passport_booking_id:
            last = Passport.objects.all().order_by('id').last()
            if last and last.passport_booking_id:
                last_num = int(last.passport_booking_id.split('-')[-1])
                new_num = last_num + 1
            else:
                new_num = 1
            self.passport_booking_id = f"PA-{new_num:04d}"
        super().save(*args, **kwargs)

    @property
    def profit(self):
        return (self.sales_amount or 0) - (self.purchase_amount or 0)

    def __str__(self):
        return f"{self.passport_booking_id} ({self.booking})"

# VISA
class Visa(models.Model):
    booking = models.ForeignKey(
        'bookings.Booking',
        on_delete=models.RESTRICT,
        related_name='visas'
    )
    visa_booking_id = models.CharField(max_length=10, unique=True, blank=True)
    date = models.DateTimeField()
    supplier = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.PROTECT,  # Required
        related_name='visa_suppliers'
    )
    mode = models.ForeignKey(
        'payments.Mode',
        on_delete=models.PROTECT,  # Required
    )
    purchase_amount = models.DecimalField(max_digits=12, decimal_places=2, blank=False, null=False)
    sales_amount = models.DecimalField(max_digits=12, decimal_places=2, blank=False, null=False)
    notes = models.TextField(blank=True, null=True)
    attachment = models.FileField(upload_to='service_attachments/', blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    finished = models.BooleanField(default=False)          # Set by operational team
    accounts_processed = models.BooleanField(default=False)  # Set by accounts team
    def save(self, *args, **kwargs):
        if not self.visa_booking_id:
            last = Visa.objects.all().order_by('id').last()
            if last and last.visa_booking_id:
                last_num = int(last.visa_booking_id.split('-')[-1])
                new_num = last_num + 1
            else:
                new_num = 1
            self.visa_booking_id = f"VI-{new_num:04d}"
        super().save(*args, **kwargs)

    @property
    def profit(self):
        return (self.sales_amount or 0) - (self.purchase_amount or 0)

    def __str__(self):
        return f"{self.visa_booking_id} ({self.booking})"

# INSURANCE
class Insurance(models.Model):
    booking = models.ForeignKey(
        'bookings.Booking',
        on_delete=models.RESTRICT,
        related_name='insurances'
    )
    insurance_booking_id = models.CharField(max_length=10, unique=True, blank=True)
    date = models.DateTimeField()
    supplier = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.PROTECT,  # Required
        related_name='insurance_suppliers'
    )
    mode = models.ForeignKey(
        'payments.Mode',
        on_delete=models.PROTECT,  # Required
    )
    purchase_amount = models.DecimalField(max_digits=12, decimal_places=2, blank=False, null=False)
    sales_amount = models.DecimalField(max_digits=12, decimal_places=2, blank=False, null=False)
    notes = models.TextField(blank=True, null=True)
    attachment = models.FileField(upload_to='service_attachments/', blank=True, null=True)
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    finished = models.BooleanField(default=False)          # Set by operational team
    accounts_processed = models.BooleanField(default=False)  # Set by accounts team
    def save(self, *args, **kwargs):
        if not self.insurance_booking_id:
            last = Insurance.objects.all().order_by('id').last()
            if last and last.insurance_booking_id:
                last_num = int(last.insurance_booking_id.split('-')[-1])
                new_num = last_num + 1
            else:
                new_num = 1
            self.insurance_booking_id = f"IN-{new_num:04d}"
        super().save(*args, **kwargs)

    @property
    def profit(self):
        return (self.sales_amount or 0) - (self.purchase_amount or 0)

    def __str__(self):
        return f"{self.insurance_booking_id} ({self.booking})"

# HOTEL
class Hotel(models.Model):
    TRAVEL_TYPE_CHOICES = [
        ('domestic', 'Domestic'),
        ('international', 'International'),
    ]
    booking = models.ForeignKey(
        'bookings.Booking',
        on_delete=models.RESTRICT,
        related_name='hotels'
    )
    hotel_booking_id = models.CharField(max_length=10, unique=True, blank=True)
    date = models.DateTimeField()
    supplier = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.PROTECT,  # Required
        related_name='hotel_suppliers'
    )
    mode = models.ForeignKey(
        'payments.Mode',
        on_delete=models.PROTECT,  # Required
    )
    purchase_amount = models.DecimalField(max_digits=12, decimal_places=2)
    sales_amount = models.DecimalField(max_digits=12, decimal_places=2)
    travel_type = models.CharField(max_length=20, choices=TRAVEL_TYPE_CHOICES)
    notes = models.TextField(blank=True, null=True)
    attachment = models.FileField(upload_to='service_attachments/', blank=True, null=True)
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    finished = models.BooleanField(default=False)          # Set by operational team
    accounts_processed = models.BooleanField(default=False)  # Set by accounts team
    def save(self, *args, **kwargs):
        if not self.hotel_booking_id:
            last = Hotel.objects.all().order_by('id').last()
            if last and last.hotel_booking_id:
                last_num = int(last.hotel_booking_id.split('-')[-1])
                new_num = last_num + 1
            else:
                new_num = 1
            self.hotel_booking_id = f"HO-{new_num:04d}"
        super().save(*args, **kwargs)

    @property
    def profit(self):
        return (self.sales_amount or 0) - (self.purchase_amount or 0)

    def __str__(self):
        return f"{self.hotel_booking_id} ({self.booking})"

# SIGHTSEEING
class SightSeeing(models.Model):
    TRAVEL_TYPE_CHOICES = [
        ('domestic', 'Domestic'),
        ('international', 'International'),
    ]
    booking = models.ForeignKey(
        'bookings.Booking',
        on_delete=models.RESTRICT,
        related_name='sightseeings'
    )
    sightseeing_booking_id = models.CharField(max_length=10, unique=True, blank=True)
    date = models.DateTimeField()
    supplier = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.PROTECT,  # Required
        related_name='sightseeing_suppliers'
    )
    mode = models.ForeignKey(
        'payments.Mode',
        on_delete=models.PROTECT,  # Required
    )
    purchase_amount = models.DecimalField(max_digits=12, decimal_places=2)
    sales_amount = models.DecimalField(max_digits=12, decimal_places=2)
    travel_type = models.CharField(max_length=20, choices=TRAVEL_TYPE_CHOICES)
    notes = models.TextField(blank=True, null=True)
    attachment = models.FileField(upload_to='service_attachments/', blank=True, null=True)
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    finished = models.BooleanField(default=False)          # Set by operational team
    accounts_processed = models.BooleanField(default=False)  # Set by accounts team
    def save(self, *args, **kwargs):
        if not self.sightseeing_booking_id:
            last = SightSeeing.objects.all().order_by('id').last()
            if last and last.sightseeing_booking_id:
                last_num = int(last.sightseeing_booking_id.split('-')[-1])
                new_num = last_num + 1
            else:
                new_num = 1
            self.sightseeing_booking_id = f"SS-{new_num:04d}"
        super().save(*args, **kwargs)

    @property
    def profit(self):
        return (self.sales_amount or 0) - (self.purchase_amount or 0)

    def __str__(self):
        return f"{self.sightseeing_booking_id} ({self.booking})"

# TRANSFER
class Transfer(models.Model):
    TRAVEL_TYPE_CHOICES = [
        ('domestic', 'Domestic'),
        ('international', 'International'),
    ]
    booking = models.ForeignKey(
        'bookings.Booking',
        on_delete=models.RESTRICT,
        related_name='transfers'
    )
    transfer_booking_id = models.CharField(max_length=10, unique=True, blank=True)
    date = models.DateTimeField()
    supplier = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.PROTECT,  # Required
        related_name='transfer_suppliers'
    )
    mode = models.ForeignKey(
        'payments.Mode',
        on_delete=models.PROTECT,  # Required
    )
    purchase_amount = models.DecimalField(max_digits=12, decimal_places=2)
    sales_amount = models.DecimalField(max_digits=12, decimal_places=2)
    travel_type = models.CharField(max_length=20, choices=TRAVEL_TYPE_CHOICES)
    notes = models.TextField(blank=True, null=True)
    attachment = models.FileField(upload_to='service_attachments/', blank=True, null=True)
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    finished = models.BooleanField(default=False)          # Set by operational team
    accounts_processed = models.BooleanField(default=False)  # Set by accounts team
    def save(self, *args, **kwargs):
        if not self.transfer_booking_id:
            last = Transfer.objects.all().order_by('id').last()
            if last and last.transfer_booking_id:
                last_num = int(last.transfer_booking_id.split('-')[-1])
                new_num = last_num + 1
            else:
                new_num = 1
            self.transfer_booking_id = f"TR-{new_num:04d}"
        super().save(*args, **kwargs)

    @property
    def profit(self):
        return (self.sales_amount or 0) - (self.purchase_amount or 0)

    def __str__(self):
        return f"{self.transfer_booking_id} ({self.booking})"


# Create your models here.


