"""
Amazon Intelligence MCP proxy.

Thin MCP server that proxies into the Django REST backend. Aligned with the
Context Protocol marketplace contract:

  * Dual-surface ready: Query (pay-per-response) + Execute (pay-per-call)
  * Every method declares `_meta.surface`, `queryEligible`, `latencyClass`,
    `pricing.executeUsd`, and `rateLimit`
  * Every method publishes an `outputSchema`; every response includes
    `structuredContent` so agents can consume typed output
  * Input schemas use standard JSON Schema `default` / `examples` hints so the
    runtime can generate valid arguments on first pass
  * Discovery-layer tools (`get_all_categories`, `browse_by_category`) so
    agents can enumerate the full surface area, not just trending items
"""
import json
import logging
import os
import re
import sys

import httpx
import uvicorn
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

# ctxprotocol is optional — if not installed, JWT verification is skipped
# (useful for local testing; must be installed for production marketplace use)
try:
    from ctxprotocol import ContextError, is_protected_mcp_method, verify_context_request
    # Allow disabling auth via env var for testing (e.g. MCP Inspector)
    _HAS_CTX = os.getenv("DISABLE_AUTH") != "1"
    if not _HAS_CTX:
        logging.warning("DISABLE_AUTH=1 detected — JWT verification disabled")
except ImportError:
    _HAS_CTX = False
    logging.warning("ctxprotocol not installed — JWT verification disabled")

logger = logging.getLogger(__name__)

# ── Configuration ───────────────────────────────────────────────────────────
BACKEND_URL = os.getenv("BACKEND_URL", "http://web:5000")
TIMEOUT = 55.0  # Under the 60s Context Protocol limit
PORT = int(os.getenv("PORT", "3000"))

# ── Regex ───────────────────────────────────────────────────────────────────
ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
AMAZON_URL_RE = re.compile(r"/dp/([A-Z0-9]{10})")

# ── Marketplace pricing / rate-limit metadata ───────────────────────────────
# Listing response price (Query surface) is set in the marketplace UI.
# Execute prices below are per method call, ~1/100 of the listing response
# price per the Context Protocol pricing guidance.
EXECUTE_PRICE_INTEL = "0.001"   # synthesised intelligence (paid call)
EXECUTE_PRICE_RAW = "0.0005"    # normalised raw data
EXECUTE_PRICE_DISCOVERY = "0.0002"  # enumeration / listing

BACKEND_RATE_LIMIT = {
    "maxRequestsPerMinute": 60,
    "cooldownMs": 1000,
    "maxConcurrency": 5,
    "supportsBulk": False,
    "notes": "Backend serves L1 (Redis) cache hits instantly; cold ASINs trigger synchronous ingest.",
}

# ── Initialize MCP Server ───────────────────────────────────────────────────
server = Server("Amazon Intelligence Proxy")


def _tool(**kwargs) -> Tool:
    """Build a Tool instance that preserves `_meta` through the MCP wire format.

    The pydantic model on recent mcp SDK versions aliases `meta` ↔ `_meta`.
    Using `model_validate` round-trips the `_meta` key regardless of whether
    the installed version exposes it as a declared field or as an extra.
    """
    return Tool.model_validate(kwargs)


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return [
        # ── Tier 1: Intelligence (synthesised, Query-first) ────────────────
        _tool(
            name="amazon_product_intelligence",
            description=(
                "TIER 1 INTELLIGENCE: Full Amazon product report for a single ASIN. "
                "Synthesises BSR trend, estimated monthly revenue (with YoY delta), "
                "and NLP-derived sentiment + positive/negative themes into a single "
                "curated payload. Replaces the core Jungle Scout ($500/yr) workflow "
                "for on-demand product intelligence.\n\n"
                "DATA FLOW:\n"
                "  amazon_product_intelligence → revenue_estimate + bsr_trend + review_analysis\n\n"
                "COMPOSABILITY:\n"
                "  Pair with browse_by_category to rank products inside a niche, or\n"
                "  with amazon_trending_products to spot momentum before synthesising."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Amazon ASIN (10 chars, e.g. 'B09G9HD6PD') or a full Amazon product URL (e.g. 'https://www.amazon.com/dp/B08N5WRWNW').",
                        "examples": [
                            "B09G9HD6PD",
                            "B08N5WRWNW",
                            "https://www.amazon.com/dp/B07XJ8C8F5",
                        ],
                    },
                },
                "required": ["identifier"],
            },
            outputSchema={
                "type": "object",
                "properties": {
                    "asin": {"type": "string"},
                    "title": {"type": "string"},
                    "brand": {"type": "string"},
                    "category": {"type": ["string", "null"]},
                    "estimatedRevenue": {
                        "type": "object",
                        "properties": {
                            "monthly": {"type": "number"},
                            "yoyChange": {"type": ["number", "null"]},
                            "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
                            "currency": {"type": "string", "enum": ["USD"]},
                        },
                    },
                    "bsrTrend": {
                        "type": "object",
                        "properties": {
                            "currentRank": {"type": ["integer", "null"]},
                            "yoyChange": {"type": ["number", "null"]},
                            "trend": {
                                "type": "string",
                                "enum": ["improving", "declining", "stable", "unknown"],
                            },
                        },
                    },
                    "sentiment": {
                        "type": "object",
                        "properties": {
                            "score": {"type": ["number", "null"], "minimum": 0, "maximum": 5},
                            "positiveThemes": {"type": "array", "items": {"type": "string"}},
                            "negativeThemes": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    "reviews": {
                        "type": "object",
                        "properties": {
                            "count": {"type": ["integer", "null"]},
                            "velocity": {"type": ["number", "null"]},
                        },
                    },
                    "curated_summary": {"type": "string"},
                    "data_freshness": {
                        "type": "string",
                        "enum": ["real-time", "near-real-time", "cached", "stale"],
                    },
                    "cacheHit": {"type": "boolean"},
                },
                "required": ["asin", "curated_summary"],
            },
            **{
                "_meta": {
                    "surface": "both",
                    "queryEligible": True,
                    "latencyClass": "fast",
                    "pricing": {"executeUsd": EXECUTE_PRICE_INTEL},
                    "rateLimit": BACKEND_RATE_LIMIT,
                },
            },
        ),

        # ── Tier 1: Intelligence (opportunity discovery) ───────────────────
        _tool(
            name="find_market_opportunities",
            description=(
                "TIER 1 INTELLIGENCE: Returns the top underserved Amazon niches ranked "
                "by an opportunity score (profitability × inverse-saturation × demand "
                "growth). Use this to unbundle costly seller-research subscriptions "
                "such as Helium 10 / Jungle Scout niche discovery.\n\n"
                "COMPOSABILITY:\n"
                "  Feed a returned niche into browse_by_category to list live ASINs,\n"
                "  then call amazon_product_intelligence on each for deep analysis."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of niches to return.",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50,
                        "examples": [5, 10, 25],
                    },
                },
                "required": [],
            },
            outputSchema={
                "type": "object",
                "properties": {
                    "opportunities": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "niche": {"type": "string"},
                                "opportunity_score": {"type": "number", "minimum": 0, "maximum": 100},
                                "profitability": {"type": "number"},
                                "competition_index": {"type": "number"},
                                "demand_growth_pct": {"type": ["number", "null"]},
                                "recommendation": {"type": "string"},
                            },
                        },
                    },
                    "total_count": {"type": "integer"},
                    "timestamp": {"type": "string", "format": "date-time"},
                },
                "required": ["opportunities", "total_count", "timestamp"],
            },
            **{
                "_meta": {
                    "surface": "both",
                    "queryEligible": True,
                    "latencyClass": "fast",
                    "pricing": {"executeUsd": EXECUTE_PRICE_INTEL},
                    "rateLimit": BACKEND_RATE_LIMIT,
                },
            },
        ),

        # ── Tier 1: Intelligence (trending momentum) ───────────────────────
        _tool(
            name="amazon_trending_products",
            description=(
                "TIER 1 INTELLIGENCE: Returns products experiencing rapid BSR improvement "
                "(positive momentum) over the detection window, ranked by velocity score. "
                "Use this to find rising ASINs before they hit best-seller lists.\n\n"
                "COMPOSABILITY:\n"
                "  Each result includes an ASIN — pipe into amazon_product_intelligence\n"
                "  for the deeper revenue / sentiment read-out."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of trending products to return.",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50,
                        "examples": [10, 25, 50],
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional Amazon category id/slug to filter by. Use get_all_categories to enumerate.",
                        "examples": ["electronics", "home-kitchen"],
                    },
                },
                "required": [],
            },
            outputSchema={
                "type": "object",
                "properties": {
                    "trending": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "asin": {"type": "string"},
                                "title": {"type": "string"},
                                "velocity_score": {"type": "number"},
                                "improvement_pct": {"type": "number"},
                                "current_bsr": {"type": ["integer", "null"]},
                            },
                        },
                    },
                    "total_count": {"type": "integer"},
                    "timestamp": {"type": "string", "format": "date-time"},
                },
                "required": ["trending", "total_count", "timestamp"],
            },
            **{
                "_meta": {
                    "surface": "both",
                    "queryEligible": True,
                    "latencyClass": "fast",
                    "pricing": {"executeUsd": EXECUTE_PRICE_INTEL},
                    "rateLimit": BACKEND_RATE_LIMIT,
                },
            },
        ),

        # ── Tier 2: Normalised raw data (Execute-first) ────────────────────
        _tool(
            name="get_bsr_history",
            description=(
                "TIER 2 RAW DATA: Daily BSR time-series for an ASIN. Returns a "
                "normalised array of {date, bsr, price} suitable for charting or "
                "downstream ML. Use when you need the raw series rather than the "
                "synthesised trend from amazon_product_intelligence."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "asin": {
                        "type": "string",
                        "pattern": "^[A-Z0-9]{10}$",
                        "description": "10-character Amazon ASIN.",
                        "examples": ["B09G9HD6PD", "B08N5WRWNW"],
                    },
                    "days": {
                        "type": "integer",
                        "description": "Lookback window in days.",
                        "default": 90,
                        "minimum": 1,
                        "maximum": 730,
                        "examples": [30, 90, 365],
                    },
                },
                "required": ["asin"],
            },
            outputSchema={
                "type": "object",
                "properties": {
                    "asin": {"type": "string"},
                    "days": {"type": "integer"},
                    "snapshots": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "date": {"type": "string", "format": "date"},
                                "bsr": {"type": "integer"},
                                "price": {"type": ["number", "null"]},
                            },
                            "required": ["date", "bsr"],
                        },
                    },
                    "timestamp": {"type": "string", "format": "date-time"},
                },
                "required": ["asin", "snapshots", "timestamp"],
            },
            **{
                "_meta": {
                    "surface": "execute",
                    "queryEligible": False,
                    "latencyClass": "fast",
                    "pricing": {"executeUsd": EXECUTE_PRICE_RAW},
                    "rateLimit": BACKEND_RATE_LIMIT,
                },
            },
        ),

        # ── Discovery layer: enumerate categories ──────────────────────────
        _tool(
            name="get_all_categories",
            description=(
                "DISCOVERY: List ALL Amazon categories known to the index. Returns "
                "{id, name, slug} tuples that can be passed to browse_by_category or "
                "amazon_trending_products.category. Use this before any browse call — "
                "otherwise you can only find trending/popular items, not the full surface.\n\n"
                "DATA FLOW:\n"
                "  get_all_categories → category_id → browse_by_category → ASINs → amazon_product_intelligence"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "default": 100,
                        "minimum": 1,
                        "maximum": 500,
                        "examples": [50, 100, 250],
                    },
                },
                "required": [],
            },
            outputSchema={
                "type": "object",
                "properties": {
                    "categories": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "name": {"type": "string"},
                                "slug": {"type": "string"},
                            },
                            "required": ["id", "name"],
                        },
                    },
                    "total_count": {"type": "integer"},
                    "timestamp": {"type": "string", "format": "date-time"},
                },
                "required": ["categories", "total_count", "timestamp"],
            },
            **{
                "_meta": {
                    "surface": "both",
                    "queryEligible": True,
                    "latencyClass": "instant",
                    "pricing": {"executeUsd": EXECUTE_PRICE_DISCOVERY},
                    "rateLimit": BACKEND_RATE_LIMIT,
                },
            },
        ),

        # ── Discovery layer: browse inside a category ──────────────────────
        _tool(
            name="browse_by_category",
            description=(
                "DISCOVERY: List ASINs inside a specific Amazon category, ranked by "
                "current BSR. Use the `category_id` returned by get_all_categories. "
                "Returned ASINs are ready inputs for amazon_product_intelligence."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "category_id": {
                        "type": "string",
                        "description": "Category id or slug from get_all_categories.",
                        "examples": ["electronics", "home-kitchen", "toys-games"],
                    },
                    "limit": {
                        "type": "integer",
                        "default": 25,
                        "minimum": 1,
                        "maximum": 100,
                        "examples": [10, 25, 50],
                    },
                },
                "required": ["category_id"],
            },
            outputSchema={
                "type": "object",
                "properties": {
                    "category_id": {"type": "string"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "asin": {"type": "string"},
                                "title": {"type": "string"},
                                "current_bsr": {"type": ["integer", "null"]},
                                "current_price": {"type": ["number", "null"]},
                                "current_rating": {"type": ["number", "null"]},
                            },
                            "required": ["asin"],
                        },
                    },
                    "total_count": {"type": "integer"},
                    "timestamp": {"type": "string", "format": "date-time"},
                },
                "required": ["category_id", "items", "total_count", "timestamp"],
            },
            **{
                "_meta": {
                    "surface": "both",
                    "queryEligible": True,
                    "latencyClass": "instant",
                    "pricing": {"executeUsd": EXECUTE_PRICE_DISCOVERY},
                    "rateLimit": BACKEND_RATE_LIMIT,
                },
            },
        ),
    ]


# ── Tool dispatch ───────────────────────────────────────────────────────────

def _err(message: str) -> dict:
    return {
        "content": [TextContent(type="text", text=message)],
        "isError": True,
    }


def _ok(summary: str, data) -> dict:
    """Return both a TextContent envelope and the structuredContent the
    Context Protocol requires for typed downstream consumption."""
    return {
        "content": [TextContent(type="text", text=summary)],
        "structuredContent": data,
    }


async def _call_backend(method: str, path: str, *, json_body: dict | None = None, params: dict | None = None) -> httpx.Response:
    url = f"{BACKEND_URL}{path}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        return await client.request(method, url, json=json_body, params=params)


def _normalise_asin(identifier: str) -> str | None:
    identifier = (identifier or "").strip()
    if ASIN_RE.match(identifier.upper()):
        return identifier.upper()
    m = AMAZON_URL_RE.search(identifier)
    if m:
        return m.group(1).upper()
    return None


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> dict:
    arguments = arguments or {}

    try:
        if name == "amazon_product_intelligence":
            asin = _normalise_asin(arguments.get("identifier", ""))
            if not asin:
                return _err("Error: Invalid ASIN or Amazon URL.")
            resp = await _call_backend("POST", "/v1/product/intelligence", json_body={"asin": asin})
            if resp.status_code == 202:
                return _err("This ASIN is being analysed for the first time. Retry in 30 seconds.")
            if resp.status_code != 200:
                return _err(f"Backend error ({resp.status_code}): {resp.text}")
            data = resp.json()
            summary = data.get("curated_summary") or f"Intelligence report for {asin}."
            return _ok(summary, data)

        if name == "find_market_opportunities":
            limit = int(arguments.get("limit", 10))
            resp = await _call_backend("GET", "/v1/analytics/opportunities/", params={"limit": limit})
            if resp.status_code != 200:
                return _err(f"Backend error ({resp.status_code}): {resp.text}")
            data = resp.json()
            summary = f"Found {data.get('total_count', 0)} underserved niches."
            return _ok(summary, data)

        if name == "amazon_trending_products":
            params = {"limit": int(arguments.get("limit", 10))}
            if "category" in arguments:
                params["category"] = arguments["category"]
            resp = await _call_backend("GET", "/v1/analytics/trending/", params=params)
            if resp.status_code != 200:
                return _err(f"Backend error ({resp.status_code}): {resp.text}")
            data = resp.json()
            summary = f"Found {data.get('total_count', 0)} products with rising momentum."
            return _ok(summary, data)

        if name == "get_bsr_history":
            asin = _normalise_asin(arguments.get("asin", ""))
            if not asin:
                return _err("Error: Invalid ASIN.")
            days = int(arguments.get("days", 90))
            resp = await _call_backend("GET", f"/v1/product/{asin}/bsr-history/", params={"days": days})
            if resp.status_code != 200:
                return _err(f"Backend error ({resp.status_code}): {resp.text}")
            data = resp.json()
            summary = f"BSR history for {asin}: {len(data.get('snapshots', []))} daily snapshots over {days}d."
            return _ok(summary, data)

        if name == "get_all_categories":
            limit = int(arguments.get("limit", 100))
            resp = await _call_backend("GET", "/v1/catalog/categories/", params={"limit": limit})
            if resp.status_code != 200:
                return _err(f"Backend error ({resp.status_code}): {resp.text}")
            data = resp.json()
            summary = f"{data.get('total_count', 0)} Amazon categories available."
            return _ok(summary, data)

        if name == "browse_by_category":
            category_id = (arguments.get("category_id") or "").strip()
            if not category_id:
                return _err("Error: category_id is required.")
            limit = int(arguments.get("limit", 25))
            resp = await _call_backend("GET", f"/v1/catalog/categories/{category_id}/items/", params={"limit": limit})
            if resp.status_code != 200:
                return _err(f"Backend error ({resp.status_code}): {resp.text}")
            data = resp.json()
            summary = f"{data.get('total_count', 0)} ASINs in category {category_id}."
            return _ok(summary, data)

        return _err(f"Unknown tool: {name}")

    except httpx.TimeoutException:
        return _err("Error: Backend request timed out.")
    except Exception as exc:  # noqa: BLE001 - surface upstream detail to the agent
        logger.exception("tool_call_failed", extra={"tool": name})
        return _err(f"Error: {exc}")


# ── SSE HTTP Transport ──────────────────────────────────────────────────────

def create_app() -> Starlette:
    sse = SseServerTransport("/messages")

    async def handle_sse(scope, receive, send):
        async with sse.connect_sse(scope, receive, send) as streams:
            await server.run(
                streams[0],
                streams[1],
                InitializationOptions(
                    server_name="amazon_intelligence_proxy",
                    server_version="1.0.0",
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )

    import uuid
    from mcp.shared.message import ServerMessageMetadata, SessionMessage
    from mcp import types

    async def handle_messages(request: Request) -> Response:
        # Only accept POST requests
        if request.method != "POST":
            return Response("Method Not Allowed", status_code=405)

        body_bytes = await request.body()
        try:
            import json
            body = json.loads(body_bytes)
        except Exception as e:
            str_headers = {k.decode("utf-8", "ignore"): v.decode("utf-8", "ignore") for k, v in request.headers.raw}
            return JSONResponse({
                "error": f"Proxy JSON Parse Error: {e}", 
                "raw_body": str(body_bytes[:200]),
                "method": request.method,
                "headers": str_headers
            }, status_code=400)

        # 1. JWT Verification
        if _HAS_CTX and is_protected_mcp_method(body.get("method", "")):
            try:
                await verify_context_request(request.headers.get("authorization", ""))
            except ContextError as e:
                return JSONResponse({"error": f"Unauthorized: {e.message}"}, status_code=401)

        # 2. Extract Session ID
        session_id_param = request.query_params.get("session_id")
        if not session_id_param:
            return Response("session_id is required", status_code=400)
        try:
            session_id = uuid.UUID(hex=session_id_param)
        except ValueError:
            return Response("Invalid session ID", status_code=400)

        # 3. Retrieve Stream Writer from SDK
        writer = sse._read_stream_writers.get(session_id)
        if not writer:
            return Response("Could not find session", status_code=404)

        # 4. Parse MCP Message
        try:
            from pydantic import TypeAdapter
            adapter = TypeAdapter(types.JSONRPCMessage)
            message = adapter.validate_json(body_bytes)
        except Exception as err:
            return Response(f"Could not parse message: {err}", status_code=400)

        # 5. Push to SDK
        # We send the unwrapped JSONRPCMessage directly to the server.run loop.
        await writer.send(message)

        return Response("Accepted", status_code=202)

    async def handle_health(request: Request) -> Response:
        return JSONResponse(
            {
                "status": "ok",
                "server": "amazon_intelligence_proxy",
                "version": "1.0.0",
                "backend": BACKEND_URL,
            }
        )

    from starlette.routing import Route, Mount
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Route("/messages", endpoint=handle_messages, methods=["POST"]),
            Route("/messages/", endpoint=handle_messages, methods=["POST"]),
            Route("/health", endpoint=handle_health),
        ],
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["*"],
                allow_headers=["*"],
            )
        ]
    )
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, force=True)
    logger.info("Starting Amazon Intelligence MCP Proxy")
    logger.info(f"  BACKEND_URL = {BACKEND_URL}")
    logger.info(f"  PORT        = {PORT}")
    logger.info(f"  ctxprotocol = {'enabled' if _HAS_CTX else 'DISABLED'}")
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=PORT)

