"""Root URL configuration."""
from django.urls import include, path

urlpatterns = [
    path("v1/product/", include("apps.products.urls")),
    path("v1/analytics/", include("apps.analytics.urls")),
    path("v1/catalog/", include("apps.products.catalog_urls")),
]
