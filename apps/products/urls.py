"""URL patterns for the products app."""
from django.urls import path
from .views import ProductIntelligenceView, HealthCheckView

urlpatterns = [
    # POST /v1/product/intelligence
    path("intelligence", ProductIntelligenceView.as_view(), name="product-intelligence"),
    # GET  /v1/product/health
    path("health", HealthCheckView.as_view(), name="health"),
]
