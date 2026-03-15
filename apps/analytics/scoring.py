import logging
from django.db.models import Avg, Sum, Count
from apps.products.models import Category, ASIN, RevenueEstimate, ReviewAnalysis
from apps.analytics.models import OpportunityScore

logger = logging.getLogger(__name__)

def calculate_opportunity_scores():
    """
    Identifies 'underserved' niches.
    Formula: Profitability (Avg Revenue) / Saturation (Avg Review Count)
    """
    categories = Category.objects.all()
    scored_count = 0
    
    for cat in categories:
        asins = ASIN.objects.filter(category=cat)
        if not asins.exists():
            continue
            
        # 1. Profitability Index (0-100)
        # Based on average monthly revenue in the category
        avg_revenue = RevenueEstimate.objects.filter(asin__category=cat).aggregate(Avg('monthly_revenue'))['monthly_revenue__avg']
        if not avg_revenue:
            avg_revenue = 0
        
        # Normalize: $100k/mo = 100 points
        profitability_index = min(100.0, float(avg_revenue) / 1000.0)
        
        # 2. Competition Index (0-100) - Higher is BETTER (easier to enter)
        # Based on average review count. If avg review count is low, competition is weak.
        avg_reviews = asins.aggregate(Avg('current_review_count'))['current_review_count__avg'] or 0
        # If avg reviews < 100, high opportunity (100 pts). If > 5000, low opportunity (0 pts).
        competition_index = max(0.0, 100.0 - (avg_reviews / 50.0))
        
        # 3. Sentiment factor
        avg_sentiment = ReviewAnalysis.objects.filter(asin__category=cat).aggregate(Avg('sentiment_score'))['sentiment_score__avg'] or 3.0
        # If sentiment is low (< 3.5), it means customers are unhappy with existing products = Opportunity!
        sentiment_bonus = max(0.0, (3.5 - avg_sentiment) * 20)
        
        # 4. Market Dominance (Whale Detection) - Higher Dominance = LOWER Opportunity
        # Calculate % of revenue held by top 3 brands
        top_brand_rev = RevenueEstimate.objects.filter(asin__category=cat).order_by('-monthly_revenue').values_list('monthly_revenue', flat=True)[:3]
        total_cat_rev = RevenueEstimate.objects.filter(asin__category=cat).aggregate(Sum('monthly_revenue'))['monthly_revenue__sum'] or 1.0
        dominance_pct = (sum(top_brand_rev) / float(total_cat_rev)) * 100
        
        # Dominance Penalty: If > 70% revenue is top 3 brands, it's hard to break in.
        dominance_penalty = max(0.0, (dominance_pct - 50.0) * 0.5)

        total_score = min(100.0, (profitability_index * 0.4) + (competition_index * 0.4) + sentiment_bonus - dominance_penalty)
        
        # Generate recommendation
        if total_score > 75:
            rec = f"CRITICAL OPPORTUNITY: ${avg_revenue:,.0f} avg rev with weak incumbents. Market dominance is low ({dominance_pct:.1f}%). Immediate entry recommended."
        elif total_score > 50:
            rec = "MODERATE OPPORTUNITY: Profitable niche but requires superior quality to displace existing brands."
        else:
            rec = "SATURATED/DOMINATED: Highly dominated or low revenue. Top 3 brands control " + f"{dominance_pct:.1f}% of the market."

        OpportunityScore.objects.update_or_create(
            category=cat,
            defaults={
                "total_score": round(float(total_score), 2),
                "profitability_index": round(float(profitability_index), 2),
                "competition_index": round(float(competition_index), 2),
                "recommendation": rec,
                "demand_growth_pct": 5.0,
                "niche_name": cat.name
            }
        )
        scored_count += 1
        
    logger.info("opportunity_scoring_complete", extra={"scored": scored_count})
    return scored_count
