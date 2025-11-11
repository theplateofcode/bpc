from django.db import models

class Mode(models.Model):
    name = models.CharField(max_length=50, unique=True)

    class Meta:
        verbose_name = "Mode of Payment"
        verbose_name_plural = "Modes of Payment"
        ordering = ['name']

    def __str__(self):
        return self.name


from django.conf import settings
from django.utils import timezone

from bookings.models import Booking
# Reuse your existing payments mode model (table: payments_mode)
# If your class name differs, adjust import accordingly.

class PaymentReceived(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="payments")
    mode = models.ForeignKey(Mode, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    received_on = models.DateField(default=timezone.now)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="received_payments")
    document = models.FileField(upload_to="payment_docs/", blank=True, null=True)
    remarks = models.TextField(blank=True)

    sent_for_approval = models.BooleanField(default=True)
    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="approved_payments", blank=True, null=True)
    approved_on = models.DateTimeField(blank=True, null=True)

    # Convenience: if user marks booking “fully received”
    is_full = models.BooleanField(default=False)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # remaining shortfall
    booking_closed = models.BooleanField(default=False)  

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def approve(self, user):
        self.approved = True
        self.approved_by = user
        self.approved_on = timezone.now()
        self.save()

    def __str__(self):
        return f"{self.booking.booking_id} / {self.amount} / {'APPROVED' if self.approved else 'PENDING'}"
