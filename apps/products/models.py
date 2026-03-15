"""
Core data models.

PostgreSQL stores product metadata & aggregated analytics.
ClickHouse (separate client) stores the BSR time-series.
"""
from django.db import models
from django.utils import timezone


class Category(models.Model):
    """Amazon category with calibration data for revenue modelling."""

    amazon_id = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=256)

    # Revenue model calibration: category-specific scaling factor
    # Used as a fallback when ML model has low confidence.
    bsr_revenue_multiplier = models.FloatField(default=1.0)

    # Seasonality index per month (stored as 12-element JSON array, index 0 = Jan)
    seasonality_indices = models.JSONField(default=list)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class ASIN(models.Model):
    """Canonical product record keyed by Amazon ASIN."""

    TIER_1 = 1  # top 50k  → refresh every 6h
    TIER_2 = 2  # next 500k → refresh every 24h
    TIER_3 = 3  # long tail  → refresh weekly

    TIER_CHOICES = [(TIER_1, "Tier 1"), (TIER_2, "Tier 2"), (TIER_3, "Tier 3")]

    asin = models.CharField(max_length=10, unique=True, db_index=True)
    title = models.CharField(max_length=512, blank=True)
    brand = models.CharField(max_length=256, blank=True)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL)
    image_url = models.URLField(blank=True)

    tier = models.SmallIntegerField(choices=TIER_CHOICES, default=TIER_3)
    query_count = models.PositiveIntegerField(default=0, help_text="Cumulative user queries; drives tier promotion")

    # Latest snapshot (denormalised for fast reads)
    current_bsr = models.IntegerField(null=True, blank=True)
    current_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    current_rating = models.FloatField(null=True, blank=True)
    current_review_count = models.IntegerField(null=True, blank=True)

    last_ingested_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["tier", "last_ingested_at"]),
        ]

    def __str__(self):
        return f"{self.asin} — {self.title[:60]}"

    def promote_tier(self):
        """Move ASIN to a higher refresh tier based on query volume."""
        if self.query_count >= 500 and self.tier == self.TIER_3:
            self.tier = self.TIER_2
            self.save(update_fields=["tier"])
        elif self.query_count >= 5000 and self.tier == self.TIER_2:
            self.tier = self.TIER_1
            self.save(update_fields=["tier"])


class RevenueEstimate(models.Model):
    """
    Latest ML-derived monthly revenue estimate for an ASIN.
    Refreshed whenever BSR data is updated.
    """

    asin = models.OneToOneField(ASIN, on_delete=models.CASCADE, related_name="revenue_estimate")

    monthly_revenue = models.DecimalField(max_digits=12, decimal_places=2)
    yoy_change_pct = models.FloatField(null=True, blank=True, help_text="Year-over-year % change")
    confidence = models.FloatField(help_text="Model confidence score 0–1")
    seasonality_adjusted = models.BooleanField(default=False)

    # Store the raw model features for auditability
    model_features = models.JSONField(default=dict)

    computed_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.asin_id}: ${self.monthly_revenue}/mo"


class ReviewAnalysis(models.Model):
    """
    NLP-derived sentiment & theme analysis for an ASIN.
    Computed offline by the ingestion pipeline.
    """

    asin = models.OneToOneField(ASIN, on_delete=models.CASCADE, related_name="review_analysis")

    sentiment_score = models.FloatField(help_text="Aggregate sentiment 1–5")
    positive_themes = models.JSONField(default=list, help_text="Top positive keywords/phrases")
    negative_themes = models.JSONField(default=list, help_text="Top negative keywords/phrases")
    sentiment_summary = models.TextField(null=True, blank=True, help_text="Prose summary of customer feedback")

    # Review velocity: new reviews per day (30-day rolling average)
    review_velocity = models.FloatField(null=True, blank=True)

    total_reviews_analysed = models.IntegerField(default=0)
    computed_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.asin_id}: sentiment {self.sentiment_score}"


class BSRSnapshot(models.Model):
    """
    Lightweight PostgreSQL shadow of ClickHouse BSR time-series.
    Used for YoY comparison queries without hitting ClickHouse.
    Stores ONE row per ASIN per day (daily roll-up).
    """

    asin = models.ForeignKey(ASIN, on_delete=models.CASCADE, related_name="bsr_snapshots", db_index=True)
    date = models.DateField(db_index=True)

    bsr_rank = models.IntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        unique_together = ("asin", "date")
        indexes = [
            models.Index(fields=["asin", "date"]),
        ]

    def __str__(self):
        return f"{self.asin_id} @ {self.date}: BSR {self.bsr_rank}"
