from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib.auth.models import Group

def group_required(*group_names):
    def in_groups(user):
        if user.is_authenticated:
            if user.is_superuser or user.groups.filter(name__in=group_names).exists():
                return True
        return False
    return user_passes_test(in_groups, login_url='/accounts/login/')

# services/utils.py

def get_service_model(service_type):
    from services.models import Ticket, Visa, Hotel, Insurance, Transfer, SightSeeing, Passport
    service_map = {
        'ticket': Ticket,
        'visa': Visa,
        'hotel': Hotel,
        'insurance': Insurance,
        'transfer': Transfer,
        'sightseeing': SightSeeing,
        'passport': Passport,
    }
    return service_map.get(service_type.lower())
