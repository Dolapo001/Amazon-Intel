from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from .models import TrendingProduct, CompetitorCluster, OpportunityScore
from .serializers import TrendingProductSerializer, CompetitorClusterSerializer, OpportunityScoreSerializer
from apps.products.models import ASIN

class TrendingProductsView(APIView):
    """
    GET /v1/analytics/trending
    Returns products with high momentum (Discovery Engine).
    """
    def get(self, request):
        trending = TrendingProduct.objects.filter(is_active=True)[:50]
        serializer = TrendingProductSerializer(trending, many=True)
        return Response(serializer.data)

class CompetitorClusterView(APIView):
    """
    GET /v1/analytics/competitors/<asin>
    Returns detected competitors for a specific ASIN.
    """
    def get(self, request, asin_code):
        cluster = get_object_or_404(CompetitorCluster, anchor_asin__asin=asin_code)
        serializer = CompetitorClusterSerializer(cluster)
        return Response(serializer.data)

class OpportunityScoreView(APIView):
    """
    GET /v1/analytics/opportunities
    Returns niche profitability and underserved scoring.
    """
    def get(self, request):
        scores = OpportunityScore.objects.all().order_by('-total_score')
        serializer = OpportunityScoreSerializer(scores, many=True)
        return Response(serializer.data)
