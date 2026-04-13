"""Tests for the claude_code adapter's stream-json translation.

Covers the rendering fixes from issue #26:
- tool_use and tool_result blocks are emitted as marker-tagged text
  chunks so live SSE and REST history share a single format.
- block_marker is set so the client flushes and creates a discrete
  transcript entry instead of concatenating into the previous text.
- _extract_content no longer leaks raw JSON for user messages.
- Nested sub-agent (Task) tool_use blocks inside a tool_result's
  content list are formatted recursively instead of being silently
  dropped.
"""

from __future__ import annotations

import json

from cambium.adapters.claude_code import (
    _extract_content,
    _format_tool_result,
    _format_tool_use,
    _stream_json_to_openai,
    _to_transcript_event,
)


def _assistant_event(blocks: list[dict]) -> dict:
    return {"type": "assistant", "message": {"content": blocks}}


def _user_event(blocks: list[dict]) -> dict:
    return {"type": "user", "message": {"content": blocks}}


# --- _format_tool_use / _format_tool_result ---------------------------------


def test_format_tool_use_produces_classifiable_marker():
    block = {
        "type": "tool_use",
        "id": "toolu_abc",
        "name": "Task",
        "input": {"description": "do a thing", "prompt": "details"},
    }
    out = _format_tool_use(block)
    assert out.startswith("[tool_use:toolu_abc] Task(")
    # Must be valid JSON in the parens so the client can unpack args if it
    # wants to later on.
    args_json = out[len("[tool_use:toolu_abc] Task(") : -1]
    assert json.loads(args_json) == {"description": "do a thing", "prompt": "details"}


def test_format_tool_result_handles_nested_tool_use_from_subagent():
    """Sub-agent results arrive as tool_result blocks whose content is a
    list containing the sub-agent's own tool_use blocks. Previously these
    were silently dropped (only .text fields were extracted), or dumped
    as raw JSON in the user-message path. They must now be formatted."""
    block = {
        "type": "tool_result",
        "tool_use_id": "toolu_outer",
        "content": [
            {"type": "text", "text": "Working on it..."},
            {
                "type": "tool_use",
                "id": "toolu_inner",
                "name": "Bash",
                "input": {"command": "ls"},
            },
        ],
    }
    out = _format_tool_result(block)
    assert out.startswith("[tool_result:toolu_outer]")
    assert "Working on it..." in out
    assert "[tool_use:toolu_inner] Bash(" in out


def test_format_tool_result_plain_string_content():
    block = {
        "type": "tool_result",
        "tool_use_id": "toolu_x",
        "content": "output text",
    }
    assert _format_tool_result(block) == "[tool_result:toolu_x] output text"


# --- _stream_json_to_openai --------------------------------------------------


def test_stream_assistant_text_has_no_block_marker():
    event = _assistant_event([{"type": "text", "text": "hello"}])
    chunks = _stream_json_to_openai(event, "chunk-1", "opus")
    assert len(chunks) == 1
    choice = chunks[0]["choices"][0]
    assert choice["delta"]["content"] == "hello"
    assert "block_marker" not in choice


def test_stream_assistant_thinking_marked_as_thinking_block():
    event = _assistant_event([{"type": "thinking", "thinking": "reasoning..."}])
    chunks = _stream_json_to_openai(event, "chunk-1", "opus")
    assert len(chunks) == 1
    choice = chunks[0]["choices"][0]
    assert choice["delta"]["content"] == "reasoning..."
    assert choice["block_marker"] == "thinking"
    assert choice["thinking"] is True


def test_stream_assistant_tool_use_emits_marker_text_not_tool_calls():
    """Previously tool_use was emitted as delta.tool_calls which the
    hook only captured the name from. It must now come through as a
    marker-tagged text chunk so classifyMessages can parse it into a
    ToolCallGroup card."""
    event = _assistant_event(
        [
            {
                "type": "tool_use",
                "id": "toolu_abc",
                "name": "Task",
                "input": {"description": "plan"},
            }
        ]
    )
    chunks = _stream_json_to_openai(event, "chunk-1", "opus")
    assert len(chunks) == 1
    choice = chunks[0]["choices"][0]
    assert "tool_calls" not in choice["delta"]
    assert choice["block_marker"] == "tool_use"
    assert choice["delta"]["content"].startswith("[tool_use:toolu_abc] Task(")


def test_stream_user_tool_result_is_now_translated():
    """Before the fix, user events were completely ignored and tool
    results never reached the broadcaster. They must now appear as
    marker-tagged text chunks."""
    event = _user_event(
        [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_outer",
                "content": [{"type": "text", "text": "done"}],
            }
        ]
    )
    chunks = _stream_json_to_openai(event, "chunk-1", "opus")
    assert len(chunks) == 1
    choice = chunks[0]["choices"][0]
    assert choice["block_marker"] == "tool_result"
    assert choice["delta"]["content"] == "[tool_result:toolu_outer] done"


def test_stream_unknown_block_types_are_skipped_not_dumped_as_json():
    event = _user_event([{"type": "mystery", "payload": {"x": 1}}])
    chunks = _stream_json_to_openai(event, "chunk-1", "opus")
    assert chunks == []


def test_stream_mixed_blocks_produce_one_chunk_per_block():
    event = _assistant_event(
        [
            {"type": "text", "text": "let me check"},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "Read",
                "input": {"file_path": "/tmp/x"},
            },
        ]
    )
    chunks = _stream_json_to_openai(event, "chunk-1", "opus")
    assert len(chunks) == 2
    assert "block_marker" not in chunks[0]["choices"][0]
    assert chunks[1]["choices"][0]["block_marker"] == "tool_use"


# --- _extract_content / TranscriptEvent -------------------------------------


def test_extract_content_assistant_message_uses_markers():
    event = _assistant_event(
        [
            {"type": "text", "text": "thinking out loud"},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "Read",
                "input": {"file_path": "/tmp/x"},
            },
        ]
    )
    content = _extract_content(event, "assistant")
    assert "thinking out loud" in content
    assert "[tool_use:toolu_1] Read(" in content


def test_extract_content_user_message_no_longer_leaks_raw_json():
    """Bug fix: previously non-tool_result blocks in a user message
    hit a json.dumps(block) fallback that dumped raw dicts into the
    transcript. That must no longer happen."""
    event = _user_event(
        [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_1",
                "content": "result text",
            },
            # Unknown type mixed in — must be silently dropped.
            {"type": "image", "source": {"data": "..."}},
        ]
    )
    content = _extract_content(event, "user")
    assert "[tool_result:toolu_1] result text" in content
    assert '{"type"' not in content  # no raw JSON leaking through


def test_transcript_event_for_user_tool_result():
    event = _user_event(
        [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_42",
                "content": [{"type": "text", "text": "ok"}],
            }
        ]
    )
    transcript = _to_transcript_event(event)
    assert transcript.role == "user"
    assert transcript.event_type == "user"
    assert transcript.content == "[tool_result:toolu_42] ok"
