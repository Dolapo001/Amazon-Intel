import logging
from celery import shared_task
from .discovery import discover_trending_asins
from .clustering import detect_competitor_clusters
from .scoring import calculate_opportunity_scores

logger = logging.getLogger(__name__)

@shared_task(name="apps.analytics.tasks.run_discovery_engine")
def run_discovery_engine():
    """Daily task to find trending products."""
    count = discover_trending_asins()
    return {"trending_found": count}

@shared_task(name="apps.analytics.tasks.run_competitor_analysis")
def run_competitor_analysis():
    """Weekly task to cluster competitors."""
    count = detect_competitor_clusters()
    return {"clusters_updated": count}

@shared_task(name="apps.analytics.tasks.run_opportunity_scoring")
def run_opportunity_scoring():
    """Weekly task to update niche opportunity scores."""
    count = calculate_opportunity_scores()
    return {"categories_scored": count}
