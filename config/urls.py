"""Root URL configuration."""
from django.urls import path, include

urlpatterns = [
    path("v1/product/", include("apps.products.urls")),
    path("v1/analytics/", include("apps.analytics.urls")),
]
