"""
Celery tasks for data ingestion and model maintenance.

Data sources (post-Keepa removal):
  Product data + BSR  → Apify junglee/amazon-product-scraper
  Reviews             → Apify junglee/amazon-reviews-scraper

Task hierarchy:
  refresh_tier_asins         → dispatches per-ASIN ingest sub-tasks  (BSR cadence §11)
  scrape_tier_reviews        → dispatches per-ASIN review sub-tasks   (review cadence §4.2)
  enqueue_asin_refresh       → immediate refresh for a user-queried ASIN
  ingest_asin                → fetch product/BSR via Apify, write to DB
  fetch_and_analyse_reviews  → fetch reviews via Apify, run NLP, write ReviewAnalysis
  retrain_revenue_model      → nightly XGBoost retraining
"""
import logging
from datetime import date, timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Tier orchestrators ────────────────────────────────────────────────────────

@shared_task(name="apps.ingestion.tasks.refresh_tier_asins", bind=True, max_retries=2)
def refresh_tier_asins(self, tier: int):
    """Kick off BSR ingestion for all ASINs in a given tier (PRD §11)."""
    from apps.products.models import ASIN

    asins = list(ASIN.objects.filter(tier=tier).values_list("asin", flat=True))
    logger.info("tier_bsr_refresh_start", extra={"tier": tier, "count": len(asins)})
    for asin in asins:
        ingest_asin.delay(asin)
    return {"tier": tier, "queued": len(asins)}


@shared_task(name="apps.ingestion.tasks.scrape_tier_reviews", bind=True, max_retries=2)
def scrape_tier_reviews(self, tier: int):
    """
    Kick off review fetching for all ASINs in a tier (PRD §4.2).
      Tier 1 → every 12h  |  Tier 2 → every 3d  |  Tier 3 → every 7d
    """
    from apps.products.models import ASIN

    asins = list(ASIN.objects.filter(tier=tier).values_list("asin", flat=True))
    logger.info("tier_review_refresh_start", extra={"tier": tier, "count": len(asins)})
    for asin in asins:
        fetch_and_analyse_reviews.delay(asin)
    return {"tier": tier, "queued": len(asins)}


# ── Immediate refresh (user-triggered) ───────────────────────────────────────

@shared_task(name="apps.ingestion.tasks.enqueue_asin_refresh", bind=True, max_retries=3)
def enqueue_asin_refresh(self, asin_code: str, priority: str = "normal"):
    """
    Triggered when a user queries an unknown or stale ASIN.
    Runs full ingest + NLP pipeline at elevated queue priority.
    """
    queue = "high_priority" if priority in ("high", "immediate") else "default"
    ingest_asin.apply_async(args=[asin_code], queue=queue)
    logger.info("asin_refresh_enqueued", extra={"asin": asin_code, "priority": priority})


# ── Core ingest task ──────────────────────────────────────────────────────────

def _ingest_asin_internal(asin_code: str, parallel: bool = True):
    """
    Core pipeline logic: Parallel/Sequential Scraping → Cleaning → NLP → Revenue → BSR.
    Shared by both Celery task and synchronous API calls.
    """
    from apps.ingestion.scraper import concurrent_fetch, fetch_product, fetch_reviews
    from apps.products.models import ASIN, Category, BSRSnapshot
    from apps.analytics.nlp import analyse_and_persist
    from apps.products.cache import set_cached_intel
    from apps.analytics.revenue import build_revenue_payload
    from apps.analytics.bsr import compute_bsr_trend

    logger.info("ingest_pipeline_start", extra={"asin": asin_code})

    # ── 1. Scrape ───────────────────────────────────────────────────────
    try:
        if parallel:
            product, reviews = concurrent_fetch(asin_code, fast_mode=True)
        else:
            # Sequential mode for synchronous calls - safer in some Gunicorn setups
            product, reviews = fetch_product(asin_code)
    except Exception as exc:
        logger.exception("scrape_failed", extra={"asin": asin_code})
        raise exc

    # ── 2. Persistence ───────────────────────────────────────────────────
    asin_obj = None
    if product:
        category, _ = Category.objects.get_or_create(
            name=product.get("category_name", "Uncategorized")
        )
        asin_obj, _ = ASIN.objects.update_or_create(
            asin=asin_code,
            defaults={
                "title":                product.get("title", ""),
                "brand":                product.get("brand", ""),
                "category":             category,
                "image_url":            product.get("image_url", ""),
                "current_bsr":          product.get("current_bsr"),
                "current_price":        product.get("current_price"),
                "current_rating":       product.get("current_rating"),
                "current_review_count": product.get("current_review_count"),
                "last_ingested_at":     timezone.now(),
            },
        )

        if product.get("current_bsr"):
            BSRSnapshot.objects.update_or_create(
                asin=asin_obj, date=date.today(),
                defaults={"bsr_rank": product["current_bsr"]},
            )
        
        _persist_bsr_to_clickhouse(asin_code, product.get("current_bsr"))
    else:
        try:
            asin_obj = ASIN.objects.get(asin=asin_code)
        except ASIN.DoesNotExist:
            logger.warning("scrape_failed_no_record", extra={"asin": asin_code})
            raise ValueError(f"Scraper returned no data for ASIN {asin_code} and no existing record found")

    # ── 3. Heavy Analytics ───────────────────────────────────────────────
    if asin_obj:
        analyse_and_persist(asin_obj, reviews)
        
        revenue_payload = build_revenue_payload(asin_obj, force_recompute=True)
        bsr_trend = compute_bsr_trend(asin_obj)

        # ── 4. Warm Redis L1 Cache ──────────────────────────────────────────
        from apps.analytics.nlp import get_review_analysis
        sentiment = get_review_analysis(asin_obj)

        final_payload = {
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
            "cacheHit": False
        }
        set_cached_intel(asin_code, final_payload, tier=asin_obj.tier)

    logger.info("ingest_pipeline_complete", extra={"asin": asin_code})


@shared_task(
    name="apps.ingestion.tasks.ingest_asin",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def ingest_asin(self, asin_code: str):
    try:
        return _ingest_asin_internal(asin_code)
    except Exception as exc:
        raise self.retry(exc=exc)


def synchronous_full_ingest(asin_code: str):
    """
    Used by the view for new ASINs to ensure immediate full response.
    Raises if the scraper fails so the caller can return a proper error.
    """
    # Use sequential mode for better stability in synchronous API environment
    _ingest_asin_internal(asin_code, parallel=False)

    from apps.products.models import ASIN
    return ASIN.objects.get(asin=asin_code)


# ── Review fetch + NLP task ───────────────────────────────────────────────────

@shared_task(
    name="apps.ingestion.tasks.fetch_and_analyse_reviews",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def fetch_and_analyse_reviews(self, asin_code: str, max_count: int = 100):
    from apps.ingestion.scraper import fetch_reviews
    from apps.products.models import ASIN
    from apps.analytics.nlp import analyse_and_persist
    from apps.products.cache import invalidate_intel

    try:
        asin_obj = ASIN.objects.get(asin=asin_code)
    except ASIN.DoesNotExist:
        return

    try:
        reviews = fetch_reviews(asin_code, max_count=max_count)
    except Exception as exc:
        raise self.retry(exc=exc)

    if reviews:
        analyse_and_persist(asin_obj, reviews)
        invalidate_intel(asin_code)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _persist_bsr_to_clickhouse(asin_code: str, bsr_rank):
    if not bsr_rank: return
    try:
        from datetime import datetime, timezone as tz
        from django.conf import settings
        from clickhouse_driver import Client

        ch = Client(
            host=settings.CLICKHOUSE["host"],
            port=settings.CLICKHOUSE["port"],
            database=settings.CLICKHOUSE["database"],
            user=settings.CLICKHOUSE["user"],
            password=settings.CLICKHOUSE["password"],
        )
        ch.execute(
            "INSERT INTO bsr_timeseries (asin, timestamp, bsr_rank) VALUES",
            [(asin_code, datetime.now(tz=tz.utc), int(bsr_rank))],
        )
    except Exception:
        pass


@shared_task(name="apps.analytics.tasks.retrain_revenue_model", bind=True)
def retrain_revenue_model(self):
    # Dummy placeholder for retraining logic
    logger.info("model_retraining_mock")
    return {"status": "success"}
