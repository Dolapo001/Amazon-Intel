"""
Tests for mcp_proxy.py — pure helper functions and the tool-list contract.

These tests do NOT require Django or a live backend; they verify:
  - _normalise_asin  — ASIN / URL / invalid input handling
  - _ok / _err       — response-envelope helpers
  - handle_list_tools — tool count, names, _meta presence, outputSchema shape
"""
import pytest
import asyncio
import re
import json


# ── Import helpers from proxy directly ──────────────────────────────────────

# We import from the module level without starting the MCP server.
import importlib.util, sys, os


def _load_proxy():
    """Load mcp_proxy.py without executing __main__."""
    spec = importlib.util.spec_from_file_location(
        "mcp_proxy_test",
        os.path.join(os.path.dirname(__file__), "..", "mcp_proxy.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def proxy():
    return _load_proxy()


# ── _normalise_asin ──────────────────────────────────────────────────────────

class TestNormaliseAsin:
    def test_valid_asin_uppercase(self, proxy):
        assert proxy._normalise_asin("B09XYZ1234") == "B09XYZ1234"

    def test_valid_asin_lowercase_normalised(self, proxy):
        assert proxy._normalise_asin("b09xyz1234") == "B09XYZ1234"

    def test_valid_asin_with_whitespace(self, proxy):
        assert proxy._normalise_asin("  B09XYZ1234  ") == "B09XYZ1234"

    def test_url_with_dp_segment(self, proxy):
        url = "https://www.amazon.com/dp/B08N5WRWNW/ref=sr_1_1"
        assert proxy._normalise_asin(url) == "B08N5WRWNW"

    def test_url_with_product_title(self, proxy):
        url = "https://www.amazon.com/Some-Product/dp/B07XJ8C8F5?th=1"
        assert proxy._normalise_asin(url) == "B07XJ8C8F5"

    def test_invalid_returns_none(self, proxy):
        assert proxy._normalise_asin("not-an-asin") is None

    def test_too_short_returns_none(self, proxy):
        assert proxy._normalise_asin("B09XY") is None

    def test_empty_string_returns_none(self, proxy):
        assert proxy._normalise_asin("") is None

    def test_none_string_returns_none(self, proxy):
        assert proxy._normalise_asin("None") is None


# ── _ok / _err ───────────────────────────────────────────────────────────────

class TestResponseHelpers:
    def test_ok_has_content_and_structured(self, proxy):
        result = proxy._ok("summary text", {"field": "value"})
        assert "content" in result
        assert result["structuredContent"] == {"field": "value"}
        assert result["content"][0].text == "summary text"

    def test_ok_content_is_text_type(self, proxy):
        result = proxy._ok("hello", {})
        assert result["content"][0].type == "text"

    def test_err_has_is_error_flag(self, proxy):
        result = proxy._err("something went wrong")
        assert result["isError"] is True

    def test_err_content_contains_message(self, proxy):
        result = proxy._err("backend timed out")
        assert result["content"][0].text == "backend timed out"

    def test_err_no_structured_content(self, proxy):
        result = proxy._err("oops")
        assert "structuredContent" not in result


# ── handle_list_tools contract ───────────────────────────────────────────────

# Required tool names the marketplace contract depends on.
EXPECTED_TOOLS = {
    "amazon_product_intelligence",
    "find_market_opportunities",
    "amazon_trending_products",
    "get_bsr_history",
    "get_all_categories",
    "browse_by_category",
}

# Required _meta keys per Context Protocol spec.
REQUIRED_META_KEYS = {"surface", "queryEligible", "latencyClass", "pricing", "rateLimit"}

VALID_LATENCY_CLASSES = {"instant", "fast", "slow", "streaming"}
VALID_SURFACES = {"answer", "execute", "both"}


@pytest.fixture(scope="module")
def tool_list(proxy):
    """Run handle_list_tools() and return the list synchronously."""
    return asyncio.get_event_loop().run_until_complete(proxy.handle_list_tools())


class TestListToolsContract:
    def test_all_expected_tools_present(self, tool_list):
        names = {t.name for t in tool_list}
        assert EXPECTED_TOOLS == names

    def test_no_unexpected_tools(self, tool_list):
        names = {t.name for t in tool_list}
        assert names == EXPECTED_TOOLS

    def test_every_tool_has_description(self, tool_list):
        for tool in tool_list:
            assert tool.description, f"{tool.name} has no description"
            assert len(tool.description) > 10, f"{tool.name} description too short"

    def test_every_tool_has_output_schema(self, tool_list):
        for tool in tool_list:
            assert tool.outputSchema is not None, f"{tool.name} missing outputSchema"
            assert tool.outputSchema.get("type") in ("object", "array"), (
                f"{tool.name} outputSchema.type must be 'object' or 'array'"
            )

    def test_every_tool_has_input_schema(self, tool_list):
        for tool in tool_list:
            assert tool.inputSchema is not None, f"{tool.name} missing inputSchema"

    def test_every_tool_has_meta(self, tool_list):
        """Every method must carry _meta so Context Protocol can classify it."""
        for tool in tool_list:
            raw = tool.model_dump(by_alias=True)
            meta = raw.get("_meta") or raw.get("meta")
            assert meta is not None, f"{tool.name} missing _meta"
            missing = REQUIRED_META_KEYS - set(meta.keys())
            assert not missing, f"{tool.name} _meta missing keys: {missing}"

    def test_every_meta_has_valid_surface(self, tool_list):
        for tool in tool_list:
            raw = tool.model_dump(by_alias=True)
            meta = raw.get("_meta") or raw.get("meta")
            assert meta["surface"] in VALID_SURFACES, (
                f"{tool.name} invalid surface: {meta['surface']}"
            )

    def test_every_meta_has_valid_latency_class(self, tool_list):
        for tool in tool_list:
            raw = tool.model_dump(by_alias=True)
            meta = raw.get("_meta") or raw.get("meta")
            assert meta["latencyClass"] in VALID_LATENCY_CLASSES, (
                f"{tool.name} invalid latencyClass: {meta['latencyClass']}"
            )

    def test_every_meta_has_execute_price(self, tool_list):
        """Methods must declare executeUsd so they are visible on Execute surface."""
        for tool in tool_list:
            raw = tool.model_dump(by_alias=True)
            meta = raw.get("_meta") or raw.get("meta")
            price = meta.get("pricing", {}).get("executeUsd")
            assert price is not None, f"{tool.name} missing pricing.executeUsd"
            # Must be a valid decimal string > 0
            assert float(price) > 0, f"{tool.name} executeUsd must be > 0"

    def test_execute_price_ratio(self, tool_list):
        """Intelligence tools should cost more than discovery tools."""
        prices = {}
        for tool in tool_list:
            raw = tool.model_dump(by_alias=True)
            meta = raw.get("_meta") or raw.get("meta")
            prices[tool.name] = float(meta["pricing"]["executeUsd"])

        intel_price = prices["amazon_product_intelligence"]
        discovery_price = prices["get_all_categories"]
        assert intel_price > discovery_price, (
            "Intelligence tools should cost more per call than discovery tools"
        )

    def test_intelligence_tools_are_query_eligible(self, tool_list):
        intelligence_tools = {"amazon_product_intelligence", "find_market_opportunities", "amazon_trending_products"}
        for tool in tool_list:
            if tool.name in intelligence_tools:
                raw = tool.model_dump(by_alias=True)
                meta = raw.get("_meta") or raw.get("meta")
                assert meta["queryEligible"] is True, f"{tool.name} should be queryEligible"

    def test_raw_data_tool_not_query_eligible(self, tool_list):
        for tool in tool_list:
            if tool.name == "get_bsr_history":
                raw = tool.model_dump(by_alias=True)
                meta = raw.get("_meta") or raw.get("meta")
                assert meta["queryEligible"] is False, "get_bsr_history should not be queryEligible"

    def test_intelligence_tools_have_input_examples(self, tool_list):
        """amazon_product_intelligence identifier must have examples for first-pass success."""
        for tool in tool_list:
            if tool.name == "amazon_product_intelligence":
                props = tool.inputSchema.get("properties", {})
                identifier = props.get("identifier", {})
                assert "examples" in identifier, (
                    "amazon_product_intelligence.identifier should have examples"
                )
                assert len(identifier["examples"]) >= 1

    def test_limit_params_have_defaults(self, tool_list):
        """Tools with a limit param must declare a default so the runtime doesn't guess."""
        tools_with_limit = {
            "find_market_opportunities",
            "amazon_trending_products",
            "get_bsr_history",
            "get_all_categories",
            "browse_by_category",
        }
        for tool in tool_list:
            if tool.name in tools_with_limit:
                props = tool.inputSchema.get("properties", {})
                limit_field = props.get("limit") or props.get("days")
                if limit_field:
                    assert "default" in limit_field, (
                        f"{tool.name} limit/days param should have a default"
                    )
