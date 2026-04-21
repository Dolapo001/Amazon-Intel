"""
Test suite for Amazon Intel API.

Covers:
  - ASIN/URL normalisation
  - BSR trend calculation
  - Revenue formula fallback
  - NLP theme extraction fallback
  - Cache hit/miss flow
  - API endpoint contracts
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import date, timedelta
from decimal import Decimal


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def category(db):
    from apps.products.models import Category
    return Category.objects.create(
        amazon_id="172282",
        name="Electronics",
        bsr_revenue_multiplier=1.5,
        seasonality_indices=[0.9, 0.85, 0.9, 0.95, 1.0, 1.0, 1.1, 1.1, 1.1, 1.2, 1.4, 1.5],
    )


@pytest.fixture
def asin(db, category):
    from apps.products.models import ASIN
    return ASIN.objects.create(
        asin="B09XYZ1234",
        title="Test Bluetooth Speaker",
        brand="TestBrand",
        category=category,
        current_bsr=1450,
        current_price=Decimal("39.99"),
        current_rating=4.2,
        current_review_count=3200,
        tier=ASIN.TIER_2,
    )


@pytest.fixture
def bsr_history(db, asin):
    """Create 400 days of BSR snapshots for YoY testing."""
    from apps.products.models import BSRSnapshot

    snapshots = []
    today = date.today()
    for i in range(400):
        d = today - timedelta(days=i)
        # Simulate improving BSR: 3000 a year ago → 1450 today
        rank = int(1450 + (3000 - 1450) * (i / 400))
        snapshots.append(BSRSnapshot(asin=asin, date=d, bsr_rank=rank))

    BSRSnapshot.objects.bulk_create(snapshots, ignore_conflicts=True)
    return snapshots


# ── Serializer / Input Validation ─────────────────────────────────────────────

class TestASINQuerySerializer:
    def test_valid_asin(self):
        from apps.products.serializers import ASINQuerySerializer
        s = ASINQuerySerializer(data={"asin": "B09XYZ1234"})
        assert s.is_valid(), s.errors
        assert s.validated_data["asin"] == "B09XYZ1234"

    def test_lowercase_asin_normalised(self):
        from apps.products.serializers import ASINQuerySerializer
        s = ASINQuerySerializer(data={"asin": "b09xyz1234"})
        assert s.is_valid()
        assert s.validated_data["asin"] == "B09XYZ1234"

    def test_amazon_url_extracted(self):
        from apps.products.serializers import ASINQuerySerializer
        url = "https://www.amazon.com/dp/B09XYZ1234/ref=sr_1_1"
        s = ASINQuerySerializer(data={"asin": url})
        assert s.is_valid(), s.errors
        assert s.validated_data["asin"] == "B09XYZ1234"

    def test_full_amazon_url_with_query_params(self):
        from apps.products.serializers import ASINQuerySerializer
        url = "https://www.amazon.com/Some-Product-Title/dp/B08ABCDE12?th=1&psc=1"
        s = ASINQuerySerializer(data={"asin": url})
        assert s.is_valid()
        assert s.validated_data["asin"] == "B08ABCDE12"

    def test_invalid_identifier_rejected(self):
        from apps.products.serializers import ASINQuerySerializer
        s = ASINQuerySerializer(data={"asin": "not-an-asin"})
        assert not s.is_valid()
        assert "asin" in s.errors

    def test_short_asin_rejected(self):
        from apps.products.serializers import ASINQuerySerializer
        s = ASINQuerySerializer(data={"asin": "B09XY"})
        assert not s.is_valid()


# ── BSR Trend Analytics ────────────────────────────────────────────────────────

class TestBSRTrend:
    @pytest.mark.django_db
    def test_trend_improving(self, asin, bsr_history):
        from apps.analytics.bsr import compute_bsr_trend
        result = compute_bsr_trend(asin)

        assert result["currentRank"] == 1450
        assert result["trend"] == "improving"
        assert result["yoyChange"] < 0   # rank went down = improved

    @pytest.mark.django_db
    def test_history_length(self, asin, bsr_history):
        from apps.analytics.bsr import compute_bsr_trend
        result = compute_bsr_trend(asin)
        # Should have ~90 data points for the 90-day window
        assert len(result["history"]) <= 90
        assert len(result["history"]) > 0

    @pytest.mark.django_db
    def test_no_history_returns_stable(self, asin):
        from apps.analytics.bsr import compute_bsr_trend
        result = compute_bsr_trend(asin)
        assert result["trend"] == "stable"
        assert result["yoyChange"] is None

    def test_classify_trend_improving(self):
        from apps.analytics.bsr import _classify_trend
        assert _classify_trend(-500, 2000) == "improving"   # 25% better

    def test_classify_trend_declining(self):
        from apps.analytics.bsr import _classify_trend
        assert _classify_trend(500, 2000) == "declining"    # 25% worse

    def test_classify_trend_stable(self):
        from apps.analytics.bsr import _classify_trend
        assert _classify_trend(100, 2000) == "stable"       # 5% — within band


# ── Revenue Estimation ─────────────────────────────────────────────────────────

class TestRevenue:
    @pytest.mark.django_db
    def test_formula_fallback_produces_positive_revenue(self, asin):
        from apps.analytics.revenue import _formula_estimate
        revenue, confidence = _formula_estimate(asin)
        assert revenue > 0
        assert 0 < confidence <= 1.0

    @pytest.mark.django_db
    def test_formula_uses_category_multiplier(self, asin, category):
        from apps.analytics.revenue import _formula_estimate
        # multiplier=1.5 → should give 1.5× more revenue than multiplier=1.0
        category.bsr_revenue_multiplier = 1.0
        category.save()
        rev_base, _ = _formula_estimate(asin)

        category.bsr_revenue_multiplier = 1.5
        category.save()
        asin.refresh_from_db()
        rev_scaled, _ = _formula_estimate(asin)

        assert abs(rev_scaled / rev_base - 1.5) < 0.01

    @pytest.mark.django_db
    def test_seasonality_applied(self, asin, category):
        from apps.analytics.revenue import _apply_seasonality
        base = 10_000.0
        # Set current month index to 1.5
        import datetime
        month_idx = datetime.date.today().month - 1
        indices = [1.0] * 12
        indices[month_idx] = 1.5
        category.seasonality_indices = indices
        category.save()
        asin.refresh_from_db()
        result = _apply_seasonality(asin, base)
        assert abs(result - 15_000.0) < 0.01

    @pytest.mark.django_db
    def test_zero_bsr_returns_zero(self, asin):
        from apps.analytics.revenue import _formula_estimate
        asin.current_bsr = None
        asin.save()
        revenue, confidence = _formula_estimate(asin)
        assert revenue == 0.0
        assert confidence == 0.0


# ── NLP ───────────────────────────────────────────────────────────────────────

class TestNLP:
    def test_frequency_fallback(self):
        from apps.analytics.nlp import _frequency_themes
        text = "battery life is great battery charge lasts long durability issue packaging bad"
        themes = _frequency_themes(text, top_n=3)
        assert "battery" in themes
        assert len(themes) <= 3

    def test_clean_text_strips_html(self):
        from apps.analytics.nlp import _clean_text
        dirty = "<p>Great <b>product</b>!</p>"
        assert "<" not in _clean_text(dirty)
        assert "Great" in _clean_text(dirty)

    def test_filter_by_rating(self):
        from apps.analytics.nlp import _filter_by_rating
        reviews = [{"text": "good", "rating": 5}, {"text": "bad", "rating": 1}, {"text": "ok", "rating": 3}]
        positive = _filter_by_rating(reviews, min_rating=4)
        negative = _filter_by_rating(reviews, max_rating=2)
        assert len(positive) == 1
        assert len(negative) == 1

    @pytest.mark.django_db
    def test_empty_reviews_saves_empty_analysis(self, asin):
        from apps.analytics.nlp import analyse_and_persist
        ra = analyse_and_persist(asin, [])
        assert ra.sentiment_score == 0.0
        assert ra.total_reviews_analysed == 0


# ── Cache ─────────────────────────────────────────────────────────────────────

class TestCache:
    def test_set_and_get_roundtrip(self):
        from apps.products.cache import get_cached_intel, set_cached_intel, invalidate_intel
        from unittest.mock import patch

        payload = {"asin": "B09XYZ1234", "title": "Test"}
        with patch("apps.products.cache.cache") as mock_cache:
            mock_cache.get.return_value = None
            assert get_cached_intel("B09XYZ1234") is None

            set_cached_intel("B09XYZ1234", payload, tier=2)
            mock_cache.set.assert_called_once()

            # PRD §10: Mid-traffic tier → 3 days
            call_args = mock_cache.set.call_args
            assert call_args[1]["timeout"] == 3 * 24 * 3600

    def test_tier1_ttl_is_24h(self):
        """PRD §10: Popular tier → 24 hours."""
        from apps.products.cache import _TTL
        from apps.products.models import ASIN
        assert _TTL[ASIN.TIER_1] == 24 * 3600

    def test_tier2_ttl_is_3d(self):
        """PRD §10: Mid-traffic tier → 3 days."""
        from apps.products.cache import _TTL
        from apps.products.models import ASIN
        assert _TTL[ASIN.TIER_2] == 3 * 24 * 3600

    def test_tier3_ttl_is_7d(self):
        """PRD §10: Long tail → 7 days."""
        from apps.products.cache import _TTL
        from apps.products.models import ASIN
        assert _TTL[ASIN.TIER_3] == 7 * 24 * 3600

    def test_invalidate_calls_delete(self):
        from apps.products.cache import invalidate_intel
        from unittest.mock import patch
        with patch("apps.products.cache.cache") as mock_cache:
            invalidate_intel("B09XYZ1234")
            mock_cache.delete.assert_called_once_with("asin_intel:B09XYZ1234")


# ── API endpoint ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestIntelEndpoint:
    def test_unknown_asin_returns_202(self, client):
        # PRD §3.1: POST /v1/product/intelligence with {"asin": "..."}
        with patch("apps.products.views.enqueue_asin_refresh") as mock_task:
            mock_task.delay = MagicMock()
            resp = client.post(
                "/v1/product/intelligence",
                data={"asin": "B00UNKNOWN1"},
                content_type="application/json",
            )
        assert resp.status_code == 202
        assert resp.json()["status"] == "queued"

    def test_invalid_asin_returns_400(self, client):
        resp = client.post(
            "/v1/product/intelligence",
            data={"asin": "not-valid"},
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "asin" in resp.json()

    def test_missing_asin_key_returns_400(self, client):
        resp = client.post(
            "/v1/product/intelligence",
            data={"identifier": "B09XYZ1234"},   # old field name — should 400
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_health_endpoint(self, client):
        with patch("apps.products.views.connection") as mock_conn, \
             patch("apps.products.views.get_redis_connection") as mock_redis:
            mock_conn.ensure_connection = MagicMock()
            mock_redis.return_value.ping = MagicMock()
            resp = client.get("/v1/product/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"


class TestApifyClient:
    """Smoke tests for the Apify scraper module."""

    def test_parse_product_bsr_as_int(self):
        from apps.ingestion.scraper import _parse_product
        item = {
            "asin": "B09XYZ1234",
            "title": "Test Speaker",
            "brand": "TestBrand",
            "salesRank": 1450,
            "price": 39.99,
            "stars": 4.2,
            "reviewsCount": 3200,
            "thumbnailImage": "https://example.com/img.jpg",
            "breadCrumbs": ["Electronics"],
        }
        result = _parse_product(item, "B09XYZ1234")
        assert result["current_bsr"] == 1450
        assert result["current_price"] == 39.99
        assert result["current_rating"] == 4.2
        assert result["bsr_series"] == []   # Apify gives no history

    def test_parse_product_bsr_as_dict(self):
        from apps.ingestion.scraper import _parse_product
        item = {"asin": "B09XYZ1234", "bestSellersRank": {"rank": 2200}, "price": 19.99}
        result = _parse_product(item, "B09XYZ1234")
        assert result["current_bsr"] == 2200

    def test_parse_review_normalises_rating(self):
        from apps.ingestion.scraper import _parse_review
        item = {"text": "Great product!", "rating": "4.0 out of 5 stars", "isVerified": True}
        result = _parse_review(item)
        assert result["rating"] == 4
        assert result["verified"] is True

    def test_parse_price_str(self):
        from apps.ingestion.scraper import _parse_price_str
        assert _parse_price_str("$39.99") == 39.99
        assert _parse_price_str("29") == 29.0
        assert _parse_price_str("invalid") is None


class TestRainforestClient:
    """Smoke tests for the Rainforest API parser."""

    def test_parse_product_bsr_as_list(self):
        from apps.ingestion.rainforest import _parse_product
        item = {
            "asin": "B09XYZ1234",
            "title": "Test Speaker",
            "brand": "TestBrand",
            "bestsellers_rank": [{"rank": 1450, "category": "Electronics"}],
            "price": {"value": 39.99, "currency": "USD"},
            "rating": 4.2,
            "ratings_total": 3200,
            "main_image": {"link": "https://example.com/img.jpg"},
            "categories": [{"name": "Electronics"}],
        }
        result = _parse_product(item)
        assert result["asin"] == "B09XYZ1234"
        assert result["current_bsr"] == 1450
        assert result["current_price"] == 39.99
        assert result["current_rating"] == 4.2
        assert result["current_review_count"] == 3200
        assert result["category_id"] == "electronics"

    def test_parse_review_normalises_rating(self):
        from apps.ingestion.rainforest import _parse_review
        item = {
            "body": "Great product!",
            "rating": 4,
            "verified_purchase": True,
            "date": {"utc": "2023-01-01T12:00:00Z"}
        }
        result = _parse_review(item)
        assert result["rating"] == 4
        assert result["verified"] is True
        assert "2023-01-01" in result["date"]
