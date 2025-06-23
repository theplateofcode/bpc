from django import forms
from .models import Booking, Status


class StatusForm(forms.ModelForm):
    class Meta:
        model = Status
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'})
        }


class BookingForm(forms.ModelForm):
    class Meta:
        model = Booking
        fields = [
            'booking_date',
            'number_of_adults',
            'number_of_children',
            'tour_start_date',
            'tour_end_date',
            'status'
        ]
        widgets = {
            'booking_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'number_of_adults': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1
            }),
            'number_of_children': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 0
            }),
            'tour_start_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'tour_end_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'status': forms.Select(attrs={
                'class': 'form-select'
            })
        }
