import os
import httpx
import re
import asyncio
from typing import Dict, Any, List
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.types import Tool, TextContent, CallToolRequest, CallToolResult
import mcp.server.stdio

# ── Configuration ───────────────────────────────────────────────────────────
BACKEND_URL = os.getenv("BACKEND_URL", "http://web:8000")
TIMEOUT = 25.0

# ── Regex ───────────────────────────────────────────────────────────────────
ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
AMAZON_URL_RE = re.compile(r"/dp/([A-Z0-9]{10})")

# ── Initialize MCP Server ───────────────────────────────────────────────────
server = Server("Amazon Intelligence Proxy")

@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """
    List available tools. 
    Includes strict Tier S metadata for Context Protocol.
    """
    return [
        Tool(
            name="amazon_product_intelligence",
            description="Returns BSR trends, estimated monthly revenue, and NLP review sentiment for any Amazon product ASIN. Replaces Jungle Scout ($500/yr) for on-demand product intelligence.",
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Amazon ASIN or product URL"
                    }
                },
                "required": ["identifier"]
            },
            # PROTOCOL SPECIFIC: The _meta block for marketplace tiering
            _meta={
                "surface": "query",
                "queryEligible": True,
                "responsePrice": 0,
                "category": "ecommerce",
                # The prompt requested the full outputSchema here
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "asin": {"type": "string"},
                        "title": {"type": "string"},
                        "brand": {"type": "string"},
                        "category": {"type": "string"},
                        "imageUrl": {"type": "string"},
                        "estimatedRevenue": {
                            "type": "object",
                            "properties": {
                                "monthly": {"type": "number"},
                                "yoyChange": {"type": "number"},
                                "confidence": {"type": "number"}
                            }
                        },
                        "sentiment": {"type": "object"},
                        "bsrTrend": {"type": "object"},
                        "summary": {"type": "string"}
                    }
                }
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[TextContent]:
    """
    Handle tool execution calls. 
    Proxies requests to the Django REST API.
    """
    if name != "amazon_product_intelligence":
        raise ValueError(f"Unknown tool: {name}")

    identifier = (arguments or {}).get("identifier", "").strip()
    
    # Normalize ASIN
    asin = ""
    if ASIN_RE.match(identifier.upper()):
        asin = identifier.upper()
    elif match := AMAZON_URL_RE.search(identifier):
        asin = match.group(1).upper()
    else:
        return [TextContent(type="text", text="Error: Invalid ASIN or URL format.")]

    # Proxy to Backend
    url = f"{BACKEND_URL}/v1/product/intelligence"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            response = await client.post(url, json={"asin": asin})
            
            if response.status_code == 202:
                return [TextContent(type="text", text="This ASIN is being analysed for the first time. Retry in 30 seconds.")]
            
            if response.status_code == 200:
                # Return raw JSON as a string for the data pass-through
                import json
                return [TextContent(type="text", text=json.dumps(response.json(), indent=2))]
            
            return [TextContent(type="text", text=f"Backend Error ({response.status_code}): {response.text}")]
            
        except httpx.TimeoutException:
            return [TextContent(type="text", text="Error: Backend request timed out.")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]

async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="amazon_intelligence_proxy",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())
