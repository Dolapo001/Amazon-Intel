"""
Amazon Intelligence — direct FastMCP server.

This variant runs inside the Django process (no HTTP hop) and uses the
`fastmcp` library pattern recommended by the Context Protocol docs:

    from fastmcp import FastMCP
    from fastmcp.server.middleware import Middleware, MiddlewareContext
    from fastmcp.server.dependencies import get_http_headers
    from fastmcp.exceptions import ToolError

Every tool publishes Context Protocol `_meta` (surface / queryEligible /
latencyClass / pricing.executeUsd / rateLimit) via FastMCP's `meta` argument
so the method is visible on both Query and Execute surfaces.
"""
import os
import sys

import django

# 1. Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
django.setup()

from ctxprotocol import ContextError, verify_context_request  # noqa: E402
from fastmcp import FastMCP  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402
from fastmcp.server.dependencies import get_http_headers  # noqa: E402
from fastmcp.server.middleware import Middleware, MiddlewareContext  # noqa: E402

from apps.analytics.bsr import compute_bsr_trend  # noqa: E402
from apps.analytics.models import OpportunityScore, TrendingProduct  # noqa: E402
from apps.analytics.nlp import get_review_analysis  # noqa: E402
from apps.analytics.revenue import build_revenue_payload  # noqa: E402
from apps.analytics.scoring import calculate_opportunity_scores  # noqa: E402
from apps.products.models import ASIN, Category  # noqa: E402

# ── Marketplace pricing metadata (see Context Protocol pricing guidance) ────
EXECUTE_PRICE_INTEL = "0.001"
EXECUTE_PRICE_RAW = "0.0005"
EXECUTE_PRICE_DISCOVERY = "0.0002"

DJANGO_RATE_LIMIT = {
    "maxRequestsPerMinute": 120,
    "cooldownMs": 500,
    "maxConcurrency": 10,
    "supportsBulk": False,
    "notes": "In-process Django ORM reads; no external API fan-out.",
}

mcp = FastMCP("Amazon Intelligence")


# The Context Protocol JWT authentication is handled entirely by mcp_proxy.py at the HTTP layer.
# We do not use FastMCP middleware for auth because JSON-RPC messages do not contain HTTP headers.

# ── Tier 1: Intelligence tools ──────────────────────────────────────────────

@mcp.tool(
    meta={
        "surface": "both",
        "queryEligible": True,
        "latencyClass": "fast",
        "pricing": {"executeUsd": EXECUTE_PRICE_INTEL},
        "rateLimit": DJANGO_RATE_LIMIT,
    },
)
def get_product_intelligence(asin_code: str) -> dict:
    """TIER 1 INTELLIGENCE: Curated Amazon product report.

    Synthesises BSR trend, estimated monthly revenue (with YoY delta) and
    NLP-derived sentiment themes into a single response. Replaces the core
    Jungle Scout ($500/yr) workflow for on-demand product intelligence.

    Args:
        asin_code: 10-character Amazon ASIN (e.g. "B09G9HD6PD").
    """
    try:
        asin_obj = ASIN.objects.get(asin=asin_code.upper())
    except ASIN.DoesNotExist:
        return {"error": f"ASIN {asin_code} not found. Trigger ingestion first."}

    revenue = build_revenue_payload(asin_obj)
    bsr = compute_bsr_trend(asin_obj)
    sentiment = get_review_analysis(asin_obj)

    summary = (
        f"Estimated Revenue: ${revenue['monthly']:,.0f}/mo ({revenue['yoyChange']}% YoY). "
        f"Sentiment: {sentiment['score']}/5. Trend: {bsr['trend'].capitalize()}."
    )

    return {
        "asin": asin_code.upper(),
        "revenue_data": revenue,
        "bsr_trend": bsr,
        "sentiment_analysis": sentiment,
        "curated_summary": summary,
        "data_freshness": asin_obj.last_ingested_at.isoformat() if asin_obj.last_ingested_at else "stale",
    }


@mcp.tool(
    meta={
        "surface": "both",
        "queryEligible": True,
        "latencyClass": "fast",
        "pricing": {"executeUsd": EXECUTE_PRICE_INTEL},
        "rateLimit": DJANGO_RATE_LIMIT,
    },
)
def find_market_opportunities(limit: int = 10) -> dict:
    """TIER 1 INTELLIGENCE: Top underserved Amazon niches.

    Ranks niches by opportunity score (profitability × inverse-saturation ×
    demand growth). Pair with `browse_by_category` to list live ASINs inside
    a returned niche.

    Args:
        limit: Number of niches to return (1–50).
    """
    # Scores are pre-computed by the Celery task `calculate_opportunity_scores`.
    # Do NOT recompute here — it triggers full DB aggregation on every call.
    scores = OpportunityScore.objects.all().order_by("-total_score")[: max(1, min(limit, 50))]

    from django.utils import timezone
    opportunities = [
        {
            "niche": s.niche_name,
            "opportunity_score": s.total_score,
            "profitability": s.profitability_index,
            "competition_index": s.competition_index,
            "demand_growth_pct": s.demand_growth_pct,
            "recommendation": s.recommendation,
        }
        for s in scores
    ]
    return {
        "opportunities": opportunities,
        "total_count": len(opportunities),
        "timestamp": timezone.now().isoformat()
    }


@mcp.tool(
    meta={
        "surface": "both",
        "queryEligible": True,
        "latencyClass": "fast",
        "pricing": {"executeUsd": EXECUTE_PRICE_INTEL},
        "rateLimit": DJANGO_RATE_LIMIT,
    },
)
def get_trending_products(limit: int = 10, category: str = None) -> dict:
    """TIER 1 INTELLIGENCE: Products with rising BSR momentum.

    Returns ASINs experiencing rapid BSR improvement ranked by velocity score.
    Feed each ASIN into `get_product_intelligence` for a deeper read-out.

    Args:
        limit: Number of trending products to return (1–50).
    """
    trending = (
        TrendingProduct.objects
        .filter(is_active=True)
        .select_related("asin")
        [: max(1, min(limit, 50))]
    )
    from django.utils import timezone
    rows = [
        {
            "asin": t.asin.asin,
            "title": t.asin.title,
            "velocity_score": t.velocity_score,
            "improvement_pct": t.bsr_change_pct,
            "current_bsr": t.asin.current_bsr,
        }
        for t in trending
    ]
    return {
        "trending": rows,
        "total_count": len(rows),
        "timestamp": timezone.now().isoformat()
    }


# ── Discovery layer ─────────────────────────────────────────────────────────

@mcp.tool(
    meta={
        "surface": "both",
        "queryEligible": True,
        "latencyClass": "instant",
        "pricing": {"executeUsd": EXECUTE_PRICE_DISCOVERY},
        "rateLimit": DJANGO_RATE_LIMIT,
    },
)
def get_all_categories(limit: int = 100) -> dict:
    """DISCOVERY: List ALL Amazon categories in the index.

    Returns `{id, name, slug}` tuples. Required before calling
    `browse_by_category` — otherwise the agent can only reach
    trending/popular items and misses the full surface area.
    """
    qs = Category.objects.all().order_by("name")[: max(1, min(limit, 500))]
    from django.utils import timezone
    categories = [
        {"id": c.amazon_id, "name": c.name, "slug": c.amazon_id}
        for c in qs
    ]
    return {
        "categories": categories,
        "total_count": len(categories),
        "timestamp": timezone.now().isoformat()
    }


@mcp.tool(
    meta={
        "surface": "both",
        "queryEligible": True,
        "latencyClass": "instant",
        "pricing": {"executeUsd": EXECUTE_PRICE_DISCOVERY},
        "rateLimit": DJANGO_RATE_LIMIT,
    },
)
def browse_by_category(category_id: str, limit: int = 25) -> dict:
    """DISCOVERY: ASINs inside a specific category, sorted by BSR.

    Use the `category_id` returned by `get_all_categories`. Returned ASINs
    are ready inputs for `get_product_intelligence`.
    """
    try:
        category = Category.objects.get(amazon_id=category_id)
    except Category.DoesNotExist:
        return {"error": f"Unknown category '{category_id}'. Call get_all_categories first."}

    qs = (
        ASIN.objects
        .filter(category=category)
        .exclude(current_bsr__isnull=True)
        .order_by("current_bsr")
        [: max(1, min(limit, 100))]
    )
    items = [
        {
            "asin": a.asin,
            "title": a.title,
            "current_bsr": a.current_bsr,
            "current_price": float(a.current_price) if a.current_price is not None else None,
            "current_rating": a.current_rating,
        }
        for a in qs
    ]
    return {"category_id": category_id, "items": items, "total_count": len(items)}


if __name__ == "__main__":
    mcp.run(transport="http", port=int(os.getenv("PORT", "3000")))
