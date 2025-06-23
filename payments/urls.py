from django.urls import path
from .views import modes_of_payment, create_mode, update_mode, delete_mode

urlpatterns = [
    path('', modes_of_payment, name='modes_of_payment'),
    path('new/', create_mode, name='create_mode'),
    path('<int:pk>/edit/', update_mode, name='update_mode'),
    path('<int:pk>/delete/', delete_mode, name='delete_mode'),
]
