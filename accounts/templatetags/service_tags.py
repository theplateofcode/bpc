from django import template

register = template.Library()

@register.filter(name='service_type')
def service_type(obj):
    # Get human-readable service type from model meta
    return obj._meta.verbose_name.title()  # Safe in Python code
