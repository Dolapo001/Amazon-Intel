import os
import django
import sys
from typing import Any

# 1. Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
django.setup()

from mcp.server.fastmcp import FastMCP
from apps.products.models import ASIN
from apps.analytics.revenue import build_revenue_payload
from apps.analytics.bsr import compute_bsr_trend
from apps.analytics.nlp import get_review_analysis
from apps.analytics.scoring import calculate_opportunity_scores
from apps.analytics.models import OpportunityScore, TrendingProduct

# Create the MCP server
mcp = FastMCP("Amazon Intelligence")

@mcp.tool()
def get_product_intelligence(asin_code: str) -> dict:
    """
    Get Tier S curated intelligence for any Amazon ASIN.
    Returns estimated monthly revenue, BSR trends, sentiment analysis, and success probability.
    """
    try:
        asin_obj = ASIN.objects.get(asin=asin_code.upper())
    except ASIN.DoesNotExist:
        return {"error": f"ASIN {asin_code} not found in database. Please trigger ingestion first."}

    revenue = build_revenue_payload(asin_obj)
    bsr = compute_bsr_trend(asin_obj)
    sentiment = get_review_analysis(asin_obj)

    # Synthesis logic (The "Tier S" value add)
    summary = f"Estimated Revenue: ${revenue['monthly']:,.0f}/mo ({revenue['yoyChange']}% YoY). "
    summary += f"Sentiment: {sentiment['score']}/5. Trend: {bsr['trend'].capitalize()}."

    return {
        "asin": asin_code,
        "revenue_data": revenue,
        "bsr_trend": bsr,
        "sentiment_analysis": sentiment,
        "curated_summary": summary,
        "data_freshness": asin_obj.last_ingested_at.isoformat() if asin_obj.last_ingested_at else "Stale"
    }

@mcp.tool()
def find_market_opportunities() -> list:
    """
    Unbundle costly market research. Returns top underserved niches 
    with high profitability and low market dominance.
    """
    # Trigger a refresh of scores
    calculate_opportunity_scores()
    
    scores = OpportunityScore.objects.all().order_by('-total_score')[:10]
    
    results = []
    for s in scores:
        results.append({
            "niche": s.niche_name,
            "opportunity_score": s.total_score,
            "profitability": s.profitability_index,
            "recommendation": s.recommendation,
            "growth": s.demand_growth_pct
        })
    return results

@mcp.tool()
def get_trending_products() -> list:
    """
    Returns products experiencing rapid BSR improvement (momentum).
    """
    trending = TrendingProduct.objects.filter(is_active=True).select_related('asin')[:10]
    
    return [{
        "asin": t.asin.asin,
        "title": t.asin.title,
        "velocity_score": t.velocity_score,
        "improvement_pct": t.bsr_change_pct,
        "current_bsr": t.asin.current_bsr
    } for t in trending]

if __name__ == "__main__":
    mcp.run()
