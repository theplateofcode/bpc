from django.urls import path
from .views import AccountTodoView, process_service, processed_services

urlpatterns = [
    path('todo/', AccountTodoView.as_view(), name='accounts_todo'),
    path('process/<str:service_type>/<int:pk>/', process_service, name='process_service'),
    path('processed/', processed_services, name='processed_services'),
]
