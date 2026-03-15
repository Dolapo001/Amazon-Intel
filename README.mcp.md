# Amazon Intelligence MCP Proxy

Tier S Curated Intelligence tool for the [Context Protocol](https://ctxprotocol.com) marketplace. Replaces **Jungle Scout ($500/yr)** by providing on-demand BSR trends, estimated monthly revenue, and NLP review sentiment.

## 🚀 Overview
This MCP server acts as a thin proxy for a Django REST backend. It fetches, normalizes, and validates product intelligence data, ensuring it meets the Context Protocol 30-second response time and schema validation requirements.

## 🛠 Setup

### Prerequisites
- Python 3.10+
- A running Django REST backend (see main project Docker setup)

### Environment Variables
- `BACKEND_URL`: URL of the Django REST API (default: `http://localhost:8000`)
- `PORT`: Port to run the MCP server (default: `3000`)

### Installation & Run
```bash
# Install dependencies
pip install mcp httpx

# Run the server
python mcp_proxy.py
```

### Docker
```bash
docker build -t amazon-intel-mcp -f Dockerfile.mcp .
docker run -e BACKEND_URL=http://your-backend:8000 -p 3000:3000 amazon-intel-mcp
```

## 🔍 Test Questions (for Grant Submission)

Include these in your grant review email to verify Tier S functionality:

1. **"What is the estimated monthly revenue for B09G9HD6PD?"**
   - *Expected Response*: Full intelligence report containing `estimatedRevenue.monthly` and a confidence score.
2. **"Is https://www.amazon.com/dp/B08N5WRWNW a growing or declining product?"**
   - *Expected Response*: `bsrTrend.trend` (improving/declining) and `yoyChange`.
3. **"What are customers complaining about most for ASIN B07XJ8C8F5?"**
   - *Expected Response*: Curated `sentiment.negativeThemes` (e.g., "durability", "battery life").
4. **"Give me a full intelligence report on B09XYZ1234"**
   - *Expected Response*: The rule-based `summary` field synthesizing all data points.
5. **"What is the sentiment score and review velocity for B08F7N3XMB?"**
   - *Expected Response*: `sentiment.score` (e.g., 4.2) and `reviewVelocity` (average reviews per day).

## 📄 Schema Validation
The server enforces a strict JSON schema for the `amazon_product_intelligence` tool, ensuring reliable synthesis for AI agents.

| Field | Type | Description |
| :--- | :--- | :--- |
| `estimatedRevenue` | Object | Monthly USD estimate + YoY % change |
| `sentiment` | Object | NLP aggregate score + extracted themes |
| `bsrTrend` | Object | Rank delta and historical movement |
| `summary` | String | Synthesis of key insights |

---
*Created for the Context Protocol Marketplace.*
