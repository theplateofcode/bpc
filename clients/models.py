from django.db import models

class Client(models.Model):
    # Auto-increment integer, not shown to user
    id = models.AutoField(primary_key=True)
    first_name = models.CharField(max_length=50)
    middle_name = models.CharField(max_length=50, blank=True)
    last_name = models.CharField(max_length=50)
    contact_number = models.CharField(max_length=20, unique=True)
    

    @property
    def client_id(self):
        return f"C-{self.id:04d}"

    def __str__(self):
        return f"{self.client_id} - {self.first_name} {self.last_name}"