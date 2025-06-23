from django.db import models
from services.models import ServiceList  # Adjust if your import path differs

class Supplier(models.Model):
    name = models.CharField(max_length=100)
    category = models.ForeignKey(
        ServiceList,
        on_delete=models.PROTECT,
        related_name='suppliers'
    )
    contact_person = models.CharField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.category.name})"
