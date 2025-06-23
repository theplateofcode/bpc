from django.urls import path
from . import views

urlpatterns = [
    path('', views.clients, name='clients'),  # /clients/
    path('create/', views.create_client, name='create_client'),  # /clients/create/
    path('<int:pk>/edit/', views.edit_client, name='edit_client'),  # /clients/1/edit/
    path('<int:pk>/delete/', views.delete_client, name='delete_client'),  # /clients/1/delete/
    path('autocomplete/', views.client_autocomplete, name='client_autocomplete'),
    path('create-ajax/', views.create_client_ajax, name='create_client_ajax'),
]
