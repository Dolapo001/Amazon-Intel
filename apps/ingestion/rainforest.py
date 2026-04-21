"""
Rainforest API client — a reliable alternative to Apify.

Advantages:
  1. Pay-per-success pricing (no lost credits on CAPTCHAs).
  2. Clean JSON structure (less parsing logic).
  3. Built-in support for Search, Reviews, and Product data in one API.

Public interface (matches scraper.py):
  fetch_product(asin)            → tuple[dict, list[dict]]
  fetch_reviews(asin, max_count) → list[dict]
  fetch_search(query)            → list[dict]
"""
import logging
from typing import Optional, Any

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.rainforestapi.com/request"
_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_CLIENT = httpx.Client(timeout=_TIMEOUT)


def fetch_product(asin: str, country: str = "US") -> tuple[Optional[dict], list[dict]]:
    """
    Fetch product details and reviews in a single call.
    Rainforest's 'product' type often includes top reviews.
    """
    api_key = _get_api_key()
    if not api_key:
        return None, []

    params = {
        "api_key": api_key,
        "type": "product",
        "amazon_domain": _get_domain(country),
        "asin": asin,
        "include_reviews": "true"
    }

    try:
        resp = _CLIENT.get(_BASE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("request_info", {}).get("success"):
            logger.error(f"Rainforest product request failed for ASIN {asin}")
            return None, []

        product_data = data.get("product", {})
        parsed_product = _parse_product(product_data)
        
        # Parse reviews if present
        raw_reviews = data.get("reviews", [])
        parsed_reviews = [_parse_review(r) for r in raw_reviews]

        return parsed_product, parsed_reviews

    except Exception as exc:
        logger.exception(f"Rainforest fetch_product error (asin={asin}): {exc}")
        return None, []


def fetch_reviews(asin: str, max_count: int = 100, country: str = "US") -> list[dict]:
    """
    Dedicated reviews fetcher for deep scraping.
    """
    api_key = _get_api_key()
    if not api_key:
        return []

    params = {
        "api_key": api_key,
        "type": "reviews",
        "amazon_domain": _get_domain(country),
        "asin": asin,
        "page": 1,
        "sort_by": "most_recent"
    }

    results = []
    try:
        # Simple single-page fetch for now. Rainforest supports pagination.
        resp = _CLIENT.get(_BASE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        
        raw_reviews = data.get("reviews", [])
        results = [_parse_review(r) for r in raw_reviews]
        
    except Exception as exc:
        logger.error(f"Rainforest fetch_reviews error (asin={asin}): {exc}")

    return results[:max_count]


def fetch_search(query: str, country: str = "US") -> list[dict]:
    """
    Search Amazon and return a list of products. 
    Great for discovering new ASINs in a niche.
    """
    api_key = _get_api_key()
    if not api_key:
        return []

    params = {
        "api_key": api_key,
        "type": "search",
        "amazon_domain": _get_domain(country),
        "search_term": query
    }

    try:
        resp = _CLIENT.get(_BASE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        
        search_results = data.get("search_results", [])
        return [_parse_product(item) for item in search_results]
    except Exception as exc:
        logger.error(f"Rainforest search error (query={query}): {exc}")
        return []


# ── Parsers ───────────────────────────────────────────────────────────────────

def _parse_product(item: dict) -> Optional[dict]:
    """
    Normalise Rainforest JSON to internal shape.
    """
    if not item:
        return None

    # Handle BSR: Rainforest returns a list under best_sellers_rank
    bsr_list = item.get("bestsellers_rank", [])
    current_bsr = None
    if bsr_list and isinstance(bsr_list, list):
        current_bsr = bsr_list[0].get("rank")

    # Handle Categories
    categories = item.get("categories", [])
    category_name = categories[-1].get("name") if categories else "Unknown"
    category_id = category_name.lower().replace("&", "and").replace(" ", "_").strip() if category_name else "unknown"

    # Handle Price
    price_info = item.get("buybox_winner", {}).get("price", {}) or item.get("price", {})
    price = price_info.get("value")

    return {
        "asin":                 item.get("asin"),
        "title":                item.get("title", ""),
        "brand":                item.get("brand", ""),
        "category_id":          category_id,
        "category_name":        category_name,
        "image_url":            item.get("main_image", {}).get("link") or item.get("image", ""),
        "current_bsr":          int(current_bsr) if current_bsr else None,
        "current_price":        float(price) if price else None,
        "current_rating":       float(item.get("rating", 0)) or None,
        "current_review_count": int(item.get("ratings_total", 0)) or None,
        "bsr_series":           [],
    }


def _parse_review(item: dict) -> dict:
    """
    Normalise Rainforest review JSON.
    """
    return {
        "text":     item.get("body") or item.get("text", ""),
        "rating":   int(item.get("rating", 3)),
        "date":     item.get("date", {}).get("utc") or item.get("date", ""),
        "verified": bool(item.get("verified_purchase", False)),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_api_key() -> Optional[str]:
    key = getattr(settings, "RAINFOREST_API_KEY", "")
    if not key:
        logger.error("RAINFOREST_API_KEY not configured in .env")
    return key or None


def _get_domain(country_code: str) -> str:
    domains = {
        "US": "amazon.com",
        "GB": "amazon.co.uk",
        "DE": "amazon.de",
        "FR": "amazon.fr",
        "CA": "amazon.ca"
    }
    return domains.get(country_code.upper(), "amazon.com")
