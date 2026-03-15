"""DRF serializers — input validation and output shaping."""
import re
from rest_framework import serializers
from .models import ASIN, Category, RevenueEstimate, ReviewAnalysis, BSRSnapshot


# ── Input ─────────────────────────────────────────────────────────────────────

ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
AMAZON_URL_RE = re.compile(r"/dp/([A-Z0-9]{10})")


class ASINQuerySerializer(serializers.Serializer):
    """
    PRD §3.1: Request body accepts { "asin": "B09XYZ123" }.
    Also tolerates a full Amazon product URL for convenience — normalised to
    a clean 10-character ASIN string before further processing.
    """

    asin = serializers.CharField(
        max_length=512,
        help_text='Amazon ASIN (e.g. "B09XYZ1234") or full Amazon product URL',
    )

    def validate_asin(self, value: str) -> str:
        value = value.strip()

        # Direct ASIN
        if ASIN_RE.match(value.upper()):
            return value.upper()

        # URL containing /dp/ASIN
        match = AMAZON_URL_RE.search(value)
        if match:
            return match.group(1).upper()

        raise serializers.ValidationError(
            "Provide a valid 10-character ASIN or an Amazon product URL containing /dp/<ASIN>."
        )


# ── Output ────────────────────────────────────────────────────────────────────

class RevenueEstimateSerializer(serializers.ModelSerializer):
    monthly = serializers.DecimalField(source="monthly_revenue", max_digits=12, decimal_places=2)
    yoyChange = serializers.FloatField(source="yoy_change_pct")
    confidence = serializers.FloatField()
    seasonalityAdjusted = serializers.BooleanField(source="seasonality_adjusted")

    class Meta:
        model = RevenueEstimate
        fields = ["monthly", "yoyChange", "confidence", "seasonalityAdjusted"]


class ReviewAnalysisSerializer(serializers.ModelSerializer):
    score = serializers.FloatField(source="sentiment_score")
    positiveThemes = serializers.ListField(source="positive_themes", child=serializers.CharField())
    negativeThemes = serializers.ListField(source="negative_themes", child=serializers.CharField())
    reviewVelocity = serializers.FloatField(source="review_velocity")
    totalReviewsAnalysed = serializers.IntegerField(source="total_reviews_analysed")

    class Meta:
        model = ReviewAnalysis
        fields = ["score", "positiveThemes", "negativeThemes", "reviewVelocity", "totalReviewsAnalysed"]


class BSRTrendSerializer(serializers.Serializer):
    currentRank = serializers.IntegerField()
    yoyChange = serializers.IntegerField()          # absolute rank delta
    yoyChangePct = serializers.FloatField()
    trend = serializers.CharField()                 # "improving" | "declining" | "stable"
    history = serializers.ListField(child=serializers.DictField())  # [{date, bsr}]


class ProductIntelligenceSerializer(serializers.Serializer):
    """
    The canonical API response.  Matches the JSON schema in the spec doc.
    """

    asin = serializers.CharField()
    title = serializers.CharField()
    brand = serializers.CharField()
    category = serializers.CharField()
    imageUrl = serializers.CharField()

    estimatedRevenue = RevenueEstimateSerializer()
    sentiment = ReviewAnalysisSerializer()
    bsrTrend = BSRTrendSerializer()

    # Human-readable synthesis (LLM-generated summary or rule-based)
    summary = serializers.CharField()

    dataFreshness = serializers.DateTimeField()
    cacheHit = serializers.BooleanField()

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "amazon_id", "name"]

class ASINSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = ASIN
        fields = ["asin", "title", "brand", "category", "category_name", "image_url", "current_bsr", "current_price", "current_rating", "current_review_count"]
