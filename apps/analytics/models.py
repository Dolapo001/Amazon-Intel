from django.db import models
from django.utils import timezone
from apps.products.models import ASIN, Category

class TrendingProduct(models.Model):
    """
    Tracks products experiencing rapid BSR improvement (falling rank).
    Detected by the ASIN Discovery Engine.
    """
    asin = models.ForeignKey(ASIN, on_delete=models.CASCADE, related_name="trending_records")
    discovery_date = models.DateField(default=timezone.now)
    
    # Momentum indicators
    bsr_change_pct = models.FloatField(help_text="BSR improvement % over detection window")
    velocity_score = models.FloatField(help_text="Combined momentum score 0-100")
    
    is_active = models.BooleanField(default=True, help_text="Currently trending")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-velocity_score"]
        unique_together = ("asin", "discovery_date")

    def __str__(self):
        return f"Trending: {self.asin.asin} ({self.velocity_score})"


class CompetitorCluster(models.Model):
    """
    Groups of ASINs competing for the same customer intent.
    Detected by shared category, price range, and keyword overlap.
    """
    anchor_asin = models.OneToOneField(ASIN, on_delete=models.CASCADE, related_name="competitor_cluster")
    competitors = models.ManyToManyField(ASIN, related_name="competitor_of")
    
    updated_at = models.DateTimeField(auto_now=True)
    cluster_stats = models.JSONField(default=dict, help_text="Aggregated niche stats (avg price, total reviews)")

    def __str__(self):
        return f"Cluster for {self.anchor_asin.asin}"


class OpportunityScore(models.Model):
    """
    Niche-level profitability and saturation analysis.
    High Score = High Profitability ($) + Low Saturation (undeserved).
    """
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="opportunity_scores")
    niche_name = models.CharField(max_length=256, blank=True) # e.g. "Wireless Ergonomic Keyboards"
    
    total_score = models.FloatField(help_text="Overall opportunity score 0-100")
    profitability_index = models.FloatField(help_text="Based on avg monthly revenue")
    competition_index = models.FloatField(help_text="High = Underserved (low reviews/ratings)")
    
    demand_growth_pct = models.FloatField(null=True, help_text="Quarter-over-quarter growth")
    
    recommendation = models.TextField(help_text="Human-readable insight")
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-total_score"]

    def __str__(self):
        return f"Opportunity in {self.category.name}: {self.total_score}"
