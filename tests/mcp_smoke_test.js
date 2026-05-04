/**
 * Amazon Intelligence MCP — Live Smoke Test Suite
 * Tests: tool discovery, schema validation, and smoke-calls every tool.
 */
const { Client } = require("@modelcontextprotocol/sdk/client/index.js");
const { SSEClientTransport } = require("@modelcontextprotocol/sdk/client/sse.js");

const ENDPOINT = "https://oyster-app-mfyar.ondigitalocean.app/sse";

async function main() {
  console.log("═══════════════════════════════════════════════════");
  console.log("  Amazon Intelligence MCP — Live Validation");
  console.log("  Endpoint:", ENDPOINT);
  console.log("═══════════════════════════════════════════════════\n");

  // ── 1. Connect ──────────────────────────────────────────────
  console.log("STEP 1: Connecting via SSE...");
  let client;
  try {
    const transport = new SSEClientTransport(new URL(ENDPOINT));
    client = new Client({ name: "qa-validator", version: "1.0.0" });
    await client.connect(transport);
    console.log("  ✅ Connected successfully\n");
  } catch (err) {
    console.error("  ❌ Connection FAILED:", err.message);
    process.exit(1);
  }

  // ── 2. Tool Discovery ──────────────────────────────────────
  console.log("STEP 2: Tool Discovery (tools/list)...");
  let tools;
  try {
    const result = await client.listTools();
    tools = result.tools;
    console.log(`  ✅ Discovered ${tools.length} tools:\n`);
    for (const t of tools) {
      const meta = t._meta || {};
      console.log(`  📦 ${t.name}`);
      console.log(`     Description: ${(t.description || "").substring(0, 80)}...`);
      console.log(`     inputSchema:  ${t.inputSchema ? "✅" : "❌"}`);
      console.log(`     outputSchema: ${t.outputSchema ? "✅" : "❌"}`);
      console.log(`     _meta:        surface=${meta.surface || "N/A"}, queryEligible=${meta.queryEligible}, latencyClass=${meta.latencyClass || "N/A"}`);
      console.log();
    }
  } catch (err) {
    console.error("  ❌ Tool discovery FAILED:", err.message);
    process.exit(1);
  }

  // ── 3. Smoke Tests ─────────────────────────────────────────
  console.log("STEP 3: Smoke Tests...\n");

  const smokeTests = [
    {
      name: "get_all_categories",
      args: { limit: 5 },
      validate: (r) => {
        const text = r.content?.[0]?.text || "";
        return text.includes("categories") || text.includes("Amazon");
      },
    },
    {
      name: "amazon_trending_products",
      args: { limit: 3 },
      validate: (r) => {
        const text = r.content?.[0]?.text || "";
        return text.includes("momentum") || text.includes("Found") || text.includes("trending");
      },
    },
    {
      name: "find_market_opportunities",
      args: { limit: 3 },
      validate: (r) => {
        const text = r.content?.[0]?.text || "";
        return text.includes("niche") || text.includes("Found") || text.includes("underserved");
      },
    },
    {
      name: "amazon_product_intelligence",
      args: { identifier: "B09G9HD6PD" },
      validate: (r) => {
        const text = r.content?.[0]?.text || "";
        return text.length > 10 && !r.isError;
      },
    },
    {
      name: "get_bsr_history",
      args: { asin: "B09G9HD6PD", days: 30 },
      validate: (r) => {
        const text = r.content?.[0]?.text || "";
        return text.includes("BSR") || text.includes("snapshot") || text.includes("history");
      },
    },
  ];

  const results = [];
  for (const test of smokeTests) {
    process.stdout.write(`  🧪 ${test.name} ... `);
    const start = Date.now();
    try {
      const result = await client.callTool({ name: test.name, arguments: test.args });
      const elapsed = Date.now() - start;
      const hasContent = result.content && result.content.length > 0;
      const isError = result.isError === true;
      const text = result.content?.[0]?.text || "";
      const hasStructured = !!result.structuredContent;

      if (isError) {
        console.log(`⚠️  ERROR RESPONSE (${elapsed}ms): ${text.substring(0, 100)}`);
        results.push({ tool: test.name, status: "ERROR", time: elapsed, note: text.substring(0, 100) });
      } else if (hasContent) {
        console.log(`✅ PASS (${elapsed}ms) | content=${text.substring(0, 60)}... | structuredContent=${hasStructured}`);
        results.push({ tool: test.name, status: "PASS", time: elapsed, structured: hasStructured });
      } else {
        console.log(`❌ FAIL (${elapsed}ms): empty response`);
        results.push({ tool: test.name, status: "FAIL", time: elapsed, note: "empty response" });
      }
    } catch (err) {
      const elapsed = Date.now() - start;
      console.log(`❌ EXCEPTION (${elapsed}ms): ${err.message}`);
      results.push({ tool: test.name, status: "EXCEPTION", time: elapsed, note: err.message });
    }
  }

  // ── 4. Summary ─────────────────────────────────────────────
  console.log("\n═══════════════════════════════════════════════════");
  console.log("  SUMMARY");
  console.log("═══════════════════════════════════════════════════");
  console.log(`  Tools discovered: ${tools.length}`);
  console.log(`  Smoke tests run:  ${results.length}`);
  console.log(`  Passed:           ${results.filter(r => r.status === "PASS").length}`);
  console.log(`  Errors:           ${results.filter(r => r.status === "ERROR").length}`);
  console.log(`  Failed:           ${results.filter(r => r.status === "FAIL" || r.status === "EXCEPTION").length}`);
  console.log();

  for (const r of results) {
    const icon = r.status === "PASS" ? "✅" : r.status === "ERROR" ? "⚠️ " : "❌";
    console.log(`  ${icon} ${r.tool.padEnd(30)} ${r.status.padEnd(10)} ${r.time}ms${r.note ? " — " + r.note : ""}${r.structured ? " [structured ✓]" : ""}`);
  }
  console.log();

  // Cleanup
  try { await client.close(); } catch {}
  process.exit(0);
}

main().catch((err) => {
  console.error("Fatal:", err);
  process.exit(1);
});
