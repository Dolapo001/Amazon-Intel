"""
API views.

POST /v1/product/intelligence  — primary query endpoint  (PRD §3.1)
GET  /v1/product/health        — liveness probe
"""
import logging
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .serializers import ASINQuerySerializer, ProductIntelligenceSerializer
from .models import ASIN, RevenueEstimate, ReviewAnalysis
from apps.analytics.bsr import compute_bsr_trend
from apps.analytics.revenue import build_revenue_payload
from apps.analytics.nlp import get_review_analysis
from apps.ingestion.tasks import enqueue_asin_refresh
from .cache import get_cached_intel, set_cached_intel, invalidate_intel

logger = logging.getLogger(__name__)


class ProductIntelligenceView(APIView):
    """
    PRD §3.1 — Product Intelligence Query.

    POST /v1/product/intelligence
    Request:  { "asin": "B09XYZ123" }   (also accepts Amazon product URL)
    Response: structured intelligence JSON — estimatedRevenue, sentiment, bsrTrend.

    Resolution order:
      1. Redis L1 cache  → return instantly if fresh
      2. Postgres DB     → assemble from stored analytics
      3. Unknown ASIN    → trigger async ingest, return 202 + "queued"

    Target latency: < 500 ms (PRD §3.1 Performance Requirements).
    """

    def post(self, request):
        # ── 1. Input validation ────────────────────────────────────────────
        serializer = ASINQuerySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        asin_code = serializer.validated_data["asin"]

        # ── 2. L1 cache (Redis) ────────────────────────────────────────────
        cached = get_cached_intel(asin_code)
        if cached:
            cached["cacheHit"] = True
            logger.info("cache_hit", extra={"asin": asin_code})
            return Response(cached)

        # ── 3. DB lookup & assembly ────────────────────────────────────────
        try:
            asin_obj = ASIN.objects.select_related(
                "category", "revenue_estimate", "review_analysis"
            ).get(asin=asin_code)
        except ASIN.DoesNotExist:
            # NEW ASIN: clear any stale placeholder cache, then do synchronous ingest
            invalidate_intel(asin_code)
            logger.info("new_asin_sync_ingest_start", extra={"asin": asin_code})
            from apps.ingestion.tasks import synchronous_full_ingest
            try:
                # This will block but concurrent_fetch makes it fast (~5s usually)
                asin_obj = synchronous_full_ingest(asin_code)
                logger.info("new_asin_sync_ingest_complete", extra={"asin": asin_code})
            except Exception:
                logger.exception("sync_ingest_failed", extra={"asin": asin_code})
                return Response(
                    {"error": f"Failed to fetch data for ASIN {asin_code}. Please verify the ASIN and try again."},
                    status=status.HTTP_404_NOT_FOUND
                )
        
        # Increment query counter and promote tier if warranted
        ASIN.objects.filter(pk=asin_obj.pk).update(query_count=asin_obj.query_count + 1)
        asin_obj.query_count += 1
        asin_obj.promote_tier()

        # ── 4. Stale-data guard / Refresh ──────────────────────────────────
        is_stale = self._is_stale(asin_obj)
        if is_stale:
            # Refresh in background, never block
            enqueue_asin_refresh.delay(asin_code, priority="normal")

        # ── 5. Assemble payload ────────────────────────────────────────────
        try:
            payload = self._assemble_payload(asin_obj, cache_hit=False)
        except Exception as exc:
            logger.exception("payload_assembly_failed", extra={"asin": asin_code, "error": str(exc)})
            return Response(
                {"error": "Intelligence data temporarily unavailable. Please retry."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Only cache if real data was ingested — never cache placeholder/incomplete payloads
        if asin_obj.last_ingested_at:
            set_cached_intel(asin_code, payload, tier=asin_obj.tier)

        return Response(payload)

    # ── Helpers ────────────────────────────────────────────────────────────

    def _is_stale(self, asin_obj: ASIN) -> bool:
        """Return True if the ASIN data needs a background refresh or if data is incomplete."""
        from datetime import timedelta
        from django.conf import settings

        if not asin_obj.last_ingested_at:
            return True

        # PRD REQUIREMENT: "Response must always return complete fields"
        # If record exists but is missing analytics, consider it stale/incomplete.
        try:
            asin_obj.review_analysis
            asin_obj.revenue_estimate
        except (ReviewAnalysis.DoesNotExist, RevenueEstimate.DoesNotExist):
            return True

        ttl_map = {
            ASIN.TIER_1: timedelta(hours=6),
            ASIN.TIER_2: timedelta(hours=24),
            ASIN.TIER_3: timedelta(days=7),
        }
        max_age = ttl_map.get(asin_obj.tier, timedelta(hours=24))
        return (timezone.now() - asin_obj.last_ingested_at) > max_age

    def _assemble_payload(self, asin_obj: ASIN, cache_hit: bool) -> dict:
        revenue_payload = build_revenue_payload(asin_obj)
        bsr_trend = compute_bsr_trend(asin_obj)
        sentiment = get_review_analysis(asin_obj)

        return {
            "asin": asin_obj.asin,
            "title": asin_obj.title,
            "brand": asin_obj.brand,
            "category": asin_obj.category.name if asin_obj.category else None,
            "estimatedRevenue": {
                "monthly": int(revenue_payload.get("monthly", 0)),
                "yoyChange": revenue_payload.get("yoyChange"),
                "confidence": revenue_payload.get("confidence"),
            },
            "sentiment": {
                "score": sentiment.get("score"),
                "positiveThemes": sentiment.get("positiveThemes", []),
                "negativeThemes": sentiment.get("negativeThemes", []),
            },
            "bsrTrend": {
                "currentRank": bsr_trend.get("currentRank"),
                "yoyChange": bsr_trend.get("yoyChange"),
                "trend": bsr_trend.get("trend"),
            },
            "reviews": {
                "count": asin_obj.current_review_count,
                "velocity": sentiment.get("reviewVelocity"),
            },
            "cacheHit": cache_hit
        }

    def _generate_summary(self, revenue: dict, sentiment: dict, bsr: dict) -> str:
        """
        Rule-based natural language summary.
        Example: "Estimated Revenue: $47K/mo (up 23%); Sentiment: 4.2/5,
                  top complaints: durability; BSR Trends: Improving in Q4."
        """
        monthly = revenue.get("monthly", 0) or 0
        yoy = revenue.get("yoyChange")
        score = sentiment.get("score") or 0
        neg_themes = sentiment.get("negativeThemes", [])
        trend = bsr.get("trend", "stable") or "stable"

        rev_str = f"${monthly:,.0f}/mo"
        if yoy is not None:
            direction = "up" if yoy >= 0 else "down"
            rev_str += f" ({direction} {abs(yoy):.0f}%)"

        complaints_str = ""
        if neg_themes:
            complaints_str = f", top complaints: {', '.join(neg_themes[:2])}"

        return (
            f"Estimated Revenue: {rev_str}; "
            f"Sentiment: {score:.1f}/5{complaints_str}; "
            f"BSR Trend: {trend.capitalize()}."
        )


class HealthCheckView(APIView):
    """Liveness probe — used by load balancers and Kubernetes."""

    def get(self, request):
        from django.db import connection
        from django_redis import get_redis_connection

        checks = {}

        try:
            connection.ensure_connection()
            checks["postgres"] = "ok"
        except Exception as e:
            checks["postgres"] = f"error: {e}"

        try:
            redis = get_redis_connection("default")
            redis.ping()
            checks["redis"] = "ok"
        except Exception as e:
            checks["redis"] = f"error: {e}"

        healthy = all(v == "ok" for v in checks.values())
        return Response(
            {"status": "healthy" if healthy else "degraded", "checks": checks},
            status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        )
