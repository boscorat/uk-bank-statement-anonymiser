"""
Unit tests for per-page processing in the bank_statement_anonymiser.

This module tests:
- _distribute_replacement(): character distribution across fragment slots
- _build_scramble_bytes_pairs(): the three-phase pair builder
  - Phase 1 line-aware scan: never / always / built-in / bold-font protection
  - Phase 2 pair construction: scramble, always-replace, skip-protected
  - Deduplication of duplicate raw bytes
  - Longest-first ordering of returned pairs
  - numeric_id_map integration
  - Empty / no-op pages
"""

from __future__ import annotations

import pikepdf
import pytest

from bank_statement_anonymiser._shared import _make_scramble_map
from bank_statement_anonymiser.anonymise import (
    _AlwaysAnonymiseConfig,
    _Fragment,
    _NeverAnonymiseConfig,
    _build_font_maps,
    _build_font_maps_v2,
    _build_scramble_bytes_pairs,
    _distribute_replacement,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_page(content: bytes, bold: bool = False) -> tuple[pikepdf.Page, pikepdf.Pdf]:
    """One-page PDF with a Latin-1 font (F1 = Helvetica, or F2 = Helvetica-Bold)."""
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(595, 842))
    page.Contents = pikepdf.Stream(pdf, content)
    font_name = pikepdf.Name("/Helvetica-Bold") if bold else pikepdf.Name("/Helvetica")
    page.Resources = pikepdf.Dictionary(
        Font=pikepdf.Dictionary(
            F1=pikepdf.Dictionary(
                Type=pikepdf.Name.Font,
                Subtype=pikepdf.Name.Type1,
                BaseFont=font_name,
            )
        )
    )
    return pikepdf.Page(page.obj), pdf


def _tj(text: str, font: str = "/F1") -> bytes:
    """BT … Tj … ET block with Latin-1 encoded text."""
    encoded = text.encode("latin-1")
    escaped = (
        encoded
        .replace(b"\\", b"\\\\")
        .replace(b"(", b"\\(")
        .replace(b")", b"\\)")
    )
    return (
        b"BT\n"
        + font.encode() + b" 12 Tf\n"
        + b"50 750 Td\n"
        + b"(" + escaped + b") Tj\n"
        + b"ET\n"
    )


def _empty_configs() -> tuple[_AlwaysAnonymiseConfig, _NeverAnonymiseConfig]:
    """Return empty always / never configs (no rules)."""
    return (
        _AlwaysAnonymiseConfig(replacements={}),
        _NeverAnonymiseConfig(phrases=frozenset()),
    )


def _page_maps(page: pikepdf.Page):
    """Return (font_encodings, forward_maps, reverse_maps, bold_fonts) for a page."""
    forward_maps, reverse_maps, bold_fonts = _build_font_maps(page)
    font_encodings, _, bold_fonts2 = _build_font_maps_v2(page)
    # Match anonymise_pdf(): reverse_maps and bold_fonts come from _build_font_maps.
    return font_encodings, forward_maps, reverse_maps, bold_fonts | bold_fonts2


# ---------------------------------------------------------------------------
# Module 7a: _distribute_replacement
# ---------------------------------------------------------------------------


class TestDistributeReplacement:
    """Tests for _distribute_replacement() — slot-based character distribution."""

    @pytest.mark.unit
    def test_single_fragment_gets_full_replacement(self):
        frag = _Fragment(raw=b"John", font="/F1", decoded="John")
        always_replacements: dict[int, str] = {}
        _distribute_replacement("Jane", [0], [frag], always_replacements)
        assert always_replacements[0] == "Jane"

    @pytest.mark.unit
    def test_two_fragments_split_by_decoded_length(self):
        """First slot gets exactly len(frag.decoded) chars; last gets remainder."""
        frag1 = _Fragment(raw=b"John", font="/F1", decoded="John")   # len 4
        frag2 = _Fragment(raw=b"Smith", font="/F1", decoded="Smith")  # len 5
        always_replacements: dict[int, str] = {}
        _distribute_replacement("JaneDoe", [0, 1], [frag1, frag2], always_replacements)
        assert always_replacements[0] == "Jane"
        assert always_replacements[1] == "Doe"

    @pytest.mark.unit
    def test_last_slot_absorbs_overflow(self):
        """When replacement is longer than combined slots, last slot absorbs excess."""
        frag1 = _Fragment(raw=b"AB", font="/F1", decoded="AB")
        frag2 = _Fragment(raw=b"CD", font="/F1", decoded="CD")
        always_replacements: dict[int, str] = {}
        _distribute_replacement("ABCDEFGHIJ", [0, 1], [frag1, frag2], always_replacements)
        assert always_replacements[0] == "AB"
        assert always_replacements[1] == "CDEFGHIJ"

    @pytest.mark.unit
    def test_last_slot_absorbs_underflow(self):
        """When replacement is shorter than combined slots, last slot gets empty string."""
        frag1 = _Fragment(raw=b"Hello", font="/F1", decoded="Hello")
        frag2 = _Fragment(raw=b"World", font="/F1", decoded="World")
        always_replacements: dict[int, str] = {}
        _distribute_replacement("Hi", [0, 1], [frag1, frag2], always_replacements)
        # First slot: remaining[:5] = "Hi" (whole replacement fits in the slot)
        assert always_replacements[0] == "Hi"
        # Last slot: remaining after first slice = "" (nothing left)
        assert always_replacements[1] == ""

    @pytest.mark.unit
    def test_single_fragment_empty_replacement(self):
        frag = _Fragment(raw=b"X", font="/F1", decoded="X")
        always_replacements: dict[int, str] = {}
        _distribute_replacement("", [0], [frag], always_replacements)
        assert always_replacements[0] == ""

    @pytest.mark.unit
    def test_three_fragments_sequential_distribution(self):
        frag1 = _Fragment(raw=b"AB", font="/F1", decoded="AB")
        frag2 = _Fragment(raw=b"CD", font="/F1", decoded="CD")
        frag3 = _Fragment(raw=b"EF", font="/F1", decoded="EF")
        always_replacements: dict[int, str] = {}
        _distribute_replacement("112233", [0, 1, 2], [frag1, frag2, frag3], always_replacements)
        assert always_replacements[0] == "11"
        assert always_replacements[1] == "22"
        assert always_replacements[2] == "33"

    @pytest.mark.unit
    def test_fragment_indices_written_correctly(self):
        """Ensure global frag_indices (not 0-based) are the keys in always_replacements."""
        frag = _Fragment(raw=b"ABC", font="/F1", decoded="ABC")
        always_replacements: dict[int, str] = {}
        _distribute_replacement("XYZ", [7], [frag], always_replacements)
        assert 7 in always_replacements
        assert always_replacements[7] == "XYZ"


# ---------------------------------------------------------------------------
# Module 7b: empty / no-text pages
# ---------------------------------------------------------------------------


class TestBuildScramblePairsEmpty:
    """Degenerate inputs that should produce an empty pairs list."""

    @pytest.mark.unit
    def test_empty_content_stream_returns_empty_list(self, mock_random_source):
        page, pdf = _make_page(b"")
        always_cfg, never_cfg = _empty_configs()
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        result = _build_scramble_bytes_pairs(page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf)
        assert result == []
        del pdf

    @pytest.mark.unit
    def test_no_text_operators_returns_empty_list(self, mock_random_source):
        """Content with only non-text operators (e.g. 'q … Q') produces no pairs."""
        page, pdf = _make_page(b"q\n1 0 0 1 0 0 cm\nQ\n")
        always_cfg, never_cfg = _empty_configs()
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        result = _build_scramble_bytes_pairs(page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf)
        assert result == []
        del pdf

    @pytest.mark.unit
    def test_returns_list(self, mock_random_source):
        page, pdf = _make_page(_tj("Hello"))
        always_cfg, never_cfg = _empty_configs()
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        result = _build_scramble_bytes_pairs(page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf)
        assert isinstance(result, list)
        del pdf


# ---------------------------------------------------------------------------
# Module 7c: scramblable fragments
# ---------------------------------------------------------------------------


class TestBuildScramblePairsScramble:
    """Fragments that are not protected should produce scramble pairs."""

    @pytest.mark.unit
    def test_scramblable_text_produces_pair(self, mock_random_source):
        page, pdf = _make_page(_tj("Amazon"))
        always_cfg, never_cfg = _empty_configs()
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        result = _build_scramble_bytes_pairs(page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf)
        assert len(result) >= 1
        del pdf

    @pytest.mark.unit
    def test_pair_original_matches_fragment_bytes(self, mock_random_source):
        page, pdf = _make_page(_tj("Amazon"))
        always_cfg, never_cfg = _empty_configs()
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        result = _build_scramble_bytes_pairs(page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf)
        originals = [orig for orig, _ in result]
        assert b"Amazon" in originals
        del pdf

    @pytest.mark.unit
    def test_pair_replacement_differs_from_original(self, mock_random_source):
        page, pdf = _make_page(_tj("Amazon"))
        always_cfg, never_cfg = _empty_configs()
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        result = _build_scramble_bytes_pairs(page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf)
        for orig, repl in result:
            if orig == b"Amazon":
                assert repl != orig
        del pdf

    @pytest.mark.unit
    def test_pair_replacement_same_length(self, mock_random_source):
        """Latin-1 scramble produces same-length replacement (letter→letter)."""
        page, pdf = _make_page(_tj("Tesco"))
        always_cfg, never_cfg = _empty_configs()
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        result = _build_scramble_bytes_pairs(page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf)
        for orig, repl in result:
            if orig == b"Tesco":
                assert len(repl) == len(orig)
        del pdf

    @pytest.mark.unit
    def test_digits_only_text_not_scrambled(self, mock_random_source):
        """Pure digit text is protected by the built-in numeric pattern."""
        page, pdf = _make_page(_tj("12345"))
        always_cfg, never_cfg = _empty_configs()
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        result = _build_scramble_bytes_pairs(page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf)
        originals = [orig for orig, _ in result]
        assert b"12345" not in originals
        del pdf


# ---------------------------------------------------------------------------
# Module 7d: protected fragments
# ---------------------------------------------------------------------------


class TestBuildScramblePairsProtected:
    """Fragments that are protected must not appear as original in any pair."""

    @pytest.mark.unit
    def test_bold_font_fragment_not_in_pairs(self, mock_random_source):
        """Fragments rendered in a bold font are protected unconditionally."""
        page, pdf = _make_page(_tj("Headline"), bold=True)
        always_cfg, never_cfg = _empty_configs()
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        result = _build_scramble_bytes_pairs(page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf)
        originals = [orig for orig, _ in result]
        assert b"Headline" not in originals
        del pdf

    @pytest.mark.unit
    def test_never_cfg_phrase_not_in_pairs(self, mock_random_source):
        page, pdf = _make_page(_tj("Barclays"))
        always_cfg = _AlwaysAnonymiseConfig(replacements={})
        never_cfg = _NeverAnonymiseConfig(phrases=frozenset(["barclays"]))
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        result = _build_scramble_bytes_pairs(page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf)
        originals = [orig for orig, _ in result]
        assert b"Barclays" not in originals
        del pdf

    @pytest.mark.unit
    def test_date_text_not_in_pairs(self, mock_random_source):
        """Dates are built-in protected; they should not appear in pairs."""
        page, pdf = _make_page(_tj("01 Jan 25"))
        always_cfg, never_cfg = _empty_configs()
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        result = _build_scramble_bytes_pairs(page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf)
        originals = [orig for orig, _ in result]
        assert b"01 Jan 25" not in originals
        del pdf

    @pytest.mark.unit
    def test_sort_code_not_in_pairs(self, mock_random_source):
        """Sort codes are built-in protected numeric IDs."""
        page, pdf = _make_page(_tj("40-37-28"))
        always_cfg, never_cfg = _empty_configs()
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        result = _build_scramble_bytes_pairs(page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf)
        originals = [orig for orig, _ in result]
        assert b"40-37-28" not in originals
        del pdf

    @pytest.mark.unit
    def test_protected_and_scramble_on_same_page(self, mock_random_source):
        """Mixed page: date is protected, merchant is scrambled."""
        content = _tj("01 Jan 25") + _tj("Merchant")
        page, pdf = _make_page(content)
        always_cfg, never_cfg = _empty_configs()
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        result = _build_scramble_bytes_pairs(page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf)
        originals = [orig for orig, _ in result]
        assert b"01 Jan 25" not in originals
        assert b"Merchant" in originals
        del pdf


# ---------------------------------------------------------------------------
# Module 7e: always-anonymise fragments
# ---------------------------------------------------------------------------


class TestBuildScramblePairsAlways:
    """Fragments matching always_cfg should produce fixed-replacement pairs."""

    @pytest.mark.unit
    def test_always_cfg_single_fragment_produces_pair(self, mock_random_source):
        page, pdf = _make_page(_tj("JohnSmith"))
        always_cfg = _AlwaysAnonymiseConfig(replacements={"JohnSmith": "JaneDoeXX"})
        never_cfg = _NeverAnonymiseConfig(phrases=frozenset())
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        result = _build_scramble_bytes_pairs(page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf)
        originals = [orig for orig, _ in result]
        assert b"JohnSmith" in originals
        del pdf

    @pytest.mark.unit
    def test_always_cfg_replacement_bytes_correct(self, mock_random_source):
        page, pdf = _make_page(_tj("JohnSmith"))
        always_cfg = _AlwaysAnonymiseConfig(replacements={"JohnSmith": "JaneDoeXX"})
        never_cfg = _NeverAnonymiseConfig(phrases=frozenset())
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        result = _build_scramble_bytes_pairs(page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf)
        pair_map = {orig: repl for orig, repl in result}
        assert pair_map.get(b"JohnSmith") == b"JaneDoeXX"
        del pdf

    @pytest.mark.unit
    def test_always_cfg_same_replacement_skipped(self, mock_random_source):
        """If replacement encodes to the same bytes, the pair is dropped (no-op)."""
        page, pdf = _make_page(_tj("Lloyds"))
        always_cfg = _AlwaysAnonymiseConfig(replacements={"Lloyds": "Lloyds"})
        never_cfg = _NeverAnonymiseConfig(phrases=frozenset())
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        result = _build_scramble_bytes_pairs(page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf)
        pair_map = {orig: repl for orig, repl in result}
        # Either not present at all, or not mapped to identical bytes
        for orig, repl in pair_map.items():
            if orig == b"Lloyds":
                assert repl != orig
        del pdf


# ---------------------------------------------------------------------------
# Module 7f: numeric_id_map integration
# ---------------------------------------------------------------------------


class TestBuildScramblePairsNumericIdMap:
    """numeric_id_map entries should produce fixed-replacement pairs like always_cfg."""

    @pytest.mark.unit
    def test_numeric_id_map_entry_produces_pair(self, mock_random_source):
        page, pdf = _make_page(_tj("40-37-28"))
        always_cfg, never_cfg = _empty_configs()
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        numeric_id_map = {"40-37-28": "00-00-00"}
        result = _build_scramble_bytes_pairs(
            page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf,
            numeric_id_map=numeric_id_map,
        )
        pair_map = {orig: repl for orig, repl in result}
        assert b"40-37-28" in pair_map
        del pdf

    @pytest.mark.unit
    def test_numeric_id_map_replacement_bytes_correct(self, mock_random_source):
        page, pdf = _make_page(_tj("40-37-28"))
        always_cfg, never_cfg = _empty_configs()
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        numeric_id_map = {"40-37-28": "00-00-00"}
        result = _build_scramble_bytes_pairs(
            page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf,
            numeric_id_map=numeric_id_map,
        )
        pair_map = {orig: repl for orig, repl in result}
        assert pair_map.get(b"40-37-28") == b"00-00-00"
        del pdf

    @pytest.mark.unit
    def test_none_numeric_id_map_treated_as_empty(self, mock_random_source):
        """Passing numeric_id_map=None should not raise."""
        page, pdf = _make_page(_tj("Amazon"))
        always_cfg, never_cfg = _empty_configs()
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        result = _build_scramble_bytes_pairs(
            page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf,
            numeric_id_map=None,
        )
        assert isinstance(result, list)
        del pdf


# ---------------------------------------------------------------------------
# Module 7g: deduplication and ordering
# ---------------------------------------------------------------------------


class TestBuildScramblePairsDeduplication:
    """Duplicate raw bytes and longest-first ordering."""

    @pytest.mark.unit
    def test_duplicate_raw_bytes_appear_once(self, mock_random_source):
        """Two identical Tj operands → only one pair for that byte sequence."""
        content = _tj("Amazon") + _tj("Amazon")
        page, pdf = _make_page(content)
        always_cfg, never_cfg = _empty_configs()
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        result = _build_scramble_bytes_pairs(page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf)
        originals = [orig for orig, _ in result]
        assert originals.count(b"Amazon") == 1
        del pdf

    @pytest.mark.unit
    def test_pairs_sorted_longest_original_first(self, mock_random_source):
        """Pairs must be sorted by descending original byte-sequence length."""
        content = _tj("Hi") + _tj("Supermarket")
        page, pdf = _make_page(content)
        always_cfg, never_cfg = _empty_configs()
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        result = _build_scramble_bytes_pairs(page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf)
        lengths = [len(orig) for orig, _ in result]
        assert lengths == sorted(lengths, reverse=True)
        del pdf

    @pytest.mark.unit
    def test_pairs_each_element_is_two_bytes_objects(self, mock_random_source):
        page, pdf = _make_page(_tj("Barclays"))
        always_cfg, never_cfg = _empty_configs()
        scramble_map = _make_scramble_map()
        fe, fm, rm, bf = _page_maps(page)
        result = _build_scramble_bytes_pairs(page, scramble_map, always_cfg, never_cfg, fe, fm, rm, bf)
        for item in result:
            assert isinstance(item, tuple)
            assert len(item) == 2
            assert isinstance(item[0], bytes)
            assert isinstance(item[1], bytes)
        del pdf
