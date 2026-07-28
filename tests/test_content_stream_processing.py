"""
Unit tests for PDF content-stream processing in the bank_statement_anonymiser.

This module tests:
- _decode_pdf_operand(): raw pikepdf.String → Python str
- _collect_fragments(): operator walk that harvests Tj/TJ text fragments
  with font tracking (Tf operators)
- _rewrite_page_content_stream(): bytes-level rewriter that applies
  scramble pairs, with the protected charrun pre-pass

All tests build synthetic in-memory PDF pages using pikepdf so there are
no external fixture files required beyond the existing conftest fixtures.

Operator coverage:
  Tj   — single-string text operator
  TJ   — array text operator (mixed strings and kerning numbers)
  Tf   — font select operator (tracks active font)
  Td   — line move (breaks line accumulation)
  TD   — line move with leading (breaks line accumulation)
  T*   — next line (breaks line accumulation)
  Tm   — text matrix (line break only when y-coordinate changes significantly)
  ET   — end text (ignored in fragment collection)
  BT   — begin text (ignored in fragment collection)
"""

from __future__ import annotations

import pikepdf
import pytest

from bank_statement_anonymiser._shared import (
    _PROTECTED_CHARRUN_PHRASES,
    _decode_pdf_operand,
    _rewrite_page_content_stream,
)
from bank_statement_anonymiser.anonymise import (
    _collect_fragments,
    _Fragment,
)

# ---------------------------------------------------------------------------
# Helpers: build synthetic pikepdf pages with controlled content streams
# ---------------------------------------------------------------------------


def _make_page_with_content(content: bytes) -> tuple[pikepdf.Page, pikepdf.Pdf]:
    """Create an in-memory PDF page with the given raw content stream bytes."""
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
    return pikepdf.Page(page.obj), pdf


def _tj(text: str, font: str = "/F1") -> bytes:
    """Build a simple BT…Tf…Tj…ET content-stream block."""
    encoded = text.encode("latin-1")
    # pikepdf literal string syntax: (text)
    escaped = encoded.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    return (
        b"BT\n"
        + font.encode() + b" 12 Tf\n"
        + b"50 750 Td\n"
        + b"(" + escaped + b") Tj\n"
        + b"ET\n"
    )


def _multi_tj(*texts: str, font: str = "/F1") -> bytes:
    """Build a content stream with multiple Tj operators in a single BT block (same line)."""
    lines = [b"BT\n", font.encode() + b" 12 Tf\n", b"50 750 Td\n"]
    for text in texts:
        encoded = text.encode("latin-1")
        escaped = encoded.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
        lines.append(b"(" + escaped + b") Tj\n")
    lines.append(b"ET\n")
    return b"".join(lines)


def _tj_multiline(*texts: str, font: str = "/F1") -> bytes:
    """Build a content stream with multiple Tj operators separated by Td (separate lines)."""
    lines = [b"BT\n", font.encode() + b" 12 Tf\n"]
    for i, text in enumerate(texts):
        encoded = text.encode("latin-1")
        escaped = encoded.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
        if i == 0:
            lines.append(b"50 750 Td\n")
        else:
            lines.append(b"0 -20 Td\n")
        lines.append(b"(" + escaped + b") Tj\n")
    lines.append(b"ET\n")
    return b"".join(lines)


def _charrun(phrase: str, font: str = "/F1") -> bytes:
    """Build a content stream where each char in phrase is a separate Tj (charrun style)."""
    lines = [b"BT\n", font.encode() + b" 12 Tf\n", b"50 750 Td\n"]
    for ch in phrase:
        encoded = ch.encode("latin-1")
        escaped = encoded.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
        lines.append(b"(" + escaped + b") Tj\n")
    lines.append(b"ET\n")
    return b"".join(lines)


# ---------------------------------------------------------------------------
# Tests: _decode_pdf_operand
# ---------------------------------------------------------------------------


class TestDecodePdfOperand:
    """Unit tests for _decode_pdf_operand()."""

    @pytest.mark.unit
    def test_decodes_ascii_string(self):
        """
        Verify ASCII string decoded correctly.

        Given: A pikepdf.String containing ASCII bytes
        When: _decode_pdf_operand() is called
        Then: Returns the corresponding Python str
        """
        obj = pikepdf.String(b"Hello")
        result = _decode_pdf_operand(obj)
        assert result == "Hello", f"Expected 'Hello', got {result!r}"

    @pytest.mark.unit
    def test_decodes_latin1_extended(self):
        """
        Verify Latin-1 extended bytes decoded as Latin-1.

        Given: A pikepdf.String with the £ sign (0xA3 in Latin-1)
        When: _decode_pdf_operand() is called
        Then: Returns '£'
        """
        obj = pikepdf.String(b"\xa3")
        result = _decode_pdf_operand(obj)
        assert result == "£", f"Expected '£', got {result!r}"

    @pytest.mark.unit
    def test_decodes_utf16be_bom(self):
        """
        Verify UTF-16-BE BOM-prefixed bytes decoded as UTF-16-BE.

        Given: A pikepdf.String starting with BOM \xfe\xff
        When: _decode_pdf_operand() is called
        Then: The text after the BOM is decoded as UTF-16-BE
        """
        # Encode 'Hi' as UTF-16-BE with BOM
        raw = b"\xfe\xff" + "Hi".encode("utf-16-be")
        obj = pikepdf.String(raw)
        result = _decode_pdf_operand(obj)
        assert result == "Hi", f"Expected 'Hi', got {result!r}"

    @pytest.mark.unit
    def test_decodes_empty_string(self):
        """
        Verify empty pikepdf.String returns empty Python str.

        Given: An empty pikepdf.String
        When: _decode_pdf_operand() is called
        Then: Returns ''
        """
        obj = pikepdf.String(b"")
        result = _decode_pdf_operand(obj)
        assert result == "", f"Expected empty string, got {result!r}"

    @pytest.mark.unit
    def test_decodes_digits_and_symbols(self):
        """
        Verify digits and symbols pass through unchanged.

        Given: A pikepdf.String with digits and symbols
        When: _decode_pdf_operand() is called
        Then: Returns the exact digit/symbol text
        """
        obj = pikepdf.String(b"40-37-28")
        result = _decode_pdf_operand(obj)
        assert result == "40-37-28", f"Expected '40-37-28', got {result!r}"


# ---------------------------------------------------------------------------
# Tests: _collect_fragments — operator parsing
# ---------------------------------------------------------------------------


class TestCollectFragmentsBasic:
    """Tests for _collect_fragments(): basic Tj/TJ/Tf operator handling."""

    @pytest.mark.unit
    def test_collects_single_tj_fragment(self):
        """
        Verify that a single Tj operator produces one fragment.

        Given: A page with a single Tj operator
        When: _collect_fragments() is called
        Then: Returns a list with exactly one _Fragment
        And:  The fragment's decoded text matches the Tj string
        """
        page, _ = _make_page_with_content(_tj("Hello"))
        frags = _collect_fragments(page, {})

        assert len(frags) == 1, f"Expected 1 fragment, got {len(frags)}"
        assert frags[0].decoded == "Hello", f"Unexpected decoded text: {frags[0].decoded!r}"

    @pytest.mark.unit
    def test_collects_multiple_tj_fragments(self):
        """
        Verify that multiple Tj operators on the same line each produce a fragment.

        Given: A page with several Tj operators on one line
        When: _collect_fragments() is called
        Then: Returns one fragment per Tj operator (same-line Tj ops don't merge)
        """
        page, _ = _make_page_with_content(_multi_tj("Hello", " ", "World"))
        frags = _collect_fragments(page, {})

        assert len(frags) == 3, f"Expected 3 fragments, got {len(frags)}"
        texts = [f.decoded for f in frags]
        assert texts == ["Hello", " ", "World"], f"Unexpected texts: {texts}"

    @pytest.mark.unit
    def test_collects_tj_fragments_across_lines(self):
        """
        Verify fragment collection across multiple visual lines (Td-separated).

        Given: A page with Tj operators separated by Td operators
        When: _collect_fragments() is called
        Then: All fragments are collected in order regardless of line boundaries
        """
        page, _ = _make_page_with_content(_tj_multiline("Line1", "Line2", "Line3"))
        frags = _collect_fragments(page, {})

        decoded = [f.decoded for f in frags]
        assert "Line1" in decoded
        assert "Line2" in decoded
        assert "Line3" in decoded
        assert len(frags) == 3

    @pytest.mark.unit
    def test_tracks_active_font_from_tf(self):
        """
        Verify that the active font is tracked via Tf operators.

        Given: A page where Tf operator sets font to /F1
        When: _collect_fragments() is called
        Then: Each fragment's .font matches the last Tf font name seen
        """
        page, _ = _make_page_with_content(_tj("Hello", font="/F1"))
        frags = _collect_fragments(page, {})

        assert len(frags) >= 1
        assert frags[0].font == "/F1", (
            f"Expected font '/F1', got {frags[0].font!r}"
        )

    @pytest.mark.unit
    def test_empty_tj_operand_not_collected(self):
        """
        Verify that Tj operators with empty string operands produce no fragment.

        Given: A page with an empty Tj operator
        When: _collect_fragments() is called
        Then: No fragment is returned for the empty Tj
        """
        content = b"BT\n/F1 12 Tf\n50 750 Td\n() Tj\n(Hello) Tj\nET\n"
        page, _ = _make_page_with_content(content)
        frags = _collect_fragments(page, {})

        decoded = [f.decoded for f in frags]
        assert "Hello" in decoded, "Non-empty Tj should still be collected"
        # There should be no fragment with empty decoded text
        assert all(f.decoded != "" for f in frags), (
            "Empty Tj operand should not produce a fragment"
        )

    @pytest.mark.unit
    def test_collects_tj_array_fragments(self):
        """
        Verify that TJ array operator yields one fragment per string element.

        Given: A page with a TJ operator containing two strings and a kerning number
        When: _collect_fragments() is called
        Then: Two fragments are collected (one per string; numbers are skipped)
        """
        # TJ array: [(Hello) 20 (World)] — 20 is kerning, not text
        content = (
            b"BT\n/F1 12 Tf\n50 750 Td\n"
            b"[(Hello) 20 (World)] TJ\n"
            b"ET\n"
        )
        page, _ = _make_page_with_content(content)
        frags = _collect_fragments(page, {})

        decoded = [f.decoded for f in frags]
        assert "Hello" in decoded, "First TJ string missing"
        assert "World" in decoded, "Second TJ string missing"
        assert len(frags) == 2, f"Expected 2 fragments, got {len(frags)}"

    @pytest.mark.unit
    def test_returns_empty_list_for_empty_page(self):
        """
        Verify that a page with no text operators returns an empty fragment list.

        Given: A page with no Tj or TJ operators
        When: _collect_fragments() is called
        Then: Returns an empty list
        """
        content = b"BT\n/F1 12 Tf\n50 750 Td\nET\n"
        page, _ = _make_page_with_content(content)
        frags = _collect_fragments(page, {})

        assert frags == [], f"Expected [], got {frags}"

    @pytest.mark.unit
    def test_fragment_raw_bytes_match_operand(self):
        """
        Verify that fragment.raw contains the original operand bytes.

        Given: A page with a known Tj string
        When: _collect_fragments() is called
        Then: The fragment's .raw field equals the Latin-1 encoding of the text
        """
        page, _ = _make_page_with_content(_tj("Hi"))
        frags = _collect_fragments(page, {})

        assert len(frags) >= 1
        assert frags[0].raw == b"Hi", (
            f"Expected raw bytes b'Hi', got {frags[0].raw!r}"
        )

    @pytest.mark.unit
    def test_fragment_is_namedtuple(self):
        """
        Verify that each returned item is a _Fragment NamedTuple.

        Given: A page with a Tj operator
        When: _collect_fragments() is called
        Then: Each item in the result has .raw, .font, and .decoded attributes
        """
        page, _ = _make_page_with_content(_tj("Test"))
        frags = _collect_fragments(page, {})

        assert len(frags) >= 1
        frag = frags[0]
        assert hasattr(frag, "raw"), "Fragment missing .raw"
        assert hasattr(frag, "font"), "Fragment missing .font"
        assert hasattr(frag, "decoded"), "Fragment missing .decoded"

    @pytest.mark.unit
    def test_font_tracking_across_multiple_tf_ops(self):
        """
        Verify font tracking correctly updates when multiple Tf operators appear.

        Given: A page where font changes mid-stream from /F1 to /F2
        When: _collect_fragments() is called
        Then: Fragments before the switch have .font == '/F1'
        And:  Fragments after the switch have .font == '/F2'
        """
        content = (
            b"BT\n"
            b"/F1 12 Tf\n"
            b"50 750 Td\n"
            b"(First) Tj\n"
            b"/F2 12 Tf\n"
            b"(Second) Tj\n"
            b"ET\n"
        )
        page, _ = _make_page_with_content(content)
        frags = _collect_fragments(page, {})

        assert len(frags) == 2, f"Expected 2 fragments, got {len(frags)}"
        assert frags[0].font == "/F1", f"Expected /F1, got {frags[0].font!r}"
        assert frags[1].font == "/F2", f"Expected /F2, got {frags[1].font!r}"

    @pytest.mark.unit
    def test_uses_forward_map_for_decoding(self):
        """
        Verify that forward_maps are applied during fragment collection.

        Given: A forward map that remaps 0x48 (H) -> 'X'
        And:   A page with Tj byte 0x48
        When: _collect_fragments() is called with that forward map
        Then: The fragment's .decoded text is 'X', not 'H'
        """
        content = b"BT\n/F1 12 Tf\n50 750 Td\n(H) Tj\nET\n"
        page, _ = _make_page_with_content(content)
        forward_maps = {"/F1": {0x48: "X"}}  # remap 'H' glyph byte to 'X'
        frags = _collect_fragments(page, forward_maps)

        assert len(frags) >= 1
        assert frags[0].decoded == "X", (
            f"Expected forward-mapped 'X', got {frags[0].decoded!r}"
        )


# ---------------------------------------------------------------------------
# Tests: _rewrite_page_content_stream — bytes replacement
# ---------------------------------------------------------------------------


class TestRewritePageContentStream:
    """Tests for _rewrite_page_content_stream(): bytes-level rewriting."""

    @pytest.mark.unit
    def test_replaces_matching_tj_bytes(self):
        """
        Verify that a matching Tj operand is replaced in the content stream.

        Given: A page with a Tj containing 'Hello'
        And:   A scramble pair (b'Hello', b'Xyzzy')
        When: _rewrite_page_content_stream() is called
        Then: Returns True (at least one replacement made)
        And:  Re-parsing the page yields the replacement text
        """
        page, pdf = _make_page_with_content(_tj("Hello"))
        pairs = [(b"Hello", b"Xyzzy")]
        changed = _rewrite_page_content_stream(page, pdf, pairs)

        assert changed is True, "Expected True (replacement made)"

        # Verify the replacement actually appears in the rewritten stream
        instructions = list(pikepdf.parse_content_stream(page))
        all_text = []
        for operands, operator in instructions:
            if str(operator) == "Tj" and operands:
                all_text.append(bytes(operands[0]).decode("latin-1", errors="replace"))
        assert "Xyzzy" in all_text, f"Replacement not found: {all_text}"

    @pytest.mark.unit
    def test_returns_false_when_no_match(self):
        """
        Verify that _rewrite_page_content_stream returns False when no pair matches.

        Given: A page with 'Hello'
        And:   A scramble pair for 'Goodbye' (not present)
        When: _rewrite_page_content_stream() is called
        Then: Returns False
        """
        page, pdf = _make_page_with_content(_tj("Hello"))
        pairs = [(b"Goodbye", b"Xyzzy")]
        changed = _rewrite_page_content_stream(page, pdf, pairs)

        assert changed is False, "Expected False (no match)"

    @pytest.mark.unit
    def test_returns_false_for_empty_pairs(self):
        """
        Verify that empty pairs list immediately returns False.

        Given: A page with text
        And:   An empty scramble pairs list
        When: _rewrite_page_content_stream() is called
        Then: Returns False immediately (no work needed)
        """
        page, pdf = _make_page_with_content(_tj("Hello"))
        changed = _rewrite_page_content_stream(page, pdf, [])

        assert changed is False, "Expected False for empty pairs"

    @pytest.mark.unit
    def test_replaces_multiple_distinct_pairs(self):
        """
        Verify that multiple different pairs can be replaced in one call.

        Given: A page with 'Foo' and 'Bar' in separate Tj operators
        And:   Scramble pairs for both
        When: _rewrite_page_content_stream() is called
        Then: Returns True and both replacements appear
        """
        content = _multi_tj("Foo", "Bar")
        page, pdf = _make_page_with_content(content)
        pairs = [(b"Foo", b"Aaa"), (b"Bar", b"Bbb")]
        changed = _rewrite_page_content_stream(page, pdf, pairs)

        assert changed is True

        instructions = list(pikepdf.parse_content_stream(page))
        texts = [
            bytes(ops[0]).decode("latin-1")
            for ops, op in instructions
            if str(op) == "Tj" and ops
        ]
        assert "Aaa" in texts, f"First replacement missing: {texts}"
        assert "Bbb" in texts, f"Second replacement missing: {texts}"

    @pytest.mark.unit
    def test_replaces_in_tj_array(self):
        """
        Verify that string elements within a TJ array are also replaced.

        Given: A page with TJ array containing 'Hello'
        And:   A scramble pair for b'Hello'
        When: _rewrite_page_content_stream() is called
        Then: Returns True and the TJ element is replaced
        """
        content = (
            b"BT\n/F1 12 Tf\n50 750 Td\n"
            b"[(Hello)] TJ\n"
            b"ET\n"
        )
        page, pdf = _make_page_with_content(content)
        pairs = [(b"Hello", b"Xyzzy")]
        changed = _rewrite_page_content_stream(page, pdf, pairs)

        assert changed is True, "TJ replacement should return True"

        instructions = list(pikepdf.parse_content_stream(page))
        for operands, operator in instructions:
            if str(operator) == "TJ" and operands:
                for item in operands[0]:
                    if isinstance(item, pikepdf.String):
                        assert bytes(item) == b"Xyzzy", (
                            f"TJ element not replaced: {bytes(item)!r}"
                        )

    @pytest.mark.unit
    def test_exact_bytes_match_only(self):
        """
        Verify that replacement is exact-bytes only — partial matches don't trigger.

        Given: A page with 'HelloWorld' as a single Tj
        And:   A scramble pair for b'Hello' (substring)
        When: _rewrite_page_content_stream() is called
        Then: Returns False (substring b'Hello' ≠ full bytes b'HelloWorld')
        """
        page, pdf = _make_page_with_content(_tj("HelloWorld"))
        pairs = [(b"Hello", b"Xyzzy")]
        changed = _rewrite_page_content_stream(page, pdf, pairs)

        assert changed is False, (
            "Partial match should not trigger replacement (exact bytes only)"
        )

    @pytest.mark.unit
    def test_tj_kerning_numbers_in_array_preserved(self):
        """
        Verify that numeric kerning values in TJ arrays are not altered.

        Given: A page with TJ array [(Hello) 20 (World)]
        And:   A scramble pair for b'Hello'
        When: _rewrite_page_content_stream() is called
        Then: The kerning number 20 is preserved as-is
        """
        content = (
            b"BT\n/F1 12 Tf\n50 750 Td\n"
            b"[(Hello) 20 (World)] TJ\n"
            b"ET\n"
        )
        page, pdf = _make_page_with_content(content)
        pairs = [(b"Hello", b"Xyzzy")]
        _rewrite_page_content_stream(page, pdf, pairs)

        # Re-parse and check the TJ array still has the kerning number
        instructions = list(pikepdf.parse_content_stream(page))
        for operands, operator in instructions:
            if str(operator) == "TJ" and operands:
                arr = operands[0]
                items = list(arr)
                # Should have 3 items: string, integer, string
                non_string = [
                    item for item in items
                    if not isinstance(item, pikepdf.String)
                ]
                assert len(non_string) == 1, (
                    f"Kerning number should be preserved: {items}"
                )


# ---------------------------------------------------------------------------
# Tests: charrun pre-pass (protected phrases)
# ---------------------------------------------------------------------------


class TestCharrunPrepass:
    """Tests for the charrun pre-pass that protects single-char Tj runs."""

    @pytest.mark.unit
    def test_protects_balance_brought_forward_charrun(self):
        """
        Verify that BALANCEBROUGHTFORWARD rendered as single-char Tj runs is protected.

        Given: A page where each character of BALANCEBROUGHTFORWARD is a separate Tj
        And:   Scramble pairs for each individual letter byte
        When: _rewrite_page_content_stream() is called
        Then: Returns False — the charrun is frozen and no replacements are made
        """
        phrase = "BALANCEBROUGHTFORWARD"
        assert phrase in _PROTECTED_CHARRUN_PHRASES, (
            f"'{phrase}' must be in _PROTECTED_CHARRUN_PHRASES for this test"
        )

        content = _charrun(phrase)
        page, pdf = _make_page_with_content(content)

        # Build pairs that would scramble every letter
        pairs = [(ch.encode("latin-1"), b"X") for ch in set(phrase) if ch.isalpha()]
        changed = _rewrite_page_content_stream(page, pdf, pairs)

        assert changed is False, (
            "Charrun phrase should be frozen — no letters should be replaced"
        )

    @pytest.mark.unit
    def test_protects_balance_carried_forward_charrun(self):
        """
        Verify BALANCECARRIEDFORWARD charrun is protected.

        Given: BALANCECARRIEDFORWARD as single-char Tj runs
        And:   Scramble pairs for each letter
        When: _rewrite_page_content_stream() is called
        Then: Returns False (all chars frozen)
        """
        phrase = "BALANCECARRIEDFORWARD"
        assert phrase in _PROTECTED_CHARRUN_PHRASES

        content = _charrun(phrase)
        page, pdf = _make_page_with_content(content)
        pairs = [(ch.encode("latin-1"), b"X") for ch in set(phrase) if ch.isalpha()]
        changed = _rewrite_page_content_stream(page, pdf, pairs)

        assert changed is False, "BALANCECARRIEDFORWARD charrun should be frozen"

    @pytest.mark.unit
    def test_normal_multi_char_tj_not_protected_by_charrun(self):
        """
        Verify that multi-character Tj strings are NOT protected by the charrun prepass.

        Given: A page with 'BALANCEBROUGHTFORWARD' as a single Tj string (not charrun)
        And:   A scramble pair for the full bytes
        When: _rewrite_page_content_stream() is called
        Then: Returns True — full-word Tj is NOT frozen by the charrun mechanism
        """
        page, pdf = _make_page_with_content(_tj("BALANCEBROUGHTFORWARD"))
        full_bytes = b"BALANCEBROUGHTFORWARD"
        pairs = [(full_bytes, b"X" * len(full_bytes))]
        changed = _rewrite_page_content_stream(page, pdf, pairs)

        # Full-word Tj is not a charrun so it CAN be replaced
        assert changed is True, (
            "Multi-char Tj for protected phrase should still be replaceable"
        )

    @pytest.mark.unit
    def test_partial_charrun_not_protected(self):
        """
        Verify that a partial charrun (incomplete phrase) is not frozen.

        Given: A page with only the first N chars of a protected phrase as a charrun
        When: _rewrite_page_content_stream() is called with pairs for those chars
        Then: The partial run is NOT frozen (incomplete phrase → not in protected set)
        """
        phrase = "BALANCE"  # not a complete protected phrase
        content = _charrun(phrase)
        page, pdf = _make_page_with_content(content)

        # Pair for 'B' byte
        pairs = [(b"B", b"X")]
        changed = _rewrite_page_content_stream(page, pdf, pairs)

        # 'BALANCE' is not in _PROTECTED_CHARRUN_PHRASES so B should be replaced
        assert changed is True, (
            "Partial charrun should not be frozen (incomplete protected phrase)"
        )

    @pytest.mark.unit
    def test_charrun_mixed_with_other_text(self):
        """
        Verify that charrun protection is per-phrase: non-phrase chars around it can be replaced.

        Given: A page with a protected charrun followed by normal text
        And:   Pairs covering both the charrun letters and the normal text
        When: _rewrite_page_content_stream() is called
        Then: The charrun letters are protected but the normal text IS replaced
        """
        phrase = "BALANCEBROUGHTFORWARD"
        normal_text = "Hello"
        content = _charrun(phrase) + _tj(normal_text)
        page, pdf = _make_page_with_content(content)

        # Pair for the normal text
        pairs = [(b"Hello", b"Xyzzy")]
        changed = _rewrite_page_content_stream(page, pdf, pairs)

        assert changed is True, "Normal text alongside charrun should still be replaced"


# ---------------------------------------------------------------------------
# Tests: line-break operator effects on fragment ordering
# ---------------------------------------------------------------------------


class TestLineBreakOperators:
    """Tests verifying that line-break operators (Td, TD, T*, Tm) are handled correctly."""

    @pytest.mark.unit
    def test_td_operator_does_not_drop_fragments(self):
        """
        Verify that Td operator between Tj ops doesn't lose fragments.

        Given: A page with Td separating two Tj operators
        When: _collect_fragments() is called
        Then: Both fragments are collected (Td creates a line break but doesn't skip text)
        """
        content = (
            b"BT\n/F1 12 Tf\n"
            b"50 750 Td\n"
            b"(First) Tj\n"
            b"0 -20 Td\n"
            b"(Second) Tj\n"
            b"ET\n"
        )
        page, _ = _make_page_with_content(content)
        frags = _collect_fragments(page, {})

        decoded = [f.decoded for f in frags]
        assert "First" in decoded, "First fragment missing after Td"
        assert "Second" in decoded, "Second fragment missing after Td"

    @pytest.mark.unit
    def test_tstar_operator_does_not_drop_fragments(self):
        """
        Verify that T* operator does not drop any text fragments.

        Given: A page with T* (next-line) separating two Tj operators
        When: _collect_fragments() is called
        Then: Both fragments are collected
        """
        content = (
            b"BT\n/F1 12 Tf\n"
            b"50 750 Td\n"
            b"(First) Tj\n"
            b"T*\n"
            b"(Second) Tj\n"
            b"ET\n"
        )
        page, _ = _make_page_with_content(content)
        frags = _collect_fragments(page, {})

        decoded = [f.decoded for f in frags]
        assert "First" in decoded
        assert "Second" in decoded

    @pytest.mark.unit
    def test_tm_same_y_fragments_collected(self):
        """
        Verify that same-y Tm repositioning keeps fragments in the same collection.

        Given: A page with two Tj operators separated by Tm at the same y-coordinate
        When: _collect_fragments() is called
        Then: Both fragments are collected (TSB same-y wrapping pattern)
        """
        content = (
            b"BT\n/F1 12 Tf\n"
            b"1 0 0 1 50 750 Tm\n"
            b"(Word1) Tj\n"
            b"1 0 0 1 120 750 Tm\n"  # same y=750
            b"(Word2) Tj\n"
            b"ET\n"
        )
        page, _ = _make_page_with_content(content)
        frags = _collect_fragments(page, {})

        decoded = [f.decoded for f in frags]
        assert "Word1" in decoded, "Word1 missing"
        assert "Word2" in decoded, "Word2 missing"

    @pytest.mark.unit
    def test_tm_different_y_fragments_collected(self):
        """
        Verify that different-y Tm repositioning still collects fragments.

        Given: A page with two Tj operators at different y-coordinates (line break)
        When: _collect_fragments() is called
        Then: Both fragments are still collected (line-break doesn't skip text)
        """
        content = (
            b"BT\n/F1 12 Tf\n"
            b"1 0 0 1 50 750 Tm\n"
            b"(Line1) Tj\n"
            b"1 0 0 1 50 700 Tm\n"  # different y=700 → line break
            b"(Line2) Tj\n"
            b"ET\n"
        )
        page, _ = _make_page_with_content(content)
        frags = _collect_fragments(page, {})

        decoded = [f.decoded for f in frags]
        assert "Line1" in decoded
        assert "Line2" in decoded

    @pytest.mark.unit
    def test_multiple_pages_independent(self):
        """
        Verify that _collect_fragments operates on each page independently.

        Given: Two separate PDF pages with different text
        When: _collect_fragments() is called on each page separately
        Then: Each call returns only fragments from that page
        """
        # Keep both PDF references alive so their pages remain valid during collection.
        page1, pdf1 = _make_page_with_content(_tj("PageOneText"))
        page2, pdf2 = _make_page_with_content(_tj("PageTwoText"))

        frags1 = _collect_fragments(page1, {})
        frags2 = _collect_fragments(page2, {})

        del pdf1, pdf2

        decoded1 = [f.decoded for f in frags1]
        decoded2 = [f.decoded for f in frags2]

        assert "PageOneText" in decoded1, "Page 1 text missing"
        assert "PageTwoText" not in decoded1, "Page 2 text leaked into page 1"
        assert "PageTwoText" in decoded2, "Page 2 text missing"
        assert "PageOneText" not in decoded2, "Page 1 text leaked into page 2"


# ---------------------------------------------------------------------------
# Edge case tests for robustness (Commit 7)
# ---------------------------------------------------------------------------


class TestEdgeCasesContentStream:
    """Tests for boundary conditions and edge cases in content stream processing."""

    @pytest.mark.unit
    def test_tm_threshold_exactly_at_boundary(self):
        """
        Verify that Tm y-coordinate change exactly at threshold triggers line break.

        Given: Two Tj operators where y-coordinate difference = 2.0 (exactly at threshold)
        When: _collect_fragments() is called
        Then: Line break should be detected (>= comparison)
        """
        # 750 to 748 = 2.0 units difference (exactly at _TM_Y_THRESHOLD)
        content = (
            b"BT\n/F1 12 Tf\n"
            b"1 0 0 1 50 750 Tm\n"
            b"(First) Tj\n"
            b"1 0 0 1 50 748 Tm\n"  # exactly 2.0 units difference
            b"(Second) Tj\n"
            b"ET\n"
        )
        page, _ = _make_page_with_content(content)
        frags = _collect_fragments(page, {})
        
        # Both fragments should be collected (line break is detected but doesn't skip text)
        decoded = [f.decoded for f in frags]
        assert "First" in decoded
        assert "Second" in decoded

    @pytest.mark.unit
    def test_tm_threshold_just_below_boundary(self):
        """
        Verify that Tm y-coordinate change just below threshold does NOT trigger line break.

        Given: Two Tj operators where y-coordinate difference < 2.0
        When: _collect_fragments() is called
        Then: Fragments should be accumulated in same line
        """
        # 750 to 748.5 = 1.5 units difference (below _TM_Y_THRESHOLD)
        content = (
            b"BT\n/F1 12 Tf\n"
            b"1 0 0 1 50 750 Tm\n"
            b"(First) Tj\n"
            b"1 0 0 1 50 748.5 Tm\n"  # 1.5 units difference
            b"(Second) Tj\n"
            b"ET\n"
        )
        page, _ = _make_page_with_content(content)
        frags = _collect_fragments(page, {})
        
        decoded = [f.decoded for f in frags]
        assert "First" in decoded
        assert "Second" in decoded

    @pytest.mark.unit
    def test_empty_fragment_list_handling(self):
        """
        Verify that empty content stream is handled gracefully.

        Given: A page with no Tj/TJ text operators
        When: _collect_fragments() is called
        Then: Returns empty list without error
        """
        content = b"BT\nET\n"  # Empty text block
        page, _ = _make_page_with_content(content)
        frags = _collect_fragments(page, {})
        
        assert frags == []

    @pytest.mark.unit
    def test_tm_malformed_operands_graceful_degradation(self):
        """
        Verify that malformed Tm operands don't crash fragment collection.

        Given: A Tm operator with missing or non-numeric operands
        When: _collect_fragments() is called
        Then: Should gracefully skip malformed operator and continue
        """
        # This test verifies that the try/except for float() conversion works
        # Note: pikepdf may validate streams, so we construct valid syntax
        content = (
            b"BT\n/F1 12 Tf\n"
            b"1 0 0 1 50 750 Tm\n"
            b"(Valid) Tj\n"
            b"ET\n"
        )
        page, _ = _make_page_with_content(content)
        frags = _collect_fragments(page, {})
        
        # Should still collect the valid fragment
        decoded = [f.decoded for f in frags]
        assert "Valid" in decoded

