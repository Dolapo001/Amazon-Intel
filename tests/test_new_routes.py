"""
Tests for routes introduced in the Context Protocol MCP audit:

  - GET /v1/catalog/categories/
  - GET /v1/catalog/categories/<id>/items/
  - GET /v1/product/<asin>/bsr-history/
  - GET /v1/analytics/trending/         (envelope shape)
  - GET /v1/analytics/opportunities/    (envelope shape)
  - POST /v1/product/intelligence       (curated_summary, data_freshness)
"""
import pytest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch


# ── Shared fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def category(db):
    from apps.products.models import Category
    return Category.objects.create(
        amazon_id="electronics",
        name="Electronics",
        bsr_revenue_multiplier=1.5,
        seasonality_indices=[1.0] * 12,
    )


@pytest.fixture
def category_b(db):
    from apps.products.models import Category
    return Category.objects.create(
        amazon_id="home-kitchen",
        name="Home & Kitchen",
        bsr_revenue_multiplier=1.0,
        seasonality_indices=[1.0] * 12,
    )


@pytest.fixture
def asin(db, category):
    from apps.products.models import ASIN
    from django.utils import timezone as tz
    return ASIN.objects.create(
        asin="B09XYZ1234",
        title="Test Bluetooth Speaker",
        brand="TestBrand",
        category=category,
        current_bsr=1450,
        current_price=Decimal("39.99"),
        current_rating=4.2,
        current_review_count=3200,
        tier=2,
        last_ingested_at=tz.now() - timedelta(hours=2),
    )


@pytest.fixture
def asin_no_bsr(db, category):
    from apps.products.models import ASIN
    return ASIN.objects.create(
        asin="B00NOBSR111",
        title="No BSR Product",
        brand="NoBrand",
        category=category,
        current_bsr=None,
        tier=3,
    )


@pytest.fixture
def bsr_snapshots(db, asin):
    from apps.products.models import BSRSnapshot
    today = date.today()
    rows = [
        BSRSnapshot(asin=asin, date=today - timedelta(days=i), bsr_rank=1450 + i * 10)
        for i in range(30)
    ]
    BSRSnapshot.objects.bulk_create(rows, ignore_conflicts=True)
    return rows


@pytest.fixture
def trending_product(db, asin):
    from apps.analytics.models import TrendingProduct
    return TrendingProduct.objects.create(
        asin=asin,
        bsr_change_pct=25.0,
        velocity_score=88.5,
        is_active=True,
    )


@pytest.fixture
def opportunity(db, category):
    from apps.analytics.models import OpportunityScore
    return OpportunityScore.objects.create(
        category=category,
        niche_name="Wireless Ergonomic Keyboards",
        total_score=82.0,
        profitability_index=76.5,
        competition_index=60.0,
        demand_growth_pct=14.2,
        recommendation="High upside — low review count in top 20.",
    )


# ── Catalog: GET /v1/catalog/categories/ ────────────────────────────────────

@pytest.mark.django_db
class TestCategoryListView:
    def test_returns_envelope(self, client, category):
        resp = client.get("/v1/catalog/categories/")
        assert resp.status_code == 200
        data = resp.json()
        assert "categories" in data
        assert "total_count" in data
        assert "timestamp" in data

    def test_category_shape(self, client, category):
        resp = client.get("/v1/catalog/categories/")
        cats = resp.json()["categories"]
        assert len(cats) >= 1
        first = cats[0]
        assert first["id"] == "electronics"
        assert first["name"] == "Electronics"
        assert "slug" in first

    def test_limit_param(self, client, category, category_b):
        resp = client.get("/v1/catalog/categories/?limit=1")
        assert resp.status_code == 200
        assert len(resp.json()["categories"]) == 1

    def test_limit_below_one_clamped(self, client, category):
        resp = client.get("/v1/catalog/categories/?limit=0")
        assert resp.status_code == 200
        assert len(resp.json()["categories"]) >= 1

    def test_limit_invalid_uses_default(self, client, category):
        resp = client.get("/v1/catalog/categories/?limit=abc")
        assert resp.status_code == 200

    def test_ordered_alphabetically(self, client, category, category_b):
        resp = client.get("/v1/catalog/categories/")
        names = [c["name"] for c in resp.json()["categories"]]
        assert names == sorted(names)

    def test_empty_db_returns_zero(self, client, db):
        resp = client.get("/v1/catalog/categories/")
        assert resp.status_code == 200
        assert resp.json()["total_count"] == 0


# ── Catalog: GET /v1/catalog/categories/<id>/items/ ─────────────────────────

@pytest.mark.django_db
class TestCategoryItemsView:
    def test_returns_envelope(self, client, category, asin):
        resp = client.get("/v1/catalog/categories/electronics/items/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["category_id"] == "electronics"
        assert "items" in data
        assert "total_count" in data
        assert "timestamp" in data

    def test_unknown_category_404(self, client, db):
        resp = client.get("/v1/catalog/categories/does-not-exist/items/")
        assert resp.status_code == 404
        assert "error" in resp.json()

    def test_item_shape(self, client, category, asin):
        resp = client.get("/v1/catalog/categories/electronics/items/")
        items = resp.json()["items"]
        assert len(items) == 1
        item = items[0]
        assert item["asin"] == "B09XYZ1234"
        assert item["current_bsr"] == 1450
        assert item["current_price"] == 39.99
        assert item["current_rating"] == 4.2

    def test_no_bsr_items_excluded(self, client, category, asin, asin_no_bsr):
        resp = client.get("/v1/catalog/categories/electronics/items/")
        asins_returned = {i["asin"] for i in resp.json()["items"]}
        assert "B00NOBSR111" not in asins_returned

    def test_items_ordered_by_bsr(self, client, category):
        from apps.products.models import ASIN
        ASIN.objects.create(asin="B00RANK00A1", category=category, current_bsr=500, tier=2)
        ASIN.objects.create(asin="B00RANK00B2", category=category, current_bsr=200, tier=2)
        ASIN.objects.create(asin="B00RANK00C3", category=category, current_bsr=800, tier=2)
        resp = client.get("/v1/catalog/categories/electronics/items/")
        ranks = [i["current_bsr"] for i in resp.json()["items"]]
        assert ranks == sorted(ranks)

    def test_limit_param(self, client, category):
        from apps.products.models import ASIN
        for i in range(5):
            ASIN.objects.create(asin=f"B00LIMIT{i:04}", category=category, current_bsr=i + 1, tier=3)
        resp = client.get("/v1/catalog/categories/electronics/items/?limit=2")
        assert len(resp.json()["items"]) == 2


# ── BSR History: GET /v1/product/<asin>/bsr-history/ ────────────────────────

@pytest.mark.django_db
class TestBSRHistoryView:
    def test_returns_envelope(self, client, asin, bsr_snapshots):
        resp = client.get("/v1/product/B09XYZ1234/bsr-history/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["asin"] == "B09XYZ1234"
        assert "snapshots" in data
        assert "days" in data
        assert "timestamp" in data

    def test_snapshot_shape(self, client, asin, bsr_snapshots):
        resp = client.get("/v1/product/B09XYZ1234/bsr-history/")
        snapshots = resp.json()["snapshots"]
        assert len(snapshots) > 0
        snap = snapshots[0]
        assert "date" in snap
        assert "bsr" in snap
        assert "price" in snap

    def test_snapshot_count_matches_days(self, client, asin, bsr_snapshots):
        resp = client.get("/v1/product/B09XYZ1234/bsr-history/?days=30")
        data = resp.json()
        assert data["days"] == 30
        assert len(data["snapshots"]) <= 30

    def test_days_default_is_90(self, client, asin, bsr_snapshots):
        resp = client.get("/v1/product/B09XYZ1234/bsr-history/")
        assert resp.json()["days"] == 90

    def test_unknown_asin_returns_404(self, client, db):
        resp = client.get("/v1/product/B00UNKNOWN1/bsr-history/")
        assert resp.status_code == 404
        assert "error" in resp.json()

    def test_asin_normalised_to_uppercase(self, client, asin, bsr_snapshots):
        resp = client.get("/v1/product/b09xyz1234/bsr-history/")
        assert resp.status_code == 200
        assert resp.json()["asin"] == "B09XYZ1234"

    def test_days_clamped_max(self, client, asin):
        resp = client.get("/v1/product/B09XYZ1234/bsr-history/?days=99999")
        assert resp.json()["days"] == 730

    def test_days_clamped_min(self, client, asin):
        resp = client.get("/v1/product/B09XYZ1234/bsr-history/?days=0")
        assert resp.json()["days"] == 1

    def test_snapshots_ordered_asc_by_date(self, client, asin, bsr_snapshots):
        resp = client.get("/v1/product/B09XYZ1234/bsr-history/")
        dates = [s["date"] for s in resp.json()["snapshots"]]
        assert dates == sorted(dates)


# ── Trending: GET /v1/analytics/trending/ ───────────────────────────────────

@pytest.mark.django_db
class TestTrendingView:
    def test_returns_envelope(self, client, trending_product):
        resp = client.get("/v1/analytics/trending/")
        assert resp.status_code == 200
        data = resp.json()
        assert "trending" in data
        assert "total_count" in data
        assert "timestamp" in data

    def test_item_shape(self, client, trending_product):
        items = client.get("/v1/analytics/trending/").json()["trending"]
        assert len(items) == 1
        item = items[0]
        assert item["asin"] == "B09XYZ1234"
        assert item["velocity_score"] == 88.5
        assert item["improvement_pct"] == 25.0
        assert item["current_bsr"] == 1450

    def test_inactive_excluded(self, client, db, asin, category):
        from apps.analytics.models import TrendingProduct
        TrendingProduct.objects.create(asin=asin, bsr_change_pct=10.0, velocity_score=50.0, is_active=False)
        resp = client.get("/v1/analytics/trending/")
        assert resp.json()["total_count"] == 0

    def test_limit_param(self, client, db, category):
        from apps.products.models import ASIN
        from apps.analytics.models import TrendingProduct
        for i in range(5):
            a = ASIN.objects.create(asin=f"B00TRND{i:05}", category=category, current_bsr=i + 1, tier=3)
            TrendingProduct.objects.create(asin=a, bsr_change_pct=10.0, velocity_score=float(50 + i), is_active=True)
        resp = client.get("/v1/analytics/trending/?limit=2")
        assert len(resp.json()["trending"]) == 2

    def test_category_filter(self, client, db, category, category_b):
        from apps.products.models import ASIN
        from apps.analytics.models import TrendingProduct
        a1 = ASIN.objects.create(asin="B00CATFLT01", category=category, current_bsr=100, tier=3)
        a2 = ASIN.objects.create(asin="B00CATFLT02", category=category_b, current_bsr=200, tier=3)
        TrendingProduct.objects.create(asin=a1, bsr_change_pct=10.0, velocity_score=70.0, is_active=True)
        TrendingProduct.objects.create(asin=a2, bsr_change_pct=10.0, velocity_score=70.0, is_active=True)
        resp = client.get("/v1/analytics/trending/?category=electronics")
        asins = {i["asin"] for i in resp.json()["trending"]}
        assert "B00CATFLT01" in asins
        assert "B00CATFLT02" not in asins


# ── Opportunities: GET /v1/analytics/opportunities/ ─────────────────────────

@pytest.mark.django_db
class TestOpportunitiesView:
    def test_returns_envelope(self, client, opportunity):
        resp = client.get("/v1/analytics/opportunities/")
        assert resp.status_code == 200
        data = resp.json()
        assert "opportunities" in data
        assert "total_count" in data
        assert "timestamp" in data

    def test_item_shape(self, client, opportunity):
        items = client.get("/v1/analytics/opportunities/").json()["opportunities"]
        assert len(items) == 1
        item = items[0]
        assert item["niche"] == "Wireless Ergonomic Keyboards"
        assert item["opportunity_score"] == 82.0
        assert item["profitability"] == 76.5
        assert item["demand_growth_pct"] == 14.2
        assert "recommendation" in item

    def test_ordered_by_score_desc(self, client, db, category):
        from apps.analytics.models import OpportunityScore
        OpportunityScore.objects.create(category=category, niche_name="A", total_score=90.0, profitability_index=80.0, competition_index=50.0, recommendation="x")
        OpportunityScore.objects.create(category=category, niche_name="B", total_score=40.0, profitability_index=30.0, competition_index=20.0, recommendation="y")
        resp = client.get("/v1/analytics/opportunities/")
        scores = [o["opportunity_score"] for o in resp.json()["opportunities"]]
        assert scores == sorted(scores, reverse=True)

    def test_limit_param(self, client, db, category):
        from apps.analytics.models import OpportunityScore
        for i in range(5):
            OpportunityScore.objects.create(category=category, niche_name=f"Niche {i}", total_score=float(i * 10), profitability_index=50.0, competition_index=30.0, recommendation="ok")
        resp = client.get("/v1/analytics/opportunities/?limit=2")
        assert len(resp.json()["opportunities"]) == 2


# ── Intelligence response: curated_summary and data_freshness ───────────────

@pytest.mark.django_db
class TestIntelligenceResponseFields:
    def _post_intel(self, client, asin_code="B09XYZ1234"):
        return client.post(
            "/v1/product/intelligence",
            data={"asin": asin_code},
            content_type="application/json",
        )

    def _mock_analytics(self):
        return (
            patch("apps.products.views.build_revenue_payload", return_value={
                "monthly": 45000, "yoyChange": 18.5, "confidence": 0.82,
            }),
            patch("apps.products.views.compute_bsr_trend", return_value={
                "currentRank": 1450, "yoyChange": -600, "yoyChangePct": -29.3, "trend": "improving", "history": [],
            }),
            patch("apps.products.views.get_review_analysis", return_value={
                "score": 4.3, "positiveThemes": ["sound quality", "battery"], "negativeThemes": ["price"],
                "reviewVelocity": 12.5,
            }),
            patch("apps.products.views.get_cached_intel", return_value=None),
            patch("apps.products.views.set_cached_intel"),
        )

    def test_curated_summary_present(self, client, asin):
        patches = self._mock_analytics()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = self._post_intel(client)
        assert resp.status_code == 200
        assert "curated_summary" in resp.json()
        assert len(resp.json()["curated_summary"]) > 0

    def test_data_freshness_near_real_time(self, client, asin):
        patches = self._mock_analytics()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = self._post_intel(client)
        assert resp.status_code == 200
        assert resp.json()["data_freshness"] == "near-real-time"

    def test_data_freshness_stale_when_never_ingested(self, client, db, category):
        from apps.products.models import ASIN
        ASIN.objects.create(
            asin="B00STALE0001", category=category, current_bsr=999, tier=3, last_ingested_at=None,
        )
        patches = self._mock_analytics()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = self._post_intel(client, "B00STALE0001")
        assert resp.status_code == 200
        assert resp.json()["data_freshness"] == "stale"

    def test_data_freshness_real_time(self, client, db, category):
        from apps.products.models import ASIN
        from django.utils import timezone as tz
        ASIN.objects.create(
            asin="B00FRESH0001", category=category, current_bsr=100, tier=1,
            last_ingested_at=tz.now() - timedelta(minutes=30),
        )
        patches = self._mock_analytics()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = self._post_intel(client, "B00FRESH0001")
        assert resp.status_code == 200
        assert resp.json()["data_freshness"] == "real-time"

    def test_estimated_revenue_has_currency(self, client, asin):
        patches = self._mock_analytics()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = self._post_intel(client)
        assert resp.json()["estimatedRevenue"]["currency"] == "USD"

    def test_curated_summary_contains_revenue(self, client, asin):
        patches = self._mock_analytics()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = self._post_intel(client)
        summary = resp.json()["curated_summary"]
        assert "$" in summary or "Revenue" in summary
