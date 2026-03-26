import os
import httpx
import re
import json
import logging
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent, EmbeddedContent
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from ctxprotocol import verify_context_request, is_protected_mcp_method, ContextError
import uvicorn

logger = logging.getLogger(__name__)

# ── Configuration ───────────────────────────────────────────────────────────
BACKEND_URL = os.getenv("BACKEND_URL", "http://web:5000")
TIMEOUT = 55.0  # Under the 60s Context Protocol limit
PORT = int(os.getenv("PORT", "3000"))

# ── Regex ───────────────────────────────────────────────────────────────────
ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
AMAZON_URL_RE = re.compile(r"/dp/([A-Z0-9]{10})")

# ── Initialize MCP Server ───────────────────────────────────────────────────
server = Server("Amazon Intelligence Proxy")


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return [
        Tool(
            name="amazon_product_intelligence",
            description=(
                "Returns BSR trends, estimated monthly revenue, and NLP review sentiment "
                "for any Amazon product ASIN. Replaces Jungle Scout ($500/yr) for "
                "on-demand product intelligence."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Amazon ASIN (e.g. B09G9HD6PD) or full Amazon product URL"
                    }
                },
                "required": ["identifier"]
            },
            outputSchema={
                "type": "object",
                "properties": {
                    "asin": {"type": "string"},
                    "revenue_data": {
                        "type": "object",
                        "properties": {
                            "monthly": {"type": "number"},
                            "yoyChange": {"type": "number"},
                            "currency": {"type": "string"}
                        }
                    },
                    "bsr_trend": {
                        "type": "object",
                        "properties": {
                            "current": {"type": "number"},
                            "trend": {"type": "string"},
                            "velocity": {"type": "number"}
                        }
                    },
                    "sentiment_analysis": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "number"},
                            "themes": {"type": "array", "items": {"type": "string"}}
                        }
                    },
                    "curated_summary": {"type": "string"}
                }
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[TextContent]:
    if name != "amazon_product_intelligence":
        raise ValueError(f"Unknown tool: {name}")

    identifier = (arguments or {}).get("identifier", "").strip()

    # Normalize to ASIN
    asin = ""
    if ASIN_RE.match(identifier.upper()):
        asin = identifier.upper()
    elif match := AMAZON_URL_RE.search(identifier):
        asin = match.group(1).upper()
    else:
        return [TextContent(type="text", text="Error: Invalid ASIN or URL format.")]

    url = f"{BACKEND_URL}/v1/product/intelligence"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            response = await client.post(url, json={"asin": asin})

            if response.status_code == 202:
                return [TextContent(
                    type="text",
                    text="This ASIN is being analysed for the first time. Retry in 30 seconds."
                )]

            if response.status_code == 200:
                data = response.json()
                return [
                    TextContent(type="text", text=json.dumps(data, indent=2)),
                    EmbeddedContent(type="embedded", data=data)  # structuredContent
                ]

            return [TextContent(
                type="text",
                text=f"Backend Error ({response.status_code}): {response.text}"
            )]

        except httpx.TimeoutException:
            return [TextContent(type="text", text="Error: Backend request timed out.")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]


# ── SSE HTTP Transport ──────────────────────────────────────────────────────

def create_app() -> Starlette:
    sse = SseServerTransport("/messages")

    async def handle_sse(request: Request) -> Response:
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
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

    async def handle_messages(request: Request) -> Response:
        body = await request.json()
        if is_protected_mcp_method(body.get("method", "")):
            try:
                await verify_context_request(
                    authorization_header=request.headers.get("authorization", "")
                )
            except ContextError as e:
                return JSONResponse(
                    {"error": f"Unauthorized: {e.message}"}, 
                    status_code=401
                )
        await sse.handle_post_message(request.scope, request.receive, request._send)

    async def handle_health(request: Request) -> Response:
        return Response("ok", media_type="text/plain")

    return Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Route("/messages", endpoint=handle_messages, methods=["POST"]),
            Route("/health", endpoint=handle_health),
        ]
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=PORT)
