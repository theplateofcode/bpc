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


from decimal import Decimal
from django.db import models, transaction
from django.conf import settings
from django.db.models import Sum



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
        'Status',
        on_delete=models.PROTECT,
        default=1
    )
    accounts_done = models.BooleanField(default=False)

    # Service flags
    tickets_finished = models.BooleanField(default=False)
    visas_finished = models.BooleanField(default=False)
    hotels_finished = models.BooleanField(default=False)
    insurances_finished = models.BooleanField(default=False)
    transfers_finished = models.BooleanField(default=False)
    sightseeings_finished = models.BooleanField(default=False)
    passports_finished = models.BooleanField(default=False)

    def get_service_statuses(self):
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
                statuses.append((display, getattr(self, flag, False)))
        return statuses

    def save(self, *args, **kwargs):
        if not self.booking_id:
            last = Booking.objects.order_by('id').last()
            last_num = last.id if last else 0
            self.booking_id = f"B-{last_num + 1:04d}"
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.tickets.all().delete()
        self.visas.all().delete()
        self.hotels.all().delete()
        self.insurances.all().delete()
        self.transfers.all().delete()
        self.sightseeings.all().delete()
        self.passports.all().delete()
        self.services.clear()
        self.bookingservice_set.all().delete()
        super().delete(*args, **kwargs)

    def __str__(self):
        return self.booking_id


     # -----------------------
    # Internal helper methods
    # -----------------------
    def _sum_decimal(self, qs, field_name: str) -> Decimal:
        val = qs.aggregate(total=Sum(field_name))["total"]
        return val or Decimal("0")

    def _is_cash_mode_filter(self):
        # Cash mode = mode.name contains "cash" (case-insensitive)
        return {"mode__name__icontains": "cash"}

    # -----------------------
    # Purchase split (REAL)
    # Uses SERVICE.mode (supplier payment mode)
    # -----------------------
    @property
    def purchase_cash(self) -> Decimal:
        f = self._is_cash_mode_filter()
        total = Decimal("0")
        total += self._sum_decimal(self.tickets.filter(**f), "purchase_amount")
        total += self._sum_decimal(self.visas.filter(**f), "purchase_amount")
        total += self._sum_decimal(self.passports.filter(**f), "purchase_amount")
        total += self._sum_decimal(self.insurances.filter(**f), "purchase_amount")
        total += self._sum_decimal(self.hotels.filter(**f), "purchase_amount")
        total += self._sum_decimal(self.sightseeings.filter(**f), "purchase_amount")
        total += self._sum_decimal(self.transfers.filter(**f), "purchase_amount")
        return total

    @property
    def purchase_non_cash(self) -> Decimal:
        return (self.purchase_total or Decimal("0")) - self.purchase_cash

    # -----------------------
    # Sales split (TARGET / BOOKING TOTAL)
    # This is NOT "actual sales"; it is sales_amount entered in services.
    # If you want "actual", keep using PaymentReceived in reports.
    # -----------------------
    @property
    def sales_cash_target(self) -> Decimal:
        f = self._is_cash_mode_filter()
        total = Decimal("0")
        total += self._sum_decimal(self.tickets.filter(**f), "sales_amount")
        total += self._sum_decimal(self.visas.filter(**f), "sales_amount")
        total += self._sum_decimal(self.passports.filter(**f), "sales_amount")
        total += self._sum_decimal(self.insurances.filter(**f), "sales_amount")
        total += self._sum_decimal(self.hotels.filter(**f), "sales_amount")
        total += self._sum_decimal(self.sightseeings.filter(**f), "sales_amount")
        total += self._sum_decimal(self.transfers.filter(**f), "sales_amount")
        return total

    @property
    def sales_non_cash_target(self) -> Decimal:
        total = (
            (self.tickets.aggregate(total=Sum("sales_amount"))["total"] or Decimal("0")) +
            (self.visas.aggregate(total=Sum("sales_amount"))["total"] or Decimal("0")) +
            (self.passports.aggregate(total=Sum("sales_amount"))["total"] or Decimal("0")) +
            (self.insurances.aggregate(total=Sum("sales_amount"))["total"] or Decimal("0")) +
            (self.hotels.aggregate(total=Sum("sales_amount"))["total"] or Decimal("0")) +
            (self.sightseeings.aggregate(total=Sum("sales_amount"))["total"] or Decimal("0")) +
            (self.transfers.aggregate(total=Sum("sales_amount"))["total"] or Decimal("0"))
        )
        return total - self.sales_cash_target

    @property
    def purchase_total(self):
        total = Decimal('0')
        total += self.tickets.aggregate(total=Sum('purchase_amount'))['total'] or Decimal('0')
        total += self.visas.aggregate(total=Sum('purchase_amount'))['total'] or Decimal('0')
        total += self.passports.aggregate(total=Sum('purchase_amount'))['total'] or Decimal('0')
        total += self.insurances.aggregate(total=Sum('purchase_amount'))['total'] or Decimal('0')
        total += self.hotels.aggregate(total=Sum('purchase_amount'))['total'] or Decimal('0')
        total += self.sightseeings.aggregate(total=Sum('purchase_amount'))['total'] or Decimal('0')
        total += self.transfers.aggregate(total=Sum('purchase_amount'))['total'] or Decimal('0')
        return total

    @property
    def sales_total(self):
        total = Decimal('0')
        total += self.tickets.aggregate(total=Sum('sales_amount'))['total'] or Decimal('0')
        total += self.visas.aggregate(total=Sum('sales_amount'))['total'] or Decimal('0')
        total += self.passports.aggregate(total=Sum('sales_amount'))['total'] or Decimal('0')
        total += self.insurances.aggregate(total=Sum('sales_amount'))['total'] or Decimal('0')
        total += self.hotels.aggregate(total=Sum('sales_amount'))['total'] or Decimal('0')
        total += self.sightseeings.aggregate(total=Sum('sales_amount'))['total'] or Decimal('0')
        total += self.transfers.aggregate(total=Sum('sales_amount'))['total'] or Decimal('0')
        return total

    @property
    def gross_profit(self):
        return self.sales_total - self.purchase_total

    @property
    def tcs_amount(self):
        hotel_sales = self.hotels.exclude(mode__name__iexact='cash').filter(
            travel_type__iexact='international'
        ).aggregate(total=Sum('sales_amount'))['total'] or Decimal('0')

        transfer_sales = self.transfers.exclude(mode__name__iexact='cash').filter(
            travel_type__iexact='international'
        ).aggregate(total=Sum('sales_amount'))['total'] or Decimal('0')

        sightseeing_sales = self.sightseeings.exclude(mode__name__iexact='cash').filter(
            travel_type__iexact='international'
        ).aggregate(total=Sum('sales_amount'))['total'] or Decimal('0')

        total = hotel_sales + transfer_sales + sightseeing_sales
        return total * Decimal('0.05')

    @property
    def invoice_amount(self):
        return self.sales_total + self.tcs_amount

    @property
    def sales_gst(self):
        gst = Decimal('0.0')
        gst_rate = Decimal('0.18')

        # Tickets: GST always applies
        for t in self.tickets.all():
            base = t.sales_amount - t.purchase_amount
            gst += base * gst_rate

        # Other services: GST only if mode is not cash
        for qs in [self.visas, self.passports, self.insurances, self.hotels, self.sightseeings, self.transfers]:
            for obj in qs.all():
                is_cash = getattr(obj.mode, 'name', '').lower() == 'cash' if hasattr(obj, 'mode') else False
                base = obj.sales_amount - obj.purchase_amount
                gst += Decimal('0') if is_cash else base * gst_rate

        return gst

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
