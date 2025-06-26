from django.contrib import admin
from .models import Booking, Status, Mode

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    readonly_fields = [
        'booking_id', 'created_by', 'booking_date',
        'tour_start_date', 'tour_end_date', 'status'
    ]
    
    list_display = [
        'booking_id', 'client', 'booking_date', 
        'status', 'tcs_amount', 'gross_profit', 
        'sales_gst', 'net_profit'
    ]
    
    @admin.display(description='TCS Amount')
    def tcs_amount(self, obj):
        return obj.tcs_amount

    @admin.display(description='Gross Profit')
    def gross_profit(self, obj):
        return obj.gross_profit

    @admin.display(description='Sales GST')
    def sales_gst(self, obj):
        return obj.sales_gst

    @admin.display(description='Net Profit')
    def net_profit(self, obj):
        return obj.net_profit

@admin.register(Status)
class StatusAdmin(admin.ModelAdmin):
    list_display = ['name']

@admin.register(Mode)
class ModeAdmin(admin.ModelAdmin):
    list_display = ['name']


from .models import BookingDocument

@admin.register(BookingDocument)
class BookingDocumentAdmin(admin.ModelAdmin):
    list_display = ('booking', 'service', 'supplier', 'uploaded_at')
    # autocomplete_fields = ('booking', 'service', 'supplier')