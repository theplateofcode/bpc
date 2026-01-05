from django.urls import path
from .views import gst_tcs_view, gst_tcs_data, gst_tcs_filters

app_name = "gst_tcs"

urlpatterns = [
    path("<str:mode>/", gst_tcs_view, name="view"),
    path("<str:mode>/data/", gst_tcs_data, name="data"),
    path("<str:mode>/filters/", gst_tcs_filters, name="filters"),
]
