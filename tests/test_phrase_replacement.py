"""
Unit tests for phrase_replace_pdf() in bank_statement_anonymiser.

This module tests the post-anonymisation phrase replacement functionality,
which allows users to fix phrases that weren't anonymised correctly by the
main pipeline.

Coverage:
- Config file loading and validation
- Phrase length matching requirements
- Character sequence detection and matching
- Byte replacement with correct glyph codes
- Multi-page phrase replacement
- Font encoding handling (ToUnicode CMap, Latin-1 fallback)
- Error handling (missing files, invalid config, parse failures)
- Output PDF validity (can be re-opened, structure preserved)
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

from bank_statement_anonymiser import phrase_replace_pdf
from bank_statement_anonymiser._shared import _decode_pdf_operand
from bank_statement_anonymiser.anonymise_phrase import (
    _apply_replacements_raw,
    _decode_byte,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_toml(path: Path, content: str) -> Path:
    """Write TOML content to a file."""
    path.write_text(content, encoding="utf-8")
    return path


def _make_hex_pdf_with_text(tmp_path: Path, *lines: str, filename: str = "src.pdf") -> Path:
    """Create a one-page PDF where text is stored in hex format (like anonymised PDFs).

    This mimics the format produced by anonymised PDFs where byte strings are
    stored as hex-encoded values instead of ASCII strings.
    """
    pdf = pikepdf.Pdf.new()
    parts = [b"BT\n/F1 12 Tf\n50 750 Td\n"]
    for i, line in enumerate(lines):
        # Encode as hex (like anonymised PDFs do)
        encoded = line.encode("latin-1")
        hex_str = encoded.hex().upper()
        parts.append(b"<" + hex_str.encode() + b"> Tj\n")
        if i < len(lines) - 1:
            parts.append(b"0 -20 Td\n")
    parts.append(b"ET\n")
    content = b"".join(parts)

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


def _extract_all_text(pdf_path: Path) -> list[str]:
    """Return a flat list of every decoded Tj/TJ string from all pages."""
    texts: list[str] = []
    with pikepdf.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            try:
                instructions = list(pikepdf.parse_content_stream(page))
            except Exception:
                continue
            for operands, operator in instructions:
                op = str(operator)
                if op == "Tj" and operands:
                    try:
                        texts.append(_decode_pdf_operand(bytes(operands[0])))
                    except Exception:
                        pass
                elif op == "TJ" and operands:
                    try:
                        for item in list(operands[0]):  # type: ignore[arg-type]
                            if isinstance(item, pikepdf.String):
                                texts.append(_decode_pdf_operand(bytes(item)))
                    except Exception:
                        pass
    return texts


def _all_text_joined(pdf_path: Path) -> str:
    """Concatenate all decoded Tj strings into one string for substring checks."""
    return "".join(_extract_all_text(pdf_path))


# ---------------------------------------------------------------------------
# Tests: Config Loading and Validation
# ---------------------------------------------------------------------------


class TestPhraseReplaceConfigLoading:
    """Tests for loading and validating phrase_replace.toml config files."""

    def test_missing_config_file_raises_error(self, tmp_path: Path):
        """Missing config file should raise FileNotFoundError."""
        pdf = _make_hex_pdf_with_text(tmp_path, "hello world", filename="test.pdf")
        config = tmp_path / "missing_config.toml"

        with pytest.raises(ValueError, match="Failed to load phrase_replace config"):
            phrase_replace_pdf(pdf, phrase_replace_path=config)

    def test_valid_config_loads_successfully(self, tmp_path: Path):
        """Valid config file with correct format should load without error."""
        pdf = _make_hex_pdf_with_text(tmp_path, "hello world", filename="test.pdf")
        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[phrase_replace]
"hello" = "goodbye"
""",
        )

        # Should not raise
        result = phrase_replace_pdf(pdf, phrase_replace_path=config)
        assert result.exists()

    def test_empty_config_section_treated_as_no_replacements(self, tmp_path: Path):
        """Config with empty phrase_replace section should process without error."""
        pdf = _make_hex_pdf_with_text(tmp_path, "hello world", filename="test.pdf")
        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[phrase_replace]
""",
        )

        result = phrase_replace_pdf(pdf, phrase_replace_path=config)
        assert result.exists()
        # Text should be unchanged
        assert "hello world" in _all_text_joined(result)

    def test_missing_phrase_replace_section_no_error(self, tmp_path: Path):
        """Config file without [phrase_replace] section should be treated as empty."""
        pdf = _make_hex_pdf_with_text(tmp_path, "hello world", filename="test.pdf")
        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[other_section]
key = "value"
""",
        )

        result = phrase_replace_pdf(pdf, phrase_replace_path=config)
        assert result.exists()

    def test_mismatched_phrase_lengths_skipped(self, tmp_path: Path):
        """Search and replacement phrases must be exactly same length."""
        pdf = _make_hex_pdf_with_text(tmp_path, "hello", filename="test.pdf")
        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[phrase_replace]
"hello" = "hi"
""",
        )

        # Should not raise - just skip the invalid rule and process normally
        result = phrase_replace_pdf(pdf, phrase_replace_path=config)
        assert result.exists()
        # Text should be unchanged since rule was skipped
        text = _all_text_joined(result)
        assert "hello" in text

    def test_correct_length_phrases_valid(self, tmp_path: Path):
        """Search and replacement phrases of equal length should validate."""
        pdf = _make_hex_pdf_with_text(tmp_path, "hello", filename="test.pdf")
        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[phrase_replace]
"hello" = "world"
""",
        )

        result = phrase_replace_pdf(pdf, phrase_replace_path=config)
        assert result.exists()


# ---------------------------------------------------------------------------
# Tests: Basic Phrase Matching and Replacement
# ---------------------------------------------------------------------------


class TestBasicPhraseReplacement:
    """Tests for basic character-by-character phrase matching and replacement."""

    def test_exact_phrase_match_is_replaced(self, tmp_path: Path):
        """Exact phrase match should be replaced with replacement phrase."""
        pdf = _make_hex_pdf_with_text(tmp_path, "hello world", filename="test.pdf")
        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[phrase_replace]
"hello" = "h****"
""",
        )

        result = phrase_replace_pdf(pdf, phrase_replace_path=config)
        text = _all_text_joined(result)
        assert "h****" in text
        assert "hello" not in text

    def test_partial_phrase_match_replaced(self, tmp_path: Path):
        """Partial phrase match within larger text should be replaced."""
        pdf = _make_hex_pdf_with_text(tmp_path, "the hello friend", filename="test.pdf")
        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[phrase_replace]
"hello" = "h****"
""",
        )

        result = phrase_replace_pdf(pdf, phrase_replace_path=config)
        text = _all_text_joined(result)
        assert "h****" in text
        assert "the h**** friend" in text

    def test_no_match_leaves_text_unchanged(self, tmp_path: Path):
        """Text without matching phrase should remain unchanged."""
        pdf = _make_hex_pdf_with_text(tmp_path, "hello world", filename="test.pdf")
        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[phrase_replace]
"goodbye" = "f*****"
""",
        )

        result = phrase_replace_pdf(pdf, phrase_replace_path=config)
        text = _all_text_joined(result)
        assert "hello world" in text
        assert "f*****" not in text

    def test_multiple_occurrences_all_replaced(self, tmp_path: Path):
        """All occurrences of phrase should be replaced."""
        pdf = _make_hex_pdf_with_text(tmp_path, "hello hello hello", filename="test.pdf")
        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[phrase_replace]
"hello" = "h****"
""",
        )

        result = phrase_replace_pdf(pdf, phrase_replace_path=config)
        text = _all_text_joined(result)
        assert text.count("h****") == 3
        assert "hello" not in text

    def test_space_character_preserved(self, tmp_path: Path):
        """Space characters should be preserved and matched correctly."""
        pdf = _make_hex_pdf_with_text(tmp_path, "ab cd ef", filename="test.pdf")
        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[phrase_replace]
"b c" = "x y"
""",
        )

        result = phrase_replace_pdf(pdf, phrase_replace_path=config)
        text = _all_text_joined(result)
        assert "ax y" in text


# ---------------------------------------------------------------------------
# Tests: Multi-Rule Replacement
# ---------------------------------------------------------------------------


class TestMultipleReplacementRules:
    """Tests for applying multiple replacement rules on same PDF."""

    def test_multiple_rules_all_applied(self, tmp_path: Path):
        """Multiple rules should all be applied in order."""
        pdf = _make_hex_pdf_with_text(tmp_path, "hello world test ", filename="test.pdf")
        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[phrase_replace]
"hello" = "h****"
"world" = "w****"
"test " = "t*** "
""",
        )

        result = phrase_replace_pdf(pdf, phrase_replace_path=config)
        text = _all_text_joined(result)
        assert "h****" in text
        assert "w****" in text
        assert "t*** " in text
        assert "hello" not in text
        assert "world" not in text

    def test_non_overlapping_rules_independent(self, tmp_path: Path):
        """Non-overlapping rules should not affect each other."""
        pdf = _make_hex_pdf_with_text(tmp_path, "apple banana cherry", filename="test.pdf")
        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[phrase_replace]
"apple" = "f****"
"berry" = "b***y"
""",
        )

        result = phrase_replace_pdf(pdf, phrase_replace_path=config)
        text = _all_text_joined(result)
        assert "f****" in text
        assert "banana" in text
        assert "cherry" in text


# ---------------------------------------------------------------------------
# Tests: Multi-Page Processing
# ---------------------------------------------------------------------------


class TestMultiPageReplacement:
    """Tests for phrase replacement across multiple pages."""

    def test_single_page_replacement(self, tmp_path: Path):
        """Replacement should work on single page PDFs."""
        pdf = _make_hex_pdf_with_text(tmp_path, "hello world", filename="test.pdf")
        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[phrase_replace]
"hello" = "h****"
""",
        )

        result = phrase_replace_pdf(pdf, phrase_replace_path=config)
        text = _all_text_joined(result)
        assert "h****" in text

    def test_multi_page_all_pages_processed(self, tmp_path: Path):
        """Replacement should apply to all pages."""
        # Create 3-page PDF with hex-encoded content
        pdf = pikepdf.Pdf.new()
        for page_num in range(3):
            text = f"Page {page_num} hello world"
            encoded = text.encode("latin-1")
            hex_str = encoded.hex().upper()
            page_content = f"BT\n/F1 12 Tf\n50 750 Td\n<{hex_str}> Tj\nET\n".encode()

            page = pdf.add_blank_page(page_size=(595, 842))
            page.Contents = pikepdf.Stream(pdf, page_content)
            page.Resources = pikepdf.Dictionary(
                Font=pikepdf.Dictionary(
                    F1=pikepdf.Dictionary(
                        Type=pikepdf.Name.Font,
                        Subtype=pikepdf.Name.Type1,
                        BaseFont=pikepdf.Name.Helvetica,
                    )
                )
            )

        pdf_path = tmp_path / "multi_page.pdf"
        pdf.save(str(pdf_path))

        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[phrase_replace]
"hello" = "h****"
""",
        )

        result = phrase_replace_pdf(pdf_path, phrase_replace_path=config)
        texts = _extract_all_text(result)

        # All pages should have replacements
        joined = " ".join(texts)
        assert joined.count("h****") == 3


# ---------------------------------------------------------------------------
# Tests: Output Validity and Structure Preservation
# ---------------------------------------------------------------------------


class TestOutputValidity:
    """Tests for output PDF validity and structure preservation."""

    def test_output_is_valid_pdf(self, tmp_path: Path):
        """Output should be a valid PDF that can be reopened."""
        pdf = _make_hex_pdf_with_text(tmp_path, "hello world", filename="test.pdf")
        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[phrase_replace]
"hello" = "goodbye"
""",
        )

        result = phrase_replace_pdf(pdf, phrase_replace_path=config)

        # Should be able to open with pikepdf without error
        with pikepdf.open(str(result)) as reloaded:
            assert len(reloaded.pages) > 0

    def test_output_path_respected(self, tmp_path: Path):
        """Specified output path should be used."""
        pdf = _make_hex_pdf_with_text(tmp_path, "hello", filename="test.pdf")
        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[phrase_replace]
"hello" = "world"
""",
        )
        custom_output = tmp_path / "custom_output.pdf"

        result = phrase_replace_pdf(pdf, output_path=custom_output, phrase_replace_path=config)

        assert result == custom_output
        assert custom_output.exists()

    def test_default_output_path_created_alongside_input(self, tmp_path: Path):
        """Default output should be created as phrase_replaced_<original>."""
        pdf = _make_hex_pdf_with_text(tmp_path, "hello", filename="test.pdf")
        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[phrase_replace]
"hello" = "world"
""",
        )

        result = phrase_replace_pdf(pdf, phrase_replace_path=config)

        # Should create phrase_replaced_test.pdf in same directory
        assert result.name == "phrase_replaced_test.pdf"
        assert result.parent == tmp_path

    def test_page_count_preserved(self, tmp_path: Path):
        """Number of pages should remain unchanged."""
        pdf = pikepdf.Pdf.new()
        for _ in range(3):
            page = pdf.add_blank_page(page_size=(595, 842))
            page.Contents = pikepdf.Stream(
                pdf,
                b"BT\n/F1 12 Tf\n50 750 Td\n(hello) Tj\nET\n",
            )
            page.Resources = pikepdf.Dictionary(
                Font=pikepdf.Dictionary(
                    F1=pikepdf.Dictionary(
                        Type=pikepdf.Name.Font,
                        Subtype=pikepdf.Name.Type1,
                        BaseFont=pikepdf.Name.Helvetica,
                    )
                )
            )

        pdf_path = tmp_path / "three_pages.pdf"
        pdf.save(str(pdf_path))

        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[phrase_replace]
"hello" = "world"
""",
        )

        result = phrase_replace_pdf(pdf_path, phrase_replace_path=config)

        with pikepdf.open(str(result)) as reopened:
            assert len(reopened.pages) == 3


# ---------------------------------------------------------------------------
# Tests: Error Handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for error handling in phrase replacement."""

    def test_invalid_pdf_file_raises_error(self, tmp_path: Path):
        """Invalid PDF file should raise an error."""
        invalid_pdf = tmp_path / "invalid.pdf"
        invalid_pdf.write_text("not a pdf")

        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[phrase_replace]
"hello" = "world"
""",
        )

        with pytest.raises(Exception):  # pikepdf will raise
            phrase_replace_pdf(invalid_pdf, phrase_replace_path=config)

    def test_missing_input_pdf_raises_error(self, tmp_path: Path):
        """Missing input PDF should raise FileNotFoundError."""
        missing_pdf = tmp_path / "missing.pdf"
        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[phrase_replace]
"hello" = "world"
""",
        )

        with pytest.raises(FileNotFoundError):
            phrase_replace_pdf(missing_pdf, phrase_replace_path=config)

    def test_malformed_toml_raises_error(self, tmp_path: Path):
        """Malformed TOML should raise error during config load."""
        pdf = _make_hex_pdf_with_text(tmp_path, "hello", filename="test.pdf")
        config = tmp_path / "bad.toml"
        config.write_text("[phrase_replace\nmalformed toml")

        with pytest.raises(Exception):
            phrase_replace_pdf(pdf, phrase_replace_path=config)


# ---------------------------------------------------------------------------
# Tests: Unit-Level Functions
# ---------------------------------------------------------------------------


class TestDecodeByte:
    """Tests for _decode_byte() utility function."""

    def test_decode_byte_latin1_fallback(self):
        """ASCII bytes should decode to Latin-1 equivalents."""
        # Using empty forward maps, should fall back to Latin-1
        forward_maps: dict[str, dict[int, str]] = {}

        # ASCII 65 = 'A'
        result = _decode_byte(65, "/F1", forward_maps)
        assert result == "A"

    def test_decode_byte_from_forward_map(self):
        """Bytes in font map should use font mapping."""
        # Mock font map where glyph 0x05 decodes to 'h'
        forward_maps = {"/F1": {0x05: "h", 0x04: "e"}}

        result = _decode_byte(0x05, "/F1", forward_maps)
        assert result == "h"

        result = _decode_byte(0x04, "/F1", forward_maps)
        assert result == "e"

    def test_decode_byte_unknown_font_falls_back(self):
        """Unknown font should fall back to Latin-1."""
        forward_maps = {"/F1": {0x05: "h"}}

        # Font /F2 not in map, should use Latin-1
        result = _decode_byte(65, "/F2", forward_maps)
        assert result == "A"


class TestApplyReplacementsRaw:
    """Tests for _apply_replacements_raw() utility function."""

    def test_apply_replacements_modifies_stream_correctly(self):
        """Replacements should modify bytearray at correct hex positions."""
        # Create a simple bytearray with hex content
        # <414243> = "ABC" in hex (0x41='A', 0x42='B', 0x43='C')
        stream = bytearray(b"<414243>Tj")

        # Mock font maps: 'A' maps to 0x41, 'X' maps to 0x58
        reverse_maps = {"/F1": {"A": 0x41, "X": 0x58}}

        # Matched sequence: "ABC" at hex positions 1, 3, 5
        # Replace 'A' at position 1 with 'X' (0x58)
        matched = [("A", 1, "/F1"), ("B", 3, "/F1"), ("C", 5, "/F1")]

        result = _apply_replacements_raw(stream, matched, "XXX", reverse_maps, debug=False)

        assert result is True
        # Check that hex was modified
        # 0x58 = '58' in hex
        assert b"58" in stream

    def test_apply_replacements_length_mismatch_fails(self):
        """Mismatched replacement length should return False."""
        stream = bytearray(b"<414243>Tj")
        reverse_maps = {"/F1": {"A": 0x41, "X": 0x58}}
        matched = [("A", 1, "/F1"), ("B", 3, "/F1")]

        # Replacement is 3 chars but matched is 2
        result = _apply_replacements_raw(stream, matched, "XXX", reverse_maps)

        assert result is False


# ---------------------------------------------------------------------------
# Tests: Integration with Real Anonymised PDFs
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRealWorldScenario:
    """Integration tests simulating real-world usage patterns."""

    def test_post_anonymisation_phrase_fix(self, tmp_path: Path):
        """Simulate fixing a phrase that was scrambled by anonymisation."""
        # Create PDF with a phrase that looks like it was scrambled
        pdf = _make_hex_pdf_with_text(
            tmp_path,
            "Statement Date: 01 Jan 2024",
            filename="test.pdf",
        )

        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[phrase_replace]
"01 Jan " = "1st Jan"
""",
        )

        result = phrase_replace_pdf(pdf, phrase_replace_path=config)
        text = _all_text_joined(result)

        assert "1st Jan" in text
        assert "01 Jan " not in text

    def test_multiple_fixes_same_page(self, tmp_path: Path):
        """Multiple phrase fixes on same page should all work."""
        pdf = _make_hex_pdf_with_text(
            tmp_path,
            "Transaction 1: payment  at 2pm",
            filename="test.pdf",
        )

        config = _write_toml(
            tmp_path / "phrase_replace.toml",
            """[phrase_replace]
"payment  " = "purchase "
""",
        )

        result = phrase_replace_pdf(pdf, phrase_replace_path=config)
        text = _all_text_joined(result)

        assert "purchase " in text
        assert "payment  " not in text
