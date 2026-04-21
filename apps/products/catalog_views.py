"""
Catalog endpoints — expose the full category surface area for MCP discovery.

GET /v1/catalog/categories/
GET /v1/catalog/categories/<category_id>/items/
"""
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ASIN, Category


def _parse_limit(request, default: int, maximum: int) -> int:
    try:
        value = int(request.query_params.get("limit", default))
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


class CategoryListView(APIView):
    """List all Amazon categories known to the index."""

    def get(self, request):
        limit = _parse_limit(request, default=100, maximum=500)
        qs = Category.objects.order_by("name")[:limit]
        categories = [
            {"id": c.amazon_id, "name": c.name, "slug": c.amazon_id}
            for c in qs
        ]
        return Response({
            "categories": categories,
            "total_count": len(categories),
            "timestamp": timezone.now().isoformat(),
        })


class CategoryItemsView(APIView):
    """List ASINs in a specific category, ordered by current BSR."""

    def get(self, request, category_id: str):
        try:
            category = Category.objects.get(amazon_id=category_id)
        except Category.DoesNotExist:
            return Response(
                {"error": f"Unknown category '{category_id}'."},
                status=status.HTTP_404_NOT_FOUND,
            )

        limit = _parse_limit(request, default=25, maximum=100)
        qs = (
            ASIN.objects
            .filter(category=category)
            .exclude(current_bsr__isnull=True)
            .order_by("current_bsr")[:limit]
        )
        items = [
            {
                "asin": a.asin,
                "title": a.title,
                "current_bsr": a.current_bsr,
                "current_price": float(a.current_price) if a.current_price is not None else None,
                "current_rating": a.current_rating,
            }
            for a in qs
        ]
        return Response({
            "category_id": category_id,
            "items": items,
            "total_count": len(items),
            "timestamp": timezone.now().isoformat(),
        })
