from django.contrib import admin
from .models import Mode

@admin.register(Mode)
class ModeAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)
