from django import forms
from .models import Mode

class ModeOfPaymentForm(forms.ModelForm):
    class Meta:
        model = Mode
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'})
        }
