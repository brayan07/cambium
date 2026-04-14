"""Tests for the self-improvement auto-classifier (fix (a) for #30)."""

from cambium.queue.sqlite import SQLiteQueue
from cambium.work_item.classifier import auto_classify, looks_like_self_improvement
from cambium.work_item.service import WorkItemService
from cambium.work_item.store import WorkItemStore


# ── pure helper tests ─────────────────────────────────────────────────


def test_classify_src_path_in_title() -> None:
    is_si, matched = looks_like_self_improvement(
        title="Fix bug in src/cambium/consumer/loop.py", description=""
    )
    assert is_si is True
    assert "src/cambium/consumer/loop.py" in matched


def test_classify_tests_path_in_description() -> None:
    is_si, matched = looks_like_self_improvement(
        title="Add coverage", description="Add a test in tests/test_consumer.py"
    )
    assert is_si is True
    assert "tests/test_consumer.py" in matched


def test_classify_defaults_path() -> None:
    is_si, _ = looks_like_self_improvement(
        title="Update prompt",
        description="Edit defaults/adapters/claude-code/prompts/executor.md",
    )
    assert is_si is True


def test_classify_ui_src_path() -> None:
    is_si, _ = looks_like_self_improvement(
        title="Fix sidebar", description="ui/src/components/Sidebar.tsx"
    )
    assert is_si is True


def test_classify_top_level_file() -> None:
    is_si, matched = looks_like_self_improvement(
        title="Bump version", description="Update pyproject.toml"
    )
    assert is_si is True
    assert "pyproject.toml" in matched


def test_classify_target_file_in_context() -> None:
    is_si, matched = looks_like_self_improvement(
        title="Self-improvement",
        description="",
        context={"target_file": "src/cambium/server/app.py"},
    )
    assert is_si is True
    assert "src/cambium/server/app.py" in matched


def test_classify_affected_paths_in_context() -> None:
    is_si, matched = looks_like_self_improvement(
        title="Refactor",
        description="",
        context={"affected_paths": ["src/cambium/foo.py", "tests/test_foo.py"]},
    )
    assert is_si is True
    assert "src/cambium/foo.py" in matched
    assert "tests/test_foo.py" in matched


def test_no_classify_for_unrelated_paths() -> None:
    is_si, matched = looks_like_self_improvement(
        title="Write report", description="Save to ~/notes/report.md"
    )
    assert is_si is False
    assert matched == []


def test_no_classify_for_lookalike_prefix() -> None:
    # "mysrc/foo.py" should not match because the path token regex
    # requires a non-word boundary on the left.
    is_si, _ = looks_like_self_improvement(
        title="x", description="touched mysrc/foo.py only"
    )
    assert is_si is False


def test_auto_classify_sets_type_and_flag() -> None:
    ctx = auto_classify(
        title="Fix src/cambium/foo.py",
        description="",
        context=None,
    )
    assert ctx["type"] == "self_improvement"
    assert ctx["auto_classified"] is True
    assert "src/cambium/foo.py" in ctx["classified_targets"]


def test_auto_classify_respects_existing_type() -> None:
    # Caller already declared a type — classifier must not overwrite.
    ctx = auto_classify(
        title="Fix src/cambium/foo.py",
        description="",
        context={"type": "implementation"},
    )
    assert ctx["type"] == "implementation"
    assert "auto_classified" not in ctx


def test_auto_classify_no_match_returns_unchanged() -> None:
    ctx = auto_classify(
        title="Write a haiku", description="five seven five", context={"foo": "bar"}
    )
    assert ctx == {"foo": "bar"}


# ── integration test against WorkItemService ──────────────────────────


def _make_service() -> tuple[WorkItemService, WorkItemStore, SQLiteQueue]:
    store = WorkItemStore()
    queue = SQLiteQueue()
    return WorkItemService(store=store, queue=queue), store, queue


def test_create_item_auto_classifies_repo_targeting_work() -> None:
    service, _store, _queue = _make_service()
    item = service.create_item(
        title="Patch src/cambium/server/app.py to handle SIGTERM",
        description="The shutdown handler in src/cambium/server/app.py needs work.",
    )
    assert item.context.get("type") == "self_improvement"
    assert item.context.get("auto_classified") is True
    assert any(
        "src/cambium/server/app.py" in t
        for t in item.context.get("classified_targets", [])
    )


def test_create_item_does_not_classify_unrelated_work() -> None:
    service, _store, _queue = _make_service()
    item = service.create_item(
        title="Research Python testing frameworks",
        description="Compare pytest, unittest, and nose2.",
    )
    assert "type" not in item.context
    assert "auto_classified" not in item.context


def test_create_item_preserves_explicit_type() -> None:
    service, _store, _queue = _make_service()
    item = service.create_item(
        title="Fix src/cambium/foo.py",
        description="",
        context={"type": "upstream_merge"},
    )
    assert item.context["type"] == "upstream_merge"
    assert "auto_classified" not in item.context
