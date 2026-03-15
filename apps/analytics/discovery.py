import logging
from datetime import date, timedelta
from django.db.models import F
from apps.products.models import ASIN, BSRSnapshot
from apps.analytics.models import TrendingProduct
from apps.analytics.revenue import _bsr_slope_30d

logger = logging.getLogger(__name__)

def discover_trending_asins(lookback_days=7, min_improvement_pct=20):
    """
    Scans the database for products with significant momentum.
    Velocity is defined by BSR slope and recent rank change.
    """
    logger.info("discovery_engine_start", extra={"lookback_days": lookback_days})
    
    trending_count = 0
    # 1. Get ASINs that have snapshots from ~lookback_days ago and today
    today = date.today()
    start_date = today - timedelta(days=lookback_days)
    
    # Simple heuristic: Compare current BSR with BSR from lookback_days ago
    asins = ASIN.objects.filter(current_bsr__isnull=False).select_related('category')
    
    for asin in asins:
        old_snapshot = BSRSnapshot.objects.filter(asin=asin, date__lte=start_date).order_by('-date').first()
        if not old_snapshot or not old_snapshot.bsr_rank:
            continue
            
        old_bsr = old_snapshot.bsr_rank
        new_bsr = asin.current_bsr
        
        # BSR improvement = old_bsr - new_bsr (since lower is better)
        improvement = old_bsr - new_bsr
        improvement_pct = (improvement / old_bsr) * 100 if old_bsr > 0 else 0
        
        if improvement_pct >= min_improvement_pct:
            # Calculate velocity score 0-100
            # Combines improvement % and the actual slope
            slope = _bsr_slope_30d(asin) # negative means improving
            
            # Normalize slope: -500 rank/day is very fast. 
            # velocity = (improvement_pct * 0.5) + (abs(slope) * some_factor)
            velocity_score = min(100.0, (improvement_pct * 0.7) + (min(abs(slope), 500) / 500 * 30))
            
            TrendingProduct.objects.update_or_create(
                asin=asin,
                discovery_date=today,
                defaults={
                    "bsr_change_pct": round(improvement_pct, 2),
                    "velocity_score": round(velocity_score, 2),
                    "is_active": True,
                    "metadata": {
                        "old_bsr": old_bsr,
                        "new_bsr": new_bsr,
                        "slope": round(slope, 2),
                        "category": asin.category.name if asin.category else "Unknown"
                    }
                }
            )
            trending_count += 1
            
    logger.info("discovery_engine_complete", extra={"found": trending_count})
    return trending_count
