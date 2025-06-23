from django.urls import path
from . import views

urlpatterns = [
    path('', views.suppliers, name='suppliers'),
    path('create/', views.create_supplier, name='create_supplier'),
    path('<int:pk>/edit/', views.edit_supplier, name='edit_supplier'),
    path('<int:pk>/delete/', views.delete_supplier, name='delete_supplier'),
]
