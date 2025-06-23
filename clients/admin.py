from django.contrib import admin
from .models import Client

@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('client_id', 'first_name', 'middle_name', 'last_name', 'contact_number')
    search_fields = ('first_name', 'last_name', 'contact_number')
    list_filter = ()
