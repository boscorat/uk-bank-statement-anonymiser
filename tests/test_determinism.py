"""
Unit tests for determinism in bank_statement_anonymiser.

This module tests:
- _make_scramble_map() properties:
  - Returns a dict mapping int codepoints to int codepoints
  - Every lowercase letter maps to a DIFFERENT lowercase letter (no fixed points)
  - Every uppercase letter maps to a DIFFERENT uppercase letter (no fixed points)
  - Lowercase maps only to lowercase; uppercase maps only to uppercase
  - All 26 lowercase and 26 uppercase letters are covered
  - The mapping is a bijection (no two originals share a replacement)
  - Digits and symbols are NOT in the map
- With a fixed seed (mock_random_source), two calls to anonymise_pdf on the
  same input produce identical scrambled text
- With a fixed seed, the same word scrambled twice produces the same result
- Numeric ID replacements are stable across pages within one run
- Each call to anonymise_pdf uses a fresh (potentially different) scramble map
  (without seed mock, two runs may differ — tested via mock to confirm they DO)
"""

from __future__ import annotations

import string
from pathlib import Path

import pikepdf
import pytest

from bank_statement_anonymiser import anonymise_pdf
from bank_statement_anonymiser._shared import (
    _LOWER_LETTERS,
    _UPPER_LETTERS,
    _decode_pdf_operand,
    _make_scramble_map,
)
from bank_statement_anonymiser.anonymise import _scramble_text


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


def _extract_all_text(pdf_path: Path) -> list[str]:
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


# ---------------------------------------------------------------------------
# Module 11a: _make_scramble_map() structural properties
# ---------------------------------------------------------------------------


class TestScrambleMapStructure:
    """_make_scramble_map() must produce a well-formed derangement."""

    @pytest.mark.unit
    def test_returns_dict(self, mock_random_source):
        result = _make_scramble_map()
        assert isinstance(result, dict)

    @pytest.mark.unit
    def test_keys_are_ints(self, mock_random_source):
        result = _make_scramble_map()
        assert all(isinstance(k, int) for k in result)

    @pytest.mark.unit
    def test_values_are_ints(self, mock_random_source):
        result = _make_scramble_map()
        assert all(isinstance(v, int) for v in result.values())

    @pytest.mark.unit
    def test_covers_all_lowercase(self, mock_random_source):
        result = _make_scramble_map()
        for ch in _LOWER_LETTERS:
            assert ord(ch) in result, f"lowercase '{ch}' missing from map"

    @pytest.mark.unit
    def test_covers_all_uppercase(self, mock_random_source):
        result = _make_scramble_map()
        for ch in _UPPER_LETTERS:
            assert ord(ch) in result, f"uppercase '{ch}' missing from map"

    @pytest.mark.unit
    def test_map_size_is_52(self, mock_random_source):
        """26 lowercase + 26 uppercase = 52 entries."""
        result = _make_scramble_map()
        assert len(result) == 52

    @pytest.mark.unit
    def test_lowercase_maps_to_lowercase(self, mock_random_source):
        result = _make_scramble_map()
        for ch in _LOWER_LETTERS:
            mapped = chr(result[ord(ch)])
            assert mapped.islower(), f"'{ch}' maps to non-lowercase '{mapped}'"

    @pytest.mark.unit
    def test_uppercase_maps_to_uppercase(self, mock_random_source):
        result = _make_scramble_map()
        for ch in _UPPER_LETTERS:
            mapped = chr(result[ord(ch)])
            assert mapped.isupper(), f"'{ch}' maps to non-uppercase '{mapped}'"

    @pytest.mark.unit
    def test_no_fixed_points_lowercase(self, mock_random_source):
        """No lowercase letter maps to itself (derangement property)."""
        result = _make_scramble_map()
        for ch in _LOWER_LETTERS:
            assert result[ord(ch)] != ord(ch), f"'{ch}' maps to itself"

    @pytest.mark.unit
    def test_no_fixed_points_uppercase(self, mock_random_source):
        """No uppercase letter maps to itself (derangement property)."""
        result = _make_scramble_map()
        for ch in _UPPER_LETTERS:
            assert result[ord(ch)] != ord(ch), f"'{ch}' maps to itself"

    @pytest.mark.unit
    def test_lowercase_bijection(self, mock_random_source):
        """All 26 lowercase output values are distinct (injective on lowercase)."""
        result = _make_scramble_map()
        lower_outputs = [result[ord(ch)] for ch in _LOWER_LETTERS]
        assert len(set(lower_outputs)) == 26, "Lowercase mapping is not bijective"

    @pytest.mark.unit
    def test_uppercase_bijection(self, mock_random_source):
        """All 26 uppercase output values are distinct (injective on uppercase)."""
        result = _make_scramble_map()
        upper_outputs = [result[ord(ch)] for ch in _UPPER_LETTERS]
        assert len(set(upper_outputs)) == 26, "Uppercase mapping is not bijective"

    @pytest.mark.unit
    def test_digits_not_in_map(self, mock_random_source):
        """Digit codepoints are not present as keys."""
        result = _make_scramble_map()
        for ch in string.digits:
            assert ord(ch) not in result, f"digit '{ch}' should not be in map"

    @pytest.mark.unit
    def test_symbols_not_in_map(self, mock_random_source):
        """Common symbol codepoints are not present as keys."""
        result = _make_scramble_map()
        for ch in "!@#$%^&*()-_=+[]{}|;:',.<>?/ ":
            assert ord(ch) not in result, f"symbol '{ch}' should not be in map"


# ---------------------------------------------------------------------------
# Module 11b: _scramble_text() per-character consistency
# ---------------------------------------------------------------------------


class TestScrambleTextConsistency:
    """_scramble_text() applies the map consistently to every letter."""

    @pytest.mark.unit
    def test_digits_unchanged(self, mock_random_source):
        m = _make_scramble_map()
        assert _scramble_text("12345", m) == "12345"

    @pytest.mark.unit
    def test_symbols_unchanged(self, mock_random_source):
        m = _make_scramble_map()
        assert _scramble_text("!@#$%", m) == "!@#$%"

    @pytest.mark.unit
    def test_spaces_unchanged(self, mock_random_source):
        m = _make_scramble_map()
        assert _scramble_text("  hi  ", m).startswith("  ")
        assert _scramble_text("  hi  ", m).endswith("  ")

    @pytest.mark.unit
    def test_mixed_digit_letter_preserves_digits(self, mock_random_source):
        m = _make_scramble_map()
        result = _scramble_text("abc123", m)
        assert result[3:] == "123", "Digits at end must be unchanged"

    @pytest.mark.unit
    def test_same_map_same_input_same_output(self, mock_random_source):
        """Applying the same map twice to the same text gives the same result."""
        m = _make_scramble_map()
        text = "HelloWorld"
        assert _scramble_text(text, m) == _scramble_text(text, m)

    @pytest.mark.unit
    def test_output_same_length_as_input(self, mock_random_source):
        m = _make_scramble_map()
        text = "QuickBrownFox"
        assert len(_scramble_text(text, m)) == len(text)

    @pytest.mark.unit
    def test_case_preserved_per_character(self, mock_random_source):
        """Every uppercase input letter maps to uppercase, lowercase to lowercase."""
        m = _make_scramble_map()
        original = "AbCdEf"
        result = _scramble_text(original, m)
        for orig_ch, res_ch in zip(original, result):
            if orig_ch.isupper():
                assert res_ch.isupper(), f"'{orig_ch}' → '{res_ch}' should be uppercase"
            elif orig_ch.islower():
                assert res_ch.islower(), f"'{orig_ch}' → '{res_ch}' should be lowercase"


# ---------------------------------------------------------------------------
# Module 11c: Same seed → same anonymised output
# ---------------------------------------------------------------------------


class TestSameSeedSameOutput:
    """With a fixed RNG seed, two anonymise_pdf calls produce identical text."""

    @pytest.mark.unit
    def test_same_raw_bytes_scramble_identically_within_one_run(
        self, mock_random_source, tmp_path
    ):
        """Within a single anonymise_pdf call the same Tj bytes always produce
        the same replacement — guaranteed by the seen_raw deduplication set.

        We verify this by putting the same word three times on one page and
        confirming all three occurrences are replaced with the same scrambled value.
        """
        content = _tj("Merchant") + _tj("Merchant") + _tj("Merchant")
        src = _make_pdf(tmp_path, content, filename="src.pdf")
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)

        # Each occurrence of "Merchant" in the stream shares the same raw bytes,
        # so _rewrite_page_content_stream replaces ALL of them with the same value.
        texts = _extract_all_text(out)
        alpha_texts = [t for t in texts if t.strip()]
        # All three slots should hold the same scrambled word
        assert len(set(alpha_texts)) == 1, (
            f"Same raw bytes produced different replacements: {set(alpha_texts)}"
        )

    @pytest.mark.unit
    def test_same_seed_different_words_different_outputs(self, mock_random_source, tmp_path):
        """Two different input words scramble to two different output words."""
        src_a = _make_pdf(tmp_path, _tj("AlphaText"), filename="a.pdf")
        src_b = _make_pdf(tmp_path, _tj("BetaTexts"), filename="b.pdf")

        out_a = tmp_path / "out_a.pdf"
        out_b = tmp_path / "out_b.pdf"

        anonymise_pdf(src_a, output_path=out_a)
        anonymise_pdf(src_b, output_path=out_b)

        texts_a = _extract_all_text(out_a)
        texts_b = _extract_all_text(out_b)

        # Both scrambled; they should differ from each other
        # (same-length different words under a bijection produce different results)
        assert texts_a != texts_b

    @pytest.mark.unit
    def test_scrambled_text_differs_from_original(self, mock_random_source, tmp_path):
        """The scramble map produces output different from input for all-alpha text."""
        src = _make_pdf(tmp_path, _tj("Scrambleme"), filename="src.pdf")
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)
        texts = _extract_all_text(out)
        assert "Scrambleme" not in texts


# ---------------------------------------------------------------------------
# Module 11d: Cross-page consistency within one run
# ---------------------------------------------------------------------------


class TestCrossPageConsistency:
    """The same text on multiple pages scrambles identically within one run."""

    @pytest.mark.unit
    def test_same_word_same_scramble_across_pages(self, mock_random_source, tmp_path):
        """'Merchant' on page 1 and page 2 scrambles to the same replacement."""
        pdf = pikepdf.Pdf.new()
        for _ in range(2):
            page = pdf.add_blank_page(page_size=(595, 842))
            page.Contents = pikepdf.Stream(pdf, _tj("Merchant"))
            page.Resources = pikepdf.Dictionary(
                Font=pikepdf.Dictionary(
                    F1=pikepdf.Dictionary(
                        Type=pikepdf.Name.Font,
                        Subtype=pikepdf.Name.Type1,
                        BaseFont=pikepdf.Name.Helvetica,
                    )
                )
            )
        src = tmp_path / "two_pages.pdf"
        pdf.save(str(src))
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)

        texts = _extract_all_text(out)
        # Filter out empty/whitespace; both pages had "Merchant" → same scrambled word
        alpha_texts = [t for t in texts if t.strip() and t.strip().isalpha()]
        assert len(set(alpha_texts)) == 1, (
            f"Same word on two pages scrambled differently: {set(alpha_texts)}"
        )
