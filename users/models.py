# Create your models here.
from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    ROLE_CHOICES = [
        ('OWNER', 'Owner'),
        ('STAFF', 'Staff'),
        ('ACCOUNTANT', 'Accountant'),
        ('ADMIN', 'Admin (Dev)'),
    ]
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)

    # Add any extra fields you want here
    service_category = models.ManyToManyField(
        'services.ServiceList',
        blank=False,
        related_name='users'
    )

    def is_owner(self):
        return self.role == 'OWNER'

    def is_staff_member(self):
        return self.role == 'STAFF'

    def is_admin(self):
        return self.role == 'ADMIN'
    
    def is_accountant(self):
        return self.role == 'ACCOUNTANT'
