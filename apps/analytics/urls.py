from django.urls import path
from .views import TrendingProductsView, CompetitorClusterView, OpportunityScoreView

app_name = "analytics"

urlpatterns = [
    path("trending/", TrendingProductsView.as_view(), name="trending"),
    path("competitors/<str:asin_code>/", CompetitorClusterView.as_view(), name="competitors"),
    path("opportunities/", OpportunityScoreView.as_view(), name="opportunities"),
]
