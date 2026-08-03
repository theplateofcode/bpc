from django import forms
from .models import Ticket, Passport, Visa, Insurance, Hotel, SightSeeing, Transfer, Hotel, SightSeeing, Transfer



from .models import Carrier

from django import forms

class CustomDateInput(forms.DateInput):
    input_type = 'text'
    format = '%d/%m/%y'

    def __init__(self, **kwargs):
        kwargs['format'] = self.format
        super().__init__(**kwargs)
        self.attrs.update({'placeholder': 'dd/mm/yy', 'class': 'form-control datepicker'})


class ServiceDateInput(forms.DateTimeInput):
    """The date widget every service form shares.

    All seven forms declared their own <input type="date"> with
    format='%d-%m-%Y' (Hotel had '%d-%m-%y'). An input of type="date" only
    accepts a value in YYYY-MM-DD; given "15-03-2025" the browser rejects it
    and renders an empty box, so every edit page opened with its date blank
    and silently re-saved whatever the user picked instead.

    Rendering as %Y-%m-%d fixes that. Submission is unaffected: a date input
    always posts YYYY-MM-DD regardless of what it was rendered with, which is
    why saving worked even while the field looked empty.

    The bogus format="date" attribute the old widgets emitted is dropped -- it
    is not an HTML attribute and did nothing.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault('format', '%Y-%m-%d')
        attrs = {'type': 'date', 'class': 'form-control'}
        attrs.update(kwargs.pop('attrs', None) or {})
        super().__init__(attrs=attrs, **kwargs)



class CarrierForm(forms.ModelForm):
    class Meta:
        model = Carrier
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'})
        }



class TicketForm(forms.ModelForm):
    class Meta:
        required_css_class = 'required'

        model = Ticket
        fields = ['booking', 'date', 'carrier', 'supplier', 'mode', 'purchase_amount', 'sales_amount','notes',
            'attachment',]
        widgets = {
            'booking': forms.HiddenInput(),
            'date': ServiceDateInput(),
            # The rest will be handled by autocomplete in the template
            'purchase_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'sales_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

# Repeat similar ModelForm for Passport, Visa, Insurance, Hotel, SightSeeing, Transfer
class VisaForm(forms.ModelForm):
    class Meta:
        required_css_class = 'required'

        model = Visa
        fields = ['booking', 'date', 'supplier', 'mode', 'purchase_amount', 'sales_amount','notes','attachment']
        widgets = {
            'booking': forms.HiddenInput(),
            'date': ServiceDateInput(),
            # The rest will be handled by autocomplete in the template
            'purchase_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'sales_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class PassportForm(forms.ModelForm):
    class Meta:
        required_css_class = 'required'

        model = Passport
        fields = ['booking', 'date',  'supplier', 'mode', 'purchase_amount', 'sales_amount', 'notes','attachment']
        widgets = {
            'booking': forms.HiddenInput(),
            'date': ServiceDateInput(),
            # The rest will be handled by autocomplete in the template
            'purchase_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'sales_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }



# ===== Insurance Form =====
class InsuranceForm(forms.ModelForm):
    class Meta:
        required_css_class = 'required'
        model = Insurance
        fields = ['booking', 'date', 'supplier', 'mode', 'purchase_amount', 'sales_amount','notes',
            'attachment',]
        widgets = {
            'booking': forms.HiddenInput(),
            'date': ServiceDateInput(),
            'purchase_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'sales_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

# ===== Hotel Form =====
class HotelForm(forms.ModelForm):
    class Meta:
        required_css_class = 'required'
        model = Hotel
        fields = ['booking', 'date', 'supplier', 'mode', 'travel_type', 'purchase_amount', 'sales_amount','notes','attachment']
        widgets = {
            'booking': forms.HiddenInput(),
            'date': ServiceDateInput(),
            'travel_type': forms.Select(attrs={'class': 'form-select'}),
            'purchase_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'sales_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

# ===== SightSeeing Form =====
class SightSeeingForm(forms.ModelForm):
    class Meta:
        required_css_class = 'required'
        model = SightSeeing
        fields = ['booking', 'date', 'supplier', 'mode', 'travel_type', 'purchase_amount', 'sales_amount','notes','attachment']
        widgets = {
            'booking': forms.HiddenInput(),
            'date': ServiceDateInput(),
            'travel_type': forms.Select(attrs={'class': 'form-select'}),
            'purchase_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'sales_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

# ===== Transfer Form =====
class TransferForm(forms.ModelForm):
    class Meta:
        required_css_class = 'required'
        model = Transfer
        fields = ['booking', 'date', 'supplier', 'mode', 'travel_type', 'purchase_amount', 'sales_amount','notes','attachment']
        widgets = {
            'booking': forms.HiddenInput(),
            'date': ServiceDateInput(),
            'travel_type': forms.Select(attrs={'class': 'form-select'}),
            'purchase_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'sales_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
