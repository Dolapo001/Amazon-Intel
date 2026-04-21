from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.products.models import ASIN

from .models import CompetitorCluster, OpportunityScore, TrendingProduct
from .serializers import (
    CompetitorClusterSerializer,
    OpportunityScoreSerializer,
    TrendingProductSerializer,
)


def _parse_limit(request, default: int, maximum: int) -> int:
    try:
        value = int(request.query_params.get("limit", default))
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


class TrendingProductsView(APIView):
    """GET /v1/analytics/trending/ — products with high momentum (Discovery Engine)."""

    def get(self, request):
        limit = _parse_limit(request, default=10, maximum=50)
        qs = TrendingProduct.objects.filter(is_active=True).select_related("asin")

        category = request.query_params.get("category")
        if category:
            qs = qs.filter(asin__category__amazon_id=category)

        qs = qs[:limit]
        trending = [
            {
                "asin": t.asin.asin,
                "title": t.asin.title,
                "velocity_score": t.velocity_score,
                "improvement_pct": t.bsr_change_pct,
                "current_bsr": t.asin.current_bsr,
            }
            for t in qs
        ]
        return Response({
            "trending": trending,
            "total_count": len(trending),
            "timestamp": timezone.now().isoformat(),
        })


class CompetitorClusterView(APIView):
    """GET /v1/analytics/competitors/<asin>/ — detected competitors for a specific ASIN."""

    def get(self, request, asin_code):
        cluster = get_object_or_404(CompetitorCluster, anchor_asin__asin=asin_code)
        serializer = CompetitorClusterSerializer(cluster)
        return Response(serializer.data)


class OpportunityScoreView(APIView):
    """GET /v1/analytics/opportunities/ — niche profitability + saturation scoring."""

    def get(self, request):
        limit = _parse_limit(request, default=10, maximum=50)
        scores = OpportunityScore.objects.select_related("category").order_by("-total_score")[:limit]
        opportunities = [
            {
                "niche": s.niche_name or (s.category.name if s.category else ""),
                "opportunity_score": s.total_score,
                "profitability": s.profitability_index,
                "competition_index": s.competition_index,
                "demand_growth_pct": s.demand_growth_pct,
                "recommendation": s.recommendation,
            }
            for s in scores
        ]
        return Response({
            "opportunities": opportunities,
            "total_count": len(opportunities),
            "timestamp": timezone.now().isoformat(),
        })
