"""Tests for Claude Code adapter usage extraction."""

from cambium.adapters.claude_code import _extract_usage


class TestExtractUsage:
    def test_extracts_usage_from_result_event(self):
        event = {
            "type": "result",
            "result": "Done.",
            "total_cost_usd": 0.0150655,
            "usage": {
                "input_tokens": 2,
                "output_tokens": 16,
                "cache_read_input_tokens": 29311,
                "cache_creation_input_tokens": 0,
                "server_tool_use": {"web_search_requests": 0},
            },
        }
        usage = _extract_usage(event)
        assert usage is not None
        assert usage.input_tokens == 2
        assert usage.output_tokens == 16
        assert usage.cache_read_tokens == 29311
        assert usage.cache_creation_tokens == 0
        assert usage.cost_usd == 0.0150655

    def test_returns_none_for_non_result_event(self):
        event = {"type": "assistant", "message": {"content": []}}
        assert _extract_usage(event) is None

    def test_returns_none_for_system_event(self):
        event = {"type": "system", "subtype": "init"}
        assert _extract_usage(event) is None

    def test_defaults_missing_fields_to_zero(self):
        event = {"type": "result", "result": "Done.", "total_cost_usd": 0.01}
        usage = _extract_usage(event)
        assert usage is not None
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.cache_read_tokens == 0
        assert usage.cache_creation_tokens == 0
        assert usage.cost_usd == 0.01

    def test_handles_missing_usage_object(self):
        event = {"type": "result", "result": "Done."}
        usage = _extract_usage(event)
        assert usage is not None
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.cost_usd == 0.0

    def test_handles_none_cost(self):
        """total_cost_usd can be None on Max subscription sessions."""
        event = {
            "type": "result",
            "result": "Done.",
            "total_cost_usd": None,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        usage = _extract_usage(event)
        assert usage is not None
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50
        assert usage.cost_usd == 0.0
