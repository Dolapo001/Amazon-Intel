import logging
from django.db.models import Avg, Q
from apps.products.models import ASIN
from apps.analytics.models import CompetitorCluster

logger = logging.getLogger(__name__)

def detect_competitor_clusters(asin_code=None):
    """
    Groups products based on market overlap.
    If asin_code is provided, updates only that cluster. Otherwise, scans all Tier 1/2 ASINs.
    """
    if asin_code:
        target_asins = ASIN.objects.filter(asin=asin_code)
    else:
        # Focus on high-value products first
        target_asins = ASIN.objects.filter(tier__in=[1, 2])

    processed = 0
    for anchor in target_asins:
        if not anchor.category or not anchor.current_price:
            continue
            
        # Define competition boundaries
        price_min = float(anchor.current_price) * 0.7
        price_max = float(anchor.current_price) * 1.3
        
        # Find potential competitors: same category, similar price
        competitors = ASIN.objects.filter(
            category=anchor.category,
            current_price__range=(price_min, price_max)
        ).exclude(id=anchor.id)[:10] # Top 10 closest competitors
        
        if competitors.exists():
            cluster, _ = CompetitorCluster.objects.get_or_create(anchor_asin=anchor)
            cluster.competitors.set(competitors)
            
            # Aggregate stats for the niche
            all_comp = list(competitors) + [anchor]
            avg_price = float(sum(c.current_price or 0 for c in all_comp) / len(all_comp))
            avg_rating = sum(c.current_rating or 0 for c in all_comp) / len(all_comp)
            
            cluster.cluster_stats = {
                "avg_price": round(avg_price, 2),
                "avg_rating": round(avg_rating, 2),
                "competitor_count": len(competitors),
                "category_name": anchor.category.name
            }
            cluster.save()
            processed += 1
            
    logger.info("competitor_clustering_complete", extra={"processed": processed})
    return processed
