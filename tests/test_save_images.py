"""Tests for attachment saving in the routine runner."""

import base64
from pathlib import Path

from cambium.runner.routine_runner import _save_attachments, _dedup_path


def _make_data_url(media_type: str = "image/png", content: bytes = b"fake-png-data") -> str:
    """Build a base64 data URL from raw bytes."""
    b64 = base64.b64encode(content).decode()
    return f"data:{media_type};base64,{b64}"


# ---------------------------------------------------------------------------
# _save_attachments — auto-named (pasted images, no filename)
# ---------------------------------------------------------------------------


class TestSaveAttachmentsAutoNamed:

    def test_saves_single_image(self, tmp_path: Path):
        result = _save_attachments(tmp_path, [(_make_data_url("image/png", b"\x89PNGfake"), None)])

        assert len(result) == 1
        assert result[0].name == "attachment-000.png"
        assert result[0].read_bytes() == b"\x89PNGfake"

    def test_saves_multiple_images(self, tmp_path: Path):
        attachments = [
            (_make_data_url("image/png", b"png"), None),
            (_make_data_url("image/jpeg", b"jpg"), None),
            (_make_data_url("image/webp", b"webp"), None),
        ]
        result = _save_attachments(tmp_path, attachments)

        assert len(result) == 3
        assert result[0].name == "attachment-000.png"
        assert result[1].name == "attachment-001.jpg"
        assert result[2].name == "attachment-002.webp"

    def test_sequence_continues_across_calls(self, tmp_path: Path):
        _save_attachments(tmp_path, [(_make_data_url("image/png", b"first"), None)])
        result = _save_attachments(tmp_path, [(_make_data_url("image/jpeg", b"second"), None)])

        assert result[0].name == "attachment-001.jpg"

    def test_sequence_handles_gaps(self, tmp_path: Path):
        att_dir = tmp_path / "attachments"
        att_dir.mkdir()
        (att_dir / "attachment-005.png").write_bytes(b"existing")

        result = _save_attachments(tmp_path, [(_make_data_url("image/png", b"new"), None)])
        assert result[0].name == "attachment-006.png"

    def test_extension_mapping(self, tmp_path: Path):
        cases = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/svg+xml": ".svg",
            "image/bmp": ".bmp",
            "application/pdf": ".pdf",
            "text/plain": ".txt",
            "text/csv": ".csv",
            "application/json": ".json",
        }
        for media_type, expected_ext in cases.items():
            result = _save_attachments(tmp_path, [(_make_data_url(media_type, b"x"), None)])
            assert result[-1].suffix == expected_ext, f"Failed for {media_type}"

    def test_unknown_media_type_uses_bin(self, tmp_path: Path):
        result = _save_attachments(tmp_path, [(_make_data_url("image/tiff", b"data"), None)])
        assert result[0].suffix == ".bin"


# ---------------------------------------------------------------------------
# _save_attachments — named files (user-uploaded documents)
# ---------------------------------------------------------------------------


class TestSaveAttachmentsNamed:

    def test_preserves_filename(self, tmp_path: Path):
        result = _save_attachments(tmp_path, [(_make_data_url("application/pdf", b"pdf"), "report.pdf")])

        assert len(result) == 1
        assert result[0].name == "report.pdf"
        assert result[0].read_bytes() == b"pdf"

    def test_deduplicates_filename(self, tmp_path: Path):
        att_dir = tmp_path / "attachments"
        att_dir.mkdir()
        (att_dir / "report.pdf").write_bytes(b"existing")

        result = _save_attachments(tmp_path, [(_make_data_url("application/pdf", b"new"), "report.pdf")])
        assert result[0].name == "report-1.pdf"

    def test_multiple_deduplication(self, tmp_path: Path):
        att_dir = tmp_path / "attachments"
        att_dir.mkdir()
        (att_dir / "data.csv").write_bytes(b"v1")
        (att_dir / "data-1.csv").write_bytes(b"v2")

        result = _save_attachments(tmp_path, [(_make_data_url("text/csv", b"v3"), "data.csv")])
        assert result[0].name == "data-2.csv"

    def test_mixed_named_and_auto(self, tmp_path: Path):
        attachments = [
            (_make_data_url("image/png", b"screenshot"), None),
            (_make_data_url("application/pdf", b"doc"), "spec.pdf"),
            (_make_data_url("image/jpeg", b"photo"), None),
        ]
        result = _save_attachments(tmp_path, attachments)

        assert len(result) == 3
        assert result[0].name == "attachment-000.png"
        assert result[1].name == "spec.pdf"
        assert result[2].name == "attachment-001.jpg"


# ---------------------------------------------------------------------------
# _save_attachments — error handling
# ---------------------------------------------------------------------------


class TestSaveAttachmentsErrors:

    def test_skips_invalid_data_url(self, tmp_path: Path):
        result = _save_attachments(tmp_path, [("not-a-data-url", None)])
        assert result == []

    def test_skips_invalid_base64(self, tmp_path: Path):
        result = _save_attachments(tmp_path, [("data:image/png;base64,!!!invalid!!!", None)])
        assert result == []

    def test_mixed_valid_and_invalid(self, tmp_path: Path):
        attachments = [
            (_make_data_url("image/png", b"good"), None),
            ("not-a-data-url", None),
            (_make_data_url("image/jpeg", b"also-good"), "photo.jpg"),
        ]
        result = _save_attachments(tmp_path, attachments)

        assert len(result) == 2
        assert result[0].name == "attachment-000.png"
        assert result[1].name == "photo.jpg"

    def test_empty_list(self, tmp_path: Path):
        result = _save_attachments(tmp_path, [])
        assert result == []
        assert not (tmp_path / "attachments").exists()

    def test_creates_attachments_dir(self, tmp_path: Path):
        assert not (tmp_path / "attachments").exists()
        _save_attachments(tmp_path, [(_make_data_url(), None)])
        assert (tmp_path / "attachments").is_dir()


# ---------------------------------------------------------------------------
# _dedup_path
# ---------------------------------------------------------------------------


class TestDedupPath:

    def test_returns_original_if_no_conflict(self, tmp_path: Path):
        path = tmp_path / "file.txt"
        assert _dedup_path(path) == path

    def test_appends_suffix_on_conflict(self, tmp_path: Path):
        (tmp_path / "file.txt").write_text("existing")
        assert _dedup_path(tmp_path / "file.txt") == tmp_path / "file-1.txt"

    def test_increments_suffix(self, tmp_path: Path):
        (tmp_path / "file.txt").write_text("v1")
        (tmp_path / "file-1.txt").write_text("v2")
        assert _dedup_path(tmp_path / "file.txt") == tmp_path / "file-2.txt"

    def test_works_with_no_extension(self, tmp_path: Path):
        (tmp_path / "README").write_text("existing")
        assert _dedup_path(tmp_path / "README") == tmp_path / "README-1"
