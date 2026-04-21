# Amazon Intelligence — Context Protocol MCP Server

Tier-S curated Amazon intelligence for the [Context Protocol](https://ctxprotocol.com)
marketplace. Replaces the core Jungle Scout ($500/yr) workflow with on-demand
BSR trends, estimated monthly revenue, and NLP review sentiment — priced
pay-per-response on the Query surface and pay-per-call on the Execute surface.

## Runtime variants

| File | When to use | Transport |
| :--- | :--- | :--- |
| `mcp_proxy.py` | Production. Thin proxy into the Django REST backend. | SSE (`/sse` + `/messages`) |
| `mcp_server.py` | Co-located FastMCP server. Runs inside the Django process. | HTTP streaming (`/mcp`) |

Both servers expose the same tool surface and the same Context Protocol
metadata. `mcp_proxy.py` is the one wired into `Dockerfile.mcp`.

## Dual-surface contract

Every method declares `_meta` so the listing is visible on **both** surfaces:

| Field | Purpose |
| :--- | :--- |
| `surface` | `"answer"`, `"execute"`, or `"both"` |
| `queryEligible` | `true` if safe for managed Query synthesis |
| `latencyClass` | `"instant"`, `"fast"`, `"slow"`, `"streaming"` |
| `pricing.executeUsd` | Per-call price on the Execute surface |
| `rateLimit` | Upstream rate-limit hints for the managed runtime |

Without `pricing.executeUsd`, a method is invisible to Execute-mode SDK
consumers. Every method in this server sets it explicitly.

### Pricing (guidance is ~1/100 of the listing response price)

| Method | Surface | Execute price |
| :--- | :--- | :--- |
| `amazon_product_intelligence` | both | `$0.001` |
| `find_market_opportunities` | both | `$0.001` |
| `amazon_trending_products` | both | `$0.001` |
| `get_bsr_history` | execute | `$0.0005` |
| `get_all_categories` | both | `$0.0002` |
| `browse_by_category` | both | `$0.0002` |

Set the **listing response price** (Query surface) in the marketplace
Contribute form — `$0.10` per response is the recommended starting point for
this class of intelligence tool.

## Tool architecture

```
┌─────────────────────────────────────────────────────────────┐
│  TIER 1 — INTELLIGENCE (Query-first, synthesised)           │
│  amazon_product_intelligence · find_market_opportunities     │
│  amazon_trending_products                                    │
├─────────────────────────────────────────────────────────────┤
│  TIER 2 — RAW DATA (Execute-first, normalised)              │
│  get_bsr_history                                             │
├─────────────────────────────────────────────────────────────┤
│  DISCOVERY LAYER (enumerate full surface area)              │
│  get_all_categories → browse_by_category → ASIN             │
└─────────────────────────────────────────────────────────────┘
```

Typical agent workflow: `get_all_categories → browse_by_category →
amazon_product_intelligence`.

## Setup

### Prerequisites
- Python 3.10+
- Running Django backend (see `docker-compose.yml`)

### Environment
| Var | Default | Description |
| :--- | :--- | :--- |
| `BACKEND_URL` | `http://web:5000` | Django REST API base URL |
| `PORT` | `3000` | MCP server port |

### Run locally
```bash
pip install -r requirements.txt
python mcp_proxy.py
```

### Docker
```bash
docker build -t amazon-intel-mcp -f Dockerfile.mcp .
docker run -e BACKEND_URL=http://your-backend:8000 -p 3000:3000 amazon-intel-mcp
```

## Test prompts (must-win)

1. **"What is the estimated monthly revenue for B09G9HD6PD?"** — exercises
   `amazon_product_intelligence.estimatedRevenue.monthly` + `confidence`.
2. **"Is `https://www.amazon.com/dp/B08N5WRWNW` growing or declining?"** —
   exercises `bsrTrend.trend` + `yoyChange`.
3. **"What are customers complaining about most for B07XJ8C8F5?"** —
   exercises `sentiment.negativeThemes`.
4. **"Find underserved Amazon niches with high profitability."** —
   exercises `find_market_opportunities`.
5. **"Which Amazon products have the strongest BSR momentum right now?"** —
   exercises `amazon_trending_products`.
6. **"List all available Amazon categories, then show me the top ASINs in
   `electronics`."** — exercises the discovery layer
   (`get_all_categories` → `browse_by_category`).

## Security

`mcp_proxy.py` wraps the protected MCP methods with
`ctxprotocol.verify_context_request`; `mcp_server.py` does the same via a
FastMCP middleware. Discovery methods (`initialize`, `tools/list`, etc.) are
intentionally left open so agents can enumerate the schema before paying.

---
*Context Protocol marketplace — Amazon Intelligence contributor.*
