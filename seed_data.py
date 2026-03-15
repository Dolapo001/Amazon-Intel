"""
Seed script — insert realistic demo data so the API returns instant 200 responses.
Run with: docker compose exec web python seed_data.py

Inserts:
  - 3 Categories
  - 5 ASINs (real Amazon ASINs with realistic data)
  - RevenueEstimate for each
  - ReviewAnalysis for each
  - BSRSnapshot history (30 days) for each
  - TrendingProduct, CompetitorCluster, OpportunityScore records
"""
import os
import sys
import django
from datetime import date, timedelta
from decimal import Decimal

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
django.setup()

from django.utils import timezone
from apps.products.models import ASIN, Category, RevenueEstimate, ReviewAnalysis, BSRSnapshot
from apps.analytics.models import TrendingProduct, CompetitorCluster, OpportunityScore

print("🌱 Seeding database...")

# ── Categories ─────────────────────────────────────────────────────────────────
cat_electronics, _ = Category.objects.get_or_create(
    amazon_id="172282",
    defaults={"name": "Electronics", "bsr_revenue_multiplier": 1.4, "seasonality_indices": [0.8,0.8,0.9,0.9,0.9,0.9,1.0,1.0,1.1,1.2,1.4,1.6]}
)
cat_kitchen, _ = Category.objects.get_or_create(
    amazon_id="284507",
    defaults={"name": "Kitchen & Dining", "bsr_revenue_multiplier": 1.1, "seasonality_indices": [0.9,0.9,1.0,1.0,1.0,1.0,1.0,1.0,1.1,1.1,1.3,1.5]}
)
cat_fitness, _ = Category.objects.get_or_create(
    amazon_id="3407891",
    defaults={"name": "Sports & Fitness", "bsr_revenue_multiplier": 1.2, "seasonality_indices": [1.3,1.2,1.1,1.0,1.0,0.9,0.9,0.9,0.9,1.0,1.1,1.2]}
)
print("  ✅ Categories created")

# ── ASINs ──────────────────────────────────────────────────────────────────────
asins_data = [
    {
        "asin": "B08N5WRWNW",
        "title": "Echo Dot (4th Gen) Smart Speaker with Alexa",
        "brand": "Amazon",
        "category": cat_electronics,
        "image_url": "https://m.media-amazon.com/images/I/61rdFk5MH+L._AC_SL1000_.jpg",
        "tier": ASIN.TIER_1,
        "current_bsr": 3,
        "current_price": Decimal("49.99"),
        "current_rating": 4.7,
        "current_review_count": 485000,
        "query_count": 12000,
        "monthly_revenue": Decimal("4200000"),
        "revenue_confidence": 0.95,
        "sentiment_score": 4.6,
        "positive_themes": ["sound quality", "easy setup", "alexa integration", "compact size"],
        "negative_themes": ["privacy concerns", "occasional mishearing"],
        "review_velocity": 850.0,
        "total_reviews": 485000,
        "bsr_start": 3,
    },
    {
        "asin": "B09B8YWXDF",
        "title": "Apple AirPods Pro (2nd Gen) with MagSafe Charging Case",
        "brand": "Apple",
        "category": cat_electronics,
        "image_url": "https://m.media-amazon.com/images/I/61SUj2aKoEL._AC_SL1500_.jpg",
        "tier": ASIN.TIER_1,
        "current_bsr": 12,
        "current_price": Decimal("249.00"),
        "current_rating": 4.5,
        "current_review_count": 92000,
        "query_count": 8500,
        "monthly_revenue": Decimal("1900000"),
        "revenue_confidence": 0.92,
        "sentiment_score": 4.4,
        "positive_themes": ["noise cancellation", "sound quality", "battery life", "comfort"],
        "negative_themes": ["price", "case durability"],
        "review_velocity": 210.0,
        "total_reviews": 92000,
        "bsr_start": 18,
    },
    {
        "asin": "B07VGRJDFY",
        "title": "Instant Pot Duo 7-in-1 Electric Pressure Cooker, 6 Quart",
        "brand": "Instant Pot",
        "category": cat_kitchen,
        "image_url": "https://m.media-amazon.com/images/I/71k0lJbECRL._AC_SL1500_.jpg",
        "tier": ASIN.TIER_2,
        "current_bsr": 45,
        "current_price": Decimal("79.95"),
        "current_rating": 4.6,
        "current_review_count": 138000,
        "query_count": 3200,
        "monthly_revenue": Decimal("520000"),
        "revenue_confidence": 0.88,
        "sentiment_score": 4.5,
        "positive_themes": ["easy to use", "versatile", "saves time", "build quality"],
        "negative_themes": ["learning curve", "lid seal issues"],
        "review_velocity": 95.0,
        "total_reviews": 138000,
        "bsr_start": 60,
    },
    {
        "asin": "B08DFPV5Y2",
        "title": "Resistance Bands Set, 11 Piece Exercise Bands",
        "brand": "Fit Simplify",
        "category": cat_fitness,
        "image_url": "https://m.media-amazon.com/images/I/81r2YBkLhDL._AC_SL1500_.jpg",
        "tier": ASIN.TIER_2,
        "current_bsr": 89,
        "current_price": Decimal("24.95"),
        "current_rating": 4.7,
        "current_review_count": 72000,
        "query_count": 1800,
        "monthly_revenue": Decimal("180000"),
        "revenue_confidence": 0.82,
        "sentiment_score": 4.6,
        "positive_themes": ["durable", "great value", "versatile workouts", "included guide"],
        "negative_themes": ["snapping at high tension", "smell on arrival"],
        "review_velocity": 45.0,
        "total_reviews": 72000,
        "bsr_start": 120,
    },
    {
        "asin": "B09G9FPHY6",
        "title": "Ninja AF101 Air Fryer that Crisps, Roasts, Reheats, 4 Quart",
        "brand": "Ninja",
        "category": cat_kitchen,
        "image_url": "https://m.media-amazon.com/images/I/71fG7vUxSaL._AC_SL1500_.jpg",
        "tier": ASIN.TIER_2,
        "current_bsr": 156,
        "current_price": Decimal("99.99"),
        "current_rating": 4.8,
        "current_review_count": 53000,
        "query_count": 890,
        "monthly_revenue": Decimal("310000"),
        "revenue_confidence": 0.79,
        "sentiment_score": 4.7,
        "positive_themes": ["cooks evenly", "easy clean", "compact", "quick heating"],
        "negative_themes": ["fan noise", "basket size"],
        "review_velocity": 62.0,
        "total_reviews": 53000,
        "bsr_start": 200,
    },
]

created_asins = []
for d in asins_data:
    asin_obj, _ = ASIN.objects.update_or_create(
        asin=d["asin"],
        defaults={
            "title": d["title"],
            "brand": d["brand"],
            "category": d["category"],
            "image_url": d["image_url"],
            "tier": d["tier"],
            "current_bsr": d["current_bsr"],
            "current_price": d["current_price"],
            "current_rating": d["current_rating"],
            "current_review_count": d["current_review_count"],
            "query_count": d["query_count"],
            "last_ingested_at": timezone.now(),
        }
    )

    # Revenue Estimate
    RevenueEstimate.objects.update_or_create(
        asin=asin_obj,
        defaults={
            "monthly_revenue": d["monthly_revenue"],
            "yoy_change_pct": 12.5,
            "confidence": d["revenue_confidence"],
            "seasonality_adjusted": True,
            "model_features": {"bsr": d["current_bsr"], "price": float(d["current_price"]), "rating": d["current_rating"]},
            "computed_at": timezone.now(),
        }
    )

    # Review Analysis
    ReviewAnalysis.objects.update_or_create(
        asin=asin_obj,
        defaults={
            "sentiment_score": d["sentiment_score"],
            "positive_themes": d["positive_themes"],
            "negative_themes": d["negative_themes"],
            "review_velocity": d["review_velocity"],
            "total_reviews_analysed": d["total_reviews"],
            "computed_at": timezone.now(),
        }
    )

    # BSR Snapshots — 30 days of history
    today = date.today()
    for i in range(30):
        snap_date = today - timedelta(days=29 - i)
        bsr_rank = int(d["bsr_start"] + (30 - i) * 2)  # improving trend
        BSRSnapshot.objects.update_or_create(
            asin=asin_obj,
            date=snap_date,
            defaults={"bsr_rank": bsr_rank, "price": d["current_price"], "category": d["category"]}
        )

    created_asins.append(asin_obj)
    print(f"  ✅ ASIN {d['asin']} — {d['title'][:50]}")

print("  ✅ All ASINs, revenue estimates, reviews, and BSR history seeded")

# ── Trending Products ──────────────────────────────────────────────────────────
for asin_obj, velocity in zip(created_asins[:3], [92.4, 87.1, 74.6]):
    TrendingProduct.objects.update_or_create(
        asin=asin_obj,
        discovery_date=date.today(),
        defaults={"bsr_change_pct": -18.5, "velocity_score": velocity, "is_active": True}
    )
print("  ✅ TrendingProducts seeded")

# ── Competitor Cluster ─────────────────────────────────────────────────────────
cluster, _ = CompetitorCluster.objects.update_or_create(
    anchor_asin=created_asins[0],
    defaults={"cluster_stats": {"avg_price": 89.99, "total_reviews": 245000, "avg_rating": 4.5}}
)
cluster.competitors.set(created_asins[1:3])
print("  ✅ CompetitorCluster seeded")

# ── Opportunity Scores ─────────────────────────────────────────────────────────
OpportunityScore.objects.update_or_create(
    category=cat_electronics,
    defaults={
        "niche_name": "Smart Home Audio Devices",
        "total_score": 82.4,
        "profitability_index": 91.0,
        "competition_index": 73.8,
        "demand_growth_pct": 24.5,
        "recommendation": "High-revenue niche with strong YoY growth. Entry barrier is brand trust — focus on differentiation via features.",
        "computed_at": timezone.now(),
    }
)
OpportunityScore.objects.update_or_create(
    category=cat_fitness,
    defaults={
        "niche_name": "Home Workout Equipment",
        "total_score": 76.1,
        "profitability_index": 68.0,
        "competition_index": 84.2,
        "demand_growth_pct": 31.2,
        "recommendation": "Underserved niche with explosive growth post-2020. Low average review counts signal opportunity.",
        "computed_at": timezone.now(),
    }
)
OpportunityScore.objects.update_or_create(
    category=cat_kitchen,
    defaults={
        "niche_name": "Healthy Cooking Appliances",
        "total_score": 69.8,
        "profitability_index": 74.5,
        "competition_index": 65.1,
        "demand_growth_pct": 18.7,
        "recommendation": "Solid recurring demand with seasonal peaks (Q4). Strong margin potential at $79–$149 price points.",
        "computed_at": timezone.now(),
    }
)
print("  ✅ OpportunityScores seeded")

print("\n🎉 Seeding complete! Test these ASINs:")
for d in asins_data:
    print(f"   {d['asin']} — {d['title'][:55]}")

print("\nExample:")
print('  curl -X POST http://localhost:5000/v1/product/intelligence \\')
print('    -H "Content-Type: application/json" \\')
print("    -d '{\"asin\": \"B08N5WRWNW\"}'")
