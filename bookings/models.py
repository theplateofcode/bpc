from decimal import Decimal
from django.db import models
from django.db.models import Sum
from django.conf import settings

# bookings/models.py


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

    @property
    def purchase_total(self):
        total = Decimal('0')
        # Tickets (always included)
        total += self.tickets.aggregate(total=Sum('purchase_amount')
                                        )['total'] or Decimal('0')

        # Visa/Passport/Insurance (exclude cash)
        total += self.visas.exclude(mode__name='Cash').aggregate(
            total=Sum('purchase_amount'))['total'] or Decimal('0')
        total += self.passports.exclude(mode__name='Cash').aggregate(
            total=Sum('purchase_amount'))['total'] or Decimal('0')
        total += self.insurances.exclude(mode__name='Cash').aggregate(
            total=Sum('purchase_amount'))['total'] or Decimal('0')

        # Package services (exclude cash)
        total += self._package_purchase_total
        return total

    @property
    def _package_purchase_total(self):
        return (
            (self.hotels.exclude(mode__name='Cash').aggregate(total=Sum('purchase_amount'))['total'] or Decimal('0')) +
            (self.sightseeings.exclude(mode__name='Cash').aggregate(total=Sum('purchase_amount'))['total'] or Decimal('0')) +
            (self.transfers.exclude(mode__name='Cash').aggregate(
                total=Sum('purchase_amount'))['total'] or Decimal('0'))
        )

    @property
    def sales_total(self):
        total = Decimal('0')
        # Tickets (always included)
        total += self.tickets.aggregate(total=Sum('sales_amount')
                                        )['total'] or Decimal('0')

        # Visa/Passport/Insurance (exclude cash)
        total += self.visas.exclude(mode__name='Cash').aggregate(
            total=Sum('sales_amount'))['total'] or Decimal('0')
        total += self.passports.exclude(mode__name='Cash').aggregate(
            total=Sum('sales_amount'))['total'] or Decimal('0')
        total += self.insurances.exclude(mode__name='Cash').aggregate(
            total=Sum('sales_amount'))['total'] or Decimal('0')

        # Package services (exclude cash)
        total += self._package_sales_total
        return total

    @property
    def _package_sales_total(self):
        return (
            (self.hotels.exclude(mode__name='Cash').aggregate(total=Sum('sales_amount'))['total'] or Decimal('0')) +
            (self.sightseeings.exclude(mode__name='Cash').aggregate(total=Sum('sales_amount'))['total'] or Decimal('0')) +
            (self.transfers.exclude(mode__name='Cash').aggregate(
                total=Sum('sales_amount'))['total'] or Decimal('0'))
        )

    # bookings/models.py
    @property
    def invoice_amount(self):
        return self.sales_total + self.tcs_amount 

    @property
    def tcs_amount(self):
        hotel_sales = self.hotels.exclude(mode__name__iexact='cash').filter(
            travel_type__iexact='international'
        ).aggregate(total=Sum('sales_amount'))['total'] or Decimal('0')
        # print("DEBUG: hotel_sales", hotel_sales)
        transfer_sales = self.transfers.exclude(mode__name__iexact='cash').filter(
            travel_type__iexact='international'
        ).aggregate(total=Sum('sales_amount'))['total'] or Decimal('0')
        # print("DEBUG: transfer_sales", transfer_sales)
        sightseeing_sales = self.sightseeings.exclude(mode__name__iexact='cash').filter(
            travel_type__iexact='international'
        ).aggregate(total=Sum('sales_amount'))['total'] or Decimal('0')
        # print("DEBUG: sightseeing_sales", sightseeing_sales)
        total = hotel_sales + transfer_sales + sightseeing_sales
        # print("DEBUG: total TCS amount", total)
        return total * Decimal('0.05')

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
