"""
Unit tests for error handling in bank_statement_anonymiser.

This module tests that the library:
- Raises FileNotFoundError for missing input PDFs
- Raises FileNotFoundError for string paths to missing files
- Does NOT raise for missing user config files (graceful fallback)
- Does NOT raise for invalid/empty TOML user configs (graceful fallback)
- Does NOT raise for a corrupt content stream (page is skipped)
- Raises pikepdf.PdfError (or similar) for a completely corrupt PDF
- Returns a valid Path even when all page text is already protected
- Does not partially write output when input is missing
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

from bank_statement_anonymiser import anonymise_pdf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pdf(tmp_path: Path, content: bytes, filename: str = "src.pdf") -> Path:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(595, 842))
    page.Contents = pikepdf.Stream(pdf, content)
    page.Resources = pikepdf.Dictionary(
        Font=pikepdf.Dictionary(
            F1=pikepdf.Dictionary(
                Type=pikepdf.Name.Font,
                Subtype=pikepdf.Name.Type1,
                BaseFont=pikepdf.Name.Helvetica,
            )
        )
    )
    out = tmp_path / filename
    pdf.save(str(out))
    return out


def _tj(text: str) -> bytes:
    encoded = text.encode("latin-1")
    escaped = (
        encoded
        .replace(b"\\", b"\\\\")
        .replace(b"(", b"\\(")
        .replace(b")", b"\\)")
    )
    return b"BT\n/F1 12 Tf\n50 750 Td\n(" + escaped + b") Tj\nET\n"


# ---------------------------------------------------------------------------
# Module 10a: Missing input file
# ---------------------------------------------------------------------------


class TestMissingInputFile:
    """anonymise_pdf() raises FileNotFoundError when the input path doesn't exist."""

    @pytest.mark.unit
    def test_missing_input_raises_file_not_found(self, tmp_path):
        missing = tmp_path / "ghost.pdf"
        with pytest.raises(FileNotFoundError):
            anonymise_pdf(missing)

    @pytest.mark.unit
    def test_missing_input_string_path_raises_file_not_found(self, tmp_path):
        missing = str(tmp_path / "ghost.pdf")
        with pytest.raises(FileNotFoundError):
            anonymise_pdf(missing)

    @pytest.mark.unit
    def test_missing_input_error_message_contains_path(self, tmp_path):
        missing = tmp_path / "my_statement.pdf"
        with pytest.raises(FileNotFoundError, match="my_statement.pdf"):
            anonymise_pdf(missing)

    @pytest.mark.unit
    def test_no_output_file_created_when_input_missing(self, tmp_path):
        """When input is missing the output file must NOT be created."""
        missing = tmp_path / "ghost.pdf"
        out = tmp_path / "out.pdf"
        with pytest.raises(FileNotFoundError):
            anonymise_pdf(missing, output_path=out)
        assert not out.exists(), "Output should not be created when input is missing"

    @pytest.mark.unit
    def test_directory_path_raises_os_error(self, tmp_path):
        """Passing a directory path (not a file) raises an OSError family exception.

        The existing-path check in anonymise_pdf only guards against missing
        files; a directory passes that check, so pikepdf raises IsADirectoryError
        (a subclass of OSError) when it tries to open it.
        """
        with pytest.raises(OSError):
            anonymise_pdf(tmp_path)


# ---------------------------------------------------------------------------
# Module 10b: Missing / invalid user config files
# ---------------------------------------------------------------------------


class TestMissingUserConfigs:
    """Missing or malformed user config files are handled gracefully (no raise)."""

    @pytest.mark.unit
    def test_missing_always_config_no_raise(self, mock_random_source, tmp_path):
        src = _make_pdf(tmp_path, _tj("SomeText"))
        nonexistent = tmp_path / "no_always.toml"
        out = tmp_path / "out.pdf"
        result = anonymise_pdf(src, output_path=out, always_anonymise_path=nonexistent)
        assert result.exists()

    @pytest.mark.unit
    def test_missing_never_config_no_raise(self, mock_random_source, tmp_path):
        src = _make_pdf(tmp_path, _tj("SomeText"))
        nonexistent = tmp_path / "no_never.toml"
        out = tmp_path / "out.pdf"
        result = anonymise_pdf(src, output_path=out, never_anonymise_path=nonexistent)
        assert result.exists()

    @pytest.mark.unit
    def test_empty_always_config_no_raise(self, mock_random_source, tmp_path):
        src = _make_pdf(tmp_path, _tj("SomeText"))
        empty_cfg = tmp_path / "empty_always.toml"
        empty_cfg.write_text("", encoding="utf-8")
        out = tmp_path / "out.pdf"
        result = anonymise_pdf(src, output_path=out, always_anonymise_path=empty_cfg)
        assert result.exists()

    @pytest.mark.unit
    def test_empty_never_config_no_raise(self, mock_random_source, tmp_path):
        src = _make_pdf(tmp_path, _tj("SomeText"))
        empty_cfg = tmp_path / "empty_never.toml"
        empty_cfg.write_text("", encoding="utf-8")
        out = tmp_path / "out.pdf"
        result = anonymise_pdf(src, output_path=out, never_anonymise_path=empty_cfg)
        assert result.exists()

    @pytest.mark.unit
    def test_always_config_with_no_string_values_no_raise(self, mock_random_source, tmp_path):
        """A TOML file whose top-level values are non-strings is silently ignored."""
        src = _make_pdf(tmp_path, _tj("SomeText"))
        cfg = tmp_path / "bad_always.toml"
        cfg.write_text("numeric_key = 42\nlist_key = [1, 2, 3]\n", encoding="utf-8")
        out = tmp_path / "out.pdf"
        result = anonymise_pdf(src, output_path=out, always_anonymise_path=cfg)
        assert result.exists()

    @pytest.mark.unit
    def test_never_config_missing_exclude_key_no_raise(self, mock_random_source, tmp_path):
        """A never_anonymise TOML that has no 'exclude' key is silently treated as empty."""
        src = _make_pdf(tmp_path, _tj("SomeText"))
        cfg = tmp_path / "no_exclude.toml"
        cfg.write_text("some_other_key = 42\n", encoding="utf-8")
        out = tmp_path / "out.pdf"
        result = anonymise_pdf(src, output_path=out, never_anonymise_path=cfg)
        assert result.exists()


# ---------------------------------------------------------------------------
# Module 10c: Corrupt / invalid PDF
# ---------------------------------------------------------------------------


class TestCorruptPdf:
    """Corrupt input bytes raise an appropriate exception (not a silent no-op)."""

    @pytest.mark.unit
    def test_not_a_pdf_raises(self, tmp_path):
        """A file with garbage bytes raises an exception when opened as PDF."""
        junk = tmp_path / "junk.pdf"
        junk.write_bytes(b"this is not a pdf at all\x00\x01\x02")
        out = tmp_path / "out.pdf"
        with pytest.raises(Exception):  # pikepdf.PdfError or similar
            anonymise_pdf(junk, output_path=out)

    @pytest.mark.unit
    def test_truncated_pdf_raises(self, tmp_path):
        """A truncated PDF (first few bytes only) raises an exception."""
        truncated = tmp_path / "truncated.pdf"
        truncated.write_bytes(b"%PDF-1.4\n%")
        out = tmp_path / "out.pdf"
        with pytest.raises(Exception):
            anonymise_pdf(truncated, output_path=out)

    @pytest.mark.unit
    def test_zero_byte_file_raises(self, tmp_path):
        """An empty (0-byte) file raises an exception."""
        empty = tmp_path / "empty.pdf"
        empty.write_bytes(b"")
        out = tmp_path / "out.pdf"
        with pytest.raises(Exception):
            anonymise_pdf(empty, output_path=out)


# ---------------------------------------------------------------------------
# Module 10d: All-protected page produces valid output
# ---------------------------------------------------------------------------


class TestAllProtectedPage:
    """When every fragment on a page is protected, output is still valid."""

    @pytest.mark.unit
    def test_all_dates_page_produces_valid_pdf(self, mock_random_source, tmp_path):
        """Page containing only date strings (all protected) produces a valid PDF."""
        content = _tj("01 Jan 25") + _tj("02 Feb 25") + _tj("03 Mar 25")
        src = _make_pdf(tmp_path, content)
        out = tmp_path / "out.pdf"
        result = anonymise_pdf(src, output_path=out)
        assert result.exists()
        with pikepdf.open(str(result)) as r:
            assert len(r.pages) == 1

    @pytest.mark.unit
    def test_all_numeric_page_produces_valid_pdf(self, mock_random_source, tmp_path):
        """Page containing only numeric strings produces a valid PDF."""
        content = _tj("1234") + _tj("5678") + _tj("9012")
        src = _make_pdf(tmp_path, content)
        out = tmp_path / "out.pdf"
        result = anonymise_pdf(src, output_path=out)
        assert result.exists()

    @pytest.mark.unit
    def test_all_never_cfg_page_produces_valid_pdf(self, mock_random_source, tmp_path):
        """Page where every fragment is in never_anonymise produces a valid PDF."""
        content = _tj("AlphaProtected") + _tj("BetaProtected")
        src = _make_pdf(tmp_path, content)
        cfg = tmp_path / "never.toml"
        cfg.write_text('exclude = ["AlphaProtected", "BetaProtected"]\n', encoding="utf-8")
        out = tmp_path / "out.pdf"
        result = anonymise_pdf(src, output_path=out, never_anonymise_path=cfg)
        assert result.exists()
        with pikepdf.open(str(result)) as r:
            assert len(r.pages) == 1
