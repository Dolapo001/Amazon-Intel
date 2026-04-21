"""URL patterns for the products app."""
from django.urls import path

from .views import BSRHistoryView, HealthCheckView, ProductIntelligenceView

urlpatterns = [
    # POST /v1/product/intelligence
    path("intelligence", ProductIntelligenceView.as_view(), name="product-intelligence"),
    # GET  /v1/product/<asin>/bsr-history/
    path("<str:asin_code>/bsr-history/", BSRHistoryView.as_view(), name="product-bsr-history"),
    # GET  /v1/product/health
    path("health", HealthCheckView.as_view(), name="health"),
]
