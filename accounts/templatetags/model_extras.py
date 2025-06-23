# your_app/templatetags/model_extras.py
from django import template
register = template.Library()

@register.filter
def model_name(obj):
    return obj._meta.model_name  # Accesses the model name safely
