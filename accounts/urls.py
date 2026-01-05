from django.urls import path
from .views import (
    AccountTodoView,
    process_service,
    processed_services,
    processed_services_data,
)

urlpatterns = [
    # Accounts To-Do (unprocessed services)
    path("todo/", AccountTodoView.as_view(), name="accounts_todo"),

    # Process a single service
    path(
        "process/<str:service_type>/<int:pk>/",
        process_service,
        name="process_service",
    ),

    # Processed services (HTML shell only)
    path(
        "processed/",
        processed_services,
        name="processed_services",
    ),

    # Processed services – lazy load / infinite scroll API
    path(
        "processed/data/",
        processed_services_data,
        name="processed_services_data",
    ),
]
