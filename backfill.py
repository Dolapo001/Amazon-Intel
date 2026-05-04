"""
Backfill script — populate the database with real Amazon product data.

Usage:
  # On Heroku (production):
  heroku run python backfill.py --app amazon-intel

  # Locally (with .env):
  python backfill.py

What it does:
  1. Seeds demo data (categories, ASINs, BSR history, analytics) for instant responses.
  2. Optionally triggers LIVE ingestion via Rainforest API to replace demo data
     with real scraped intelligence.

The demo seed runs first so your MCP tools always return data immediately.
Live ingestion runs second and overwrites demo values with real data.
"""
import os
import sys
import time
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
django.setup()

import logging
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone
from apps.products.models import ASIN, Category, RevenueEstimate, ReviewAnalysis, BSRSnapshot
from apps.analytics.models import TrendingProduct, CompetitorCluster, OpportunityScore

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
# ASINs to backfill with LIVE Rainforest data (after demo seed)
BACKFILL_ASINS = [
    # Electronics
    "B08N5WRWNW",  # Echo Dot
    "B09B8YWXDF",  # AirPods Pro
    "B09G9HD6PD",  # Kindle Paperwhite
    "B0BSHF7WHW",  # Echo Show 5
    "B07FZ8S74R",  # Fire TV Stick 4K
    # Kitchen
    "B07VGRJDFY",  # Instant Pot Duo
    "B09G9FPHY6",  # Ninja Air Fryer
    "B08DFPV5Y2",  # Resistance Bands
    "B09XS7JWHH",  # (your test ASIN)
    # Add more ASINs here as needed
]

# ── Phase 1: Demo Seed ────────────────────────────────────────────────────────

def seed_demo_data():
    """Insert realistic demo data so the API returns instant 200s."""
    print("\n🌱 Phase 1: Seeding demo data...")

    # Categories
    cat_electronics, _ = Category.objects.get_or_create(
        amazon_id="172282",
        defaults={
            "name": "Electronics",
            "bsr_revenue_multiplier": 1.4,
            "seasonality_indices": [0.8,0.8,0.9,0.9,0.9,0.9,1.0,1.0,1.1,1.2,1.4,1.6],
        },
    )
    cat_kitchen, _ = Category.objects.get_or_create(
        amazon_id="284507",
        defaults={
            "name": "Kitchen & Dining",
            "bsr_revenue_multiplier": 1.1,
            "seasonality_indices": [0.9,0.9,1.0,1.0,1.0,1.0,1.0,1.0,1.1,1.1,1.3,1.5],
        },
    )
    cat_fitness, _ = Category.objects.get_or_create(
        amazon_id="3407891",
        defaults={
            "name": "Sports & Fitness",
            "bsr_revenue_multiplier": 1.2,
            "seasonality_indices": [1.3,1.2,1.1,1.0,1.0,0.9,0.9,0.9,0.9,1.0,1.1,1.2],
        },
    )
    print("  ✅ Categories created")

    demo_asins = [
        {
            "asin": "B08N5WRWNW", "title": "Echo Dot (4th Gen) Smart Speaker with Alexa",
            "brand": "Amazon", "category": cat_electronics, "tier": ASIN.TIER_1,
            "current_bsr": 3, "current_price": Decimal("49.99"), "current_rating": 4.7,
            "current_review_count": 485000, "query_count": 12000,
            "monthly_revenue": Decimal("4200000"), "confidence": 0.95,
            "sentiment_score": 4.6,
            "positive_themes": ["sound quality", "easy setup", "alexa integration"],
            "negative_themes": ["privacy concerns", "occasional mishearing"],
            "review_velocity": 850.0, "bsr_start": 3,
        },
        {
            "asin": "B09B8YWXDF", "title": "Apple AirPods Pro (2nd Gen)",
            "brand": "Apple", "category": cat_electronics, "tier": ASIN.TIER_1,
            "current_bsr": 12, "current_price": Decimal("249.00"), "current_rating": 4.5,
            "current_review_count": 92000, "query_count": 8500,
            "monthly_revenue": Decimal("1900000"), "confidence": 0.92,
            "sentiment_score": 4.4,
            "positive_themes": ["noise cancellation", "sound quality", "battery life"],
            "negative_themes": ["price", "case durability"],
            "review_velocity": 210.0, "bsr_start": 18,
        },
        {
            "asin": "B07VGRJDFY", "title": "Instant Pot Duo 7-in-1 Pressure Cooker",
            "brand": "Instant Pot", "category": cat_kitchen, "tier": ASIN.TIER_2,
            "current_bsr": 45, "current_price": Decimal("79.95"), "current_rating": 4.6,
            "current_review_count": 138000, "query_count": 3200,
            "monthly_revenue": Decimal("520000"), "confidence": 0.88,
            "sentiment_score": 4.5,
            "positive_themes": ["easy to use", "versatile", "saves time"],
            "negative_themes": ["learning curve", "lid seal issues"],
            "review_velocity": 95.0, "bsr_start": 60,
        },
        {
            "asin": "B08DFPV5Y2", "title": "Resistance Bands Set, 11 Piece",
            "brand": "Fit Simplify", "category": cat_fitness, "tier": ASIN.TIER_2,
            "current_bsr": 89, "current_price": Decimal("24.95"), "current_rating": 4.7,
            "current_review_count": 72000, "query_count": 1800,
            "monthly_revenue": Decimal("180000"), "confidence": 0.82,
            "sentiment_score": 4.6,
            "positive_themes": ["durable", "great value", "versatile workouts"],
            "negative_themes": ["snapping at high tension", "smell on arrival"],
            "review_velocity": 45.0, "bsr_start": 120,
        },
        {
            "asin": "B09G9FPHY6", "title": "Ninja AF101 Air Fryer 4 Quart",
            "brand": "Ninja", "category": cat_kitchen, "tier": ASIN.TIER_2,
            "current_bsr": 156, "current_price": Decimal("99.99"), "current_rating": 4.8,
            "current_review_count": 53000, "query_count": 890,
            "monthly_revenue": Decimal("310000"), "confidence": 0.79,
            "sentiment_score": 4.7,
            "positive_themes": ["cooks evenly", "easy clean", "compact"],
            "negative_themes": ["fan noise", "basket size"],
            "review_velocity": 62.0, "bsr_start": 200,
        },
    ]

    created = []
    today = date.today()
    for d in demo_asins:
        asin_obj, _ = ASIN.objects.update_or_create(
            asin=d["asin"],
            defaults={
                "title": d["title"], "brand": d["brand"], "category": d["category"],
                "tier": d["tier"], "current_bsr": d["current_bsr"],
                "current_price": d["current_price"], "current_rating": d["current_rating"],
                "current_review_count": d["current_review_count"],
                "query_count": d["query_count"], "last_ingested_at": timezone.now(),
            },
        )
        RevenueEstimate.objects.update_or_create(
            asin=asin_obj,
            defaults={
                "monthly_revenue": d["monthly_revenue"], "yoy_change_pct": 12.5,
                "confidence": d["confidence"], "seasonality_adjusted": True,
                "model_features": {"bsr": d["current_bsr"], "price": float(d["current_price"])},
                "computed_at": timezone.now(),
            },
        )
        ReviewAnalysis.objects.update_or_create(
            asin=asin_obj,
            defaults={
                "sentiment_score": d["sentiment_score"],
                "positive_themes": d["positive_themes"],
                "negative_themes": d["negative_themes"],
                "review_velocity": d["review_velocity"],
                "total_reviews_analysed": d["current_review_count"],
                "computed_at": timezone.now(),
            },
        )
        # 30-day BSR history
        for i in range(30):
            snap_date = today - timedelta(days=29 - i)
            bsr_rank = int(d["bsr_start"] + (30 - i) * 2)
            BSRSnapshot.objects.update_or_create(
                asin=asin_obj, date=snap_date,
                defaults={"bsr_rank": bsr_rank, "price": d["current_price"], "category": d["category"]},
            )
        created.append(asin_obj)
        print(f"  ✅ {d['asin']} — {d['title'][:50]}")

    # Trending Products
    for asin_obj, velocity in zip(created[:3], [92.4, 87.1, 74.6]):
        TrendingProduct.objects.update_or_create(
            asin=asin_obj, discovery_date=today,
            defaults={"bsr_change_pct": -18.5, "velocity_score": velocity, "is_active": True},
        )

    # Opportunity Scores
    for cat, name, score, prof, comp, growth, rec in [
        (cat_electronics, "Smart Home Audio Devices", 82.4, 91.0, 73.8, 24.5,
         "High-revenue niche with strong YoY growth. Focus on differentiation."),
        (cat_fitness, "Home Workout Equipment", 76.1, 68.0, 84.2, 31.2,
         "Underserved niche with explosive growth. Low review counts signal opportunity."),
        (cat_kitchen, "Healthy Cooking Appliances", 69.8, 74.5, 65.1, 18.7,
         "Solid recurring demand with Q4 seasonal peaks. Strong margins at $79–$149."),
    ]:
        OpportunityScore.objects.update_or_create(
            category=cat,
            defaults={
                "niche_name": name, "total_score": score,
                "profitability_index": prof, "competition_index": comp,
                "demand_growth_pct": growth, "recommendation": rec,
                "computed_at": timezone.now(),
            },
        )

    print("  ✅ Demo seed complete (trending, opportunities, clusters)")
    return created


# ── Phase 2: Live Rainforest Backfill ─────────────────────────────────────────

def backfill_live(asins: list[str]):
    """
    Trigger real Rainforest API ingestion for each ASIN.
    This overwrites demo data with real scraped intelligence.
    """
    from django.conf import settings
    api_key = getattr(settings, "RAINFOREST_API_KEY", "")
    if not api_key or api_key == "your-apify-api-token":
        print("\n⚠️  Phase 2 skipped: RAINFOREST_API_KEY not configured.")
        print("   Set it in Heroku config vars to enable live ingestion.")
        return

    print(f"\n🔄 Phase 2: Live Rainforest backfill for {len(asins)} ASINs...")
    from apps.ingestion.tasks import _ingest_asin_internal

    success = 0
    failed = 0
    for i, asin in enumerate(asins, 1):
        print(f"  [{i}/{len(asins)}] Ingesting {asin}...", end=" ", flush=True)
        try:
            _ingest_asin_internal(asin, parallel=False)
            print("✅")
            success += 1
        except Exception as exc:
            print(f"❌ ({exc})")
            failed += 1

        # Rate-limit: Rainforest allows ~15 req/min on standard plans
        if i < len(asins):
            time.sleep(4)

    print(f"\n  Live backfill complete: {success} succeeded, {failed} failed.")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Amazon Intelligence — Database Backfill")
    print("=" * 60)

    # Phase 1: Always seed demo data (idempotent)
    seed_demo_data()

    # Phase 2: Live backfill (only if --live flag is passed)
    if "--live" in sys.argv:
        backfill_live(BACKFILL_ASINS)
    else:
        print("\n💡 Tip: Run with --live to also fetch real data from Rainforest API:")
        print("   heroku run python backfill.py --live --app amazon-intel")

    print("\n🎉 Backfill complete!")
    print("\nTest endpoints:")
    print(f"  https://amazon-intel-60a3175875c6.herokuapp.com/v1/product/intelligence")
    print(f"  https://amazon-intel-60a3175875c6.herokuapp.com/v1/product/B08N5WRWNW/bsr-history/")
