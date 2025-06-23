from django.db import models

class Mode(models.Model):
    name = models.CharField(max_length=50, unique=True)

    class Meta:
        verbose_name = "Mode of Payment"
        verbose_name_plural = "Modes of Payment"
        ordering = ['name']

    def __str__(self):
        return self.name
