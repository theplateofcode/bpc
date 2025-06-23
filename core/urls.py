from django.urls import path
from .views import home
from .views import manage_groups


urlpatterns = [
    path('', home, name='home'),
    path('manage-groups/', manage_groups, name='manage_groups'),
]

