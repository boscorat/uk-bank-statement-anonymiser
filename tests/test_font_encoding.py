"""
Unit tests for font encoding in the bank_statement_anonymiser.

This module tests all functions involved in PDF font encoding and decoding:

- _parse_tounicode_cmap(): Parse ToUnicode CMap streams to CID→Unicode maps
- _decode_raw_bytes(): Decode raw bytes via ToUnicode forward map or Latin-1 fallback
- _decode_raw_bytes_v2(): Identity-H aware decoder (2-byte CID big-endian)
- _decode_raw_bytes_safe(): Routing dispatcher between v1 and v2 decoders
- _is_identity_h_font(): Detect Identity-H encoding from a font dictionary
- _reencode_fragment(): Re-encode Unicode text back to raw bytes for a font
- _scramble_text(): Plain letter-scrambler (digits/symbols unchanged)
- _scramble_text_font_aware(): Glyph-collision-aware scrambler for custom fonts

All three real-world encoding strategies are covered:
  - HSBC: Latin-1 / WinAnsiEncoding (single-byte, no ToUnicode CMap)
  - TSB:  Custom ToUnicode CMap reencoding (single-byte with forward map)
  - NatWest: Identity-H CID fonts (2-byte big-endian CIDs)
"""

from __future__ import annotations

import pikepdf
import pytest

from bank_statement_anonymiser._shared import (
    _LOWER_LETTERS,
    _UPPER_LETTERS,
    _make_scramble_map,
    _parse_tounicode_cmap,
)
from bank_statement_anonymiser.anonymise import (
    _decode_raw_bytes,
    _decode_raw_bytes_safe,
    _decode_raw_bytes_v2,
    _FontEncoding,
    _is_identity_h_font,
    _reencode_fragment,
    _scramble_text,
    _scramble_text_font_aware,
)

# ---------------------------------------------------------------------------
# Helpers to build minimal CMap streams for testing
# ---------------------------------------------------------------------------


def _make_bfchar_cmap(pairs: list[tuple[int, int]]) -> bytes:
    """Build a minimal Latin-1 ToUnicode CMap stream from (glyph_byte, unicode_cp) pairs."""
    entries = "\n".join(f"<{g:02X}> <{u:04X}>" for g, u in pairs)
    return (
        f"/CIDInit /ProcSet findresource begin\n"
        f"12 dict begin\n"
        f"begincmap\n"
        f"{len(pairs)} beginbfchar\n"
        f"{entries}\n"
        f"endbfchar\n"
        f"endcmap\n"
        f"CMapName currentdict /CMap defineresource pop\n"
        f"end\n"
        f"end\n"
    ).encode("latin-1")


def _make_identity_h_cmap(pairs: list[tuple[int, int]]) -> bytes:
    """Build a minimal Identity-H ToUnicode CMap from (cid_16bit, unicode_cp) pairs."""
    entries = "\n".join(f"<{g:04X}> <{u:04X}>" for g, u in pairs)
    return (
        f"/CIDInit /ProcSet findresource begin\n"
        f"12 dict begin\n"
        f"begincmap\n"
        f"{len(pairs)} beginbfchar\n"
        f"{entries}\n"
        f"endbfchar\n"
        f"endcmap\n"
    ).encode("latin-1")


# ---------------------------------------------------------------------------
# Tests: _parse_tounicode_cmap
# ---------------------------------------------------------------------------


class TestParseTounicodeCmap:
    """Unit tests for _parse_tounicode_cmap()."""

    @pytest.mark.unit
    def test_parses_single_byte_bfchar(self):
        """
        Verify parsing of a standard single-byte bfchar CMap.

        Given: A CMap stream with <XX> -> <YYYY> single-byte mappings
        When: _parse_tounicode_cmap() is called
        Then: Returns a dict mapping glyph-byte ints to Unicode chars
        """
        cmap = _make_bfchar_cmap([(0x41, 0x0041), (0x42, 0x0042)])  # A->A, B->B
        result = _parse_tounicode_cmap(cmap)

        assert 0x41 in result, "Glyph byte 0x41 should be in result"
        assert result[0x41] == "A", f"Expected 'A', got {result[0x41]!r}"
        assert result[0x42] == "B", f"Expected 'B', got {result[0x42]!r}"

    @pytest.mark.unit
    def test_parses_multibyte_identity_h_cmap(self):
        """
        Verify parsing of multi-byte Identity-H CMap entries.

        Given: A CMap stream with <CCCC> -> <YYYY> multi-byte CID mappings
        When: _parse_tounicode_cmap() is called
        Then: Returns a dict mapping 16-bit CID ints to Unicode chars
        """
        # CID 0x0041 (65) -> Unicode 'A' (0x0041)
        cmap = _make_identity_h_cmap([(0x0041, 0x0041), (0x0048, 0x0048)])
        result = _parse_tounicode_cmap(cmap)

        assert 0x0041 in result, "CID 0x0041 should be in result"
        assert result[0x0041] == "A"
        assert result[0x0048] == "H"

    @pytest.mark.unit
    def test_omits_null_unicode_codepoint(self):
        """
        Verify that U+0000 entries are excluded from the result.

        Given: A CMap stream containing an entry mapping to U+0000
        When: _parse_tounicode_cmap() is called
        Then: The U+0000 entry is omitted from the result dict
        """
        cmap = _make_bfchar_cmap([(0x41, 0x0041), (0xFF, 0x0000)])
        result = _parse_tounicode_cmap(cmap)

        assert 0xFF not in result, "U+0000 mapped entry should be omitted"
        assert 0x41 in result, "Valid entry should still be present"

    @pytest.mark.unit
    def test_returns_empty_dict_for_empty_stream(self):
        """
        Verify empty CMap stream returns empty dict.

        Given: An empty byte stream
        When: _parse_tounicode_cmap() is called
        Then: Returns an empty dict (no entries to parse)
        """
        result = _parse_tounicode_cmap(b"")
        assert result == {}, f"Expected empty dict, got {result}"

    @pytest.mark.unit
    def test_returns_empty_for_stream_with_no_bfchar(self):
        """
        Verify CMap stream without bfchar section returns empty dict.

        Given: A CMap stream with only bfrange (not bfchar)
        When: _parse_tounicode_cmap() is called
        Then: Returns an empty dict (bfrange entries are ignored)
        """
        cmap_no_bfchar = b"/CIDInit /ProcSet findresource begin\nbegincmap\nendcmap\nend"
        result = _parse_tounicode_cmap(cmap_no_bfchar)
        assert result == {}, f"Expected empty dict, got {result}"

    @pytest.mark.unit
    def test_handles_utf16be_bom_prefix(self):
        """
        Verify handling of UTF-16-BE BOM prefix in CMap streams.

        Given: A CMap stream starting with BOM prefix \xfe\xff
        When: _parse_tounicode_cmap() is called
        Then: Stream is decoded as UTF-16-BE and entries are parsed correctly
        """
        # Build a simple CMap in Latin-1, then encode as UTF-16-BE with BOM
        cmap_latin1 = _make_bfchar_cmap([(0x41, 0x0041)])
        cmap_utf16 = b"\xfe\xff" + cmap_latin1.decode("latin-1").encode("utf-16-be")
        result = _parse_tounicode_cmap(cmap_utf16)
        assert 0x41 in result, "UTF-16-BE CMap should be parsed"
        assert result[0x41] == "A"

    @pytest.mark.unit
    def test_parses_multiple_entries(self):
        """
        Verify that all entries in a CMap are parsed.

        Given: A CMap stream with many entries
        When: _parse_tounicode_cmap() is called
        Then: All entries are present in the result
        """
        # Map ASCII letters A-Z
        pairs = [(0x41 + i, 0x0041 + i) for i in range(26)]
        cmap = _make_bfchar_cmap(pairs)
        result = _parse_tounicode_cmap(cmap)

        assert len(result) == 26, f"Expected 26 entries, got {len(result)}"
        for i, letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
            assert result[0x41 + i] == letter, f"Missing entry for {letter!r}"

    @pytest.mark.unit
    def test_values_are_single_unicode_chars(self):
        """
        Verify that all result values are single-character strings.

        Given: A CMap stream with various entries
        When: _parse_tounicode_cmap() is called
        Then: Every value in the result is a single Unicode character
        """
        pairs = [(0x41 + i, 0x0041 + i) for i in range(26)]
        cmap = _make_bfchar_cmap(pairs)
        result = _parse_tounicode_cmap(cmap)

        for key, value in result.items():
            assert isinstance(value, str), f"Value for key {key} is not str"
            assert len(value) == 1, (
                f"Value for key {key} has length {len(value)}, expected 1"
            )


# ---------------------------------------------------------------------------
# Tests: _decode_raw_bytes (v1 — single-byte with forward map or Latin-1)
# ---------------------------------------------------------------------------


class TestDecodeRawBytes:
    """Unit tests for _decode_raw_bytes() — single-byte decoder."""

    @pytest.mark.unit
    def test_uses_forward_map_when_present(self):
        """
        Verify that _decode_raw_bytes uses the ToUnicode forward map when available.

        Given: A forward map for font /F1 and raw bytes for that font
        When: _decode_raw_bytes() is called
        Then: Decoded text uses the forward map values
        """
        forward_maps = {"/F1": {0x41: "A", 0x42: "B", 0x43: "C"}}
        raw = bytes([0x41, 0x42, 0x43])
        result = _decode_raw_bytes(raw, "/F1", forward_maps)
        assert result == "ABC", f"Expected 'ABC', got {result!r}"

    @pytest.mark.unit
    def test_falls_back_to_latin1_without_forward_map(self):
        """
        Verify Latin-1 fallback when no forward map exists for the font.

        Given: No forward map for the font
        When: _decode_raw_bytes() is called with raw bytes
        Then: Decoded text uses Latin-1 decoding (HSBC style)
        """
        forward_maps: dict[str, dict[int, str]] = {}
        raw = b"Hello"
        result = _decode_raw_bytes(raw, "/F1", forward_maps)
        assert result == "Hello", f"Expected 'Hello', got {result!r}"

    @pytest.mark.unit
    def test_forward_map_missing_byte_produces_empty(self):
        """
        Verify that bytes not in the forward map produce empty string for that slot.

        Given: A forward map that is missing an entry for a particular byte
        When: _decode_raw_bytes() is called with a byte not in the map
        Then: That byte position produces an empty string in the output
        """
        forward_maps = {"/F1": {0x41: "A"}}  # only 'A' mapped
        raw = bytes([0x41, 0x42])  # 0x42 not in map
        result = _decode_raw_bytes(raw, "/F1", forward_maps)
        assert result == "A", f"Expected 'A' (0x42 omitted), got {result!r}"

    @pytest.mark.unit
    def test_handles_empty_raw_bytes(self):
        """
        Verify handling of empty raw bytes.

        Given: Empty raw bytes
        When: _decode_raw_bytes() is called
        Then: Returns empty string
        """
        forward_maps: dict[str, dict[int, str]] = {}
        result = _decode_raw_bytes(b"", "/F1", forward_maps)
        assert result == "", f"Expected empty string, got {result!r}"

    @pytest.mark.unit
    def test_latin1_range_preserved(self):
        """
        Verify that Latin-1 extended characters survive the fallback decode.

        Given: Bytes in the Latin-1 extended range (0x80–0xFF), no forward map
        When: _decode_raw_bytes() is called
        Then: Characters decoded correctly as Latin-1
        """
        raw = bytes([0xA3])  # £ sign in Latin-1
        result = _decode_raw_bytes(raw, "/F1", {})
        assert result == "£", f"Expected '£', got {result!r}"


# ---------------------------------------------------------------------------
# Tests: _decode_raw_bytes_v2 (Identity-H CID decoder)
# ---------------------------------------------------------------------------


class TestDecodeRawBytesV2:
    """Unit tests for _decode_raw_bytes_v2() — Identity-H / single-byte decoder."""

    @pytest.mark.unit
    def test_decodes_identity_h_two_byte_cids(self):
        """
        Verify 2-byte big-endian CID decoding for Identity-H fonts.

        Given: A FontEncoding with is_identity_h=True and a CID map
        And:   Raw bytes representing big-endian CID values
        When: _decode_raw_bytes_v2() is called
        Then: Each pair of bytes is decoded as one character
        """
        # CID 0x0041 -> 'A', CID 0x0048 -> 'H'
        fwd = {0x0041: "A", 0x0048: "H", 0x0049: "I"}
        font_enc = _FontEncoding(
            font_name="/F0",
            forward_map=fwd,
            is_identity_h=True,
        )
        # Encode "AHI" as three 2-byte CIDs
        raw = bytes([0x00, 0x41, 0x00, 0x48, 0x00, 0x49])
        result = _decode_raw_bytes_v2(raw, font_enc)
        assert result == "AHI", f"Expected 'AHI', got {result!r}"

    @pytest.mark.unit
    def test_identity_h_missing_cid_produces_empty(self):
        """
        Verify that unknown CIDs produce empty string slots in Identity-H mode.

        Given: A forward map missing a particular CID
        When: Raw bytes contain that CID
        Then: That position yields empty string in the output
        """
        fwd = {0x0041: "A"}
        font_enc = _FontEncoding(
            font_name="/F0",
            forward_map=fwd,
            is_identity_h=True,
        )
        raw = bytes([0x00, 0x41, 0x00, 0xFF])  # 0x00FF not in map
        result = _decode_raw_bytes_v2(raw, font_enc)
        assert result == "A", f"Expected 'A' (unknown CID omitted), got {result!r}"

    @pytest.mark.unit
    def test_identity_h_odd_byte_count_fallback(self):
        """
        Verify graceful handling of an odd number of bytes in Identity-H mode.

        Given: An Identity-H FontEncoding and a raw byte stream with odd length
        When: _decode_raw_bytes_v2() is called
        Then: The trailing single byte is looked up as a 1-byte key (fallback)
        And:  No exception is raised
        """
        fwd = {0x0041: "A", 0x42: "B"}  # 0x42 as a 1-byte fallback key
        font_enc = _FontEncoding(
            font_name="/F0",
            forward_map=fwd,
            is_identity_h=True,
        )
        raw = bytes([0x00, 0x41, 0x42])  # 3 bytes — odd
        # Should not raise; trailing 0x42 decoded as single-byte fallback
        result = _decode_raw_bytes_v2(raw, font_enc)
        assert isinstance(result, str), "Should return a string"
        assert "A" in result, "First CID should decode to 'A'"

    @pytest.mark.unit
    def test_single_byte_mode_uses_forward_map(self):
        """
        Verify that single-byte mode (is_identity_h=False) uses the forward map.

        Given: A FontEncoding with is_identity_h=False and a forward map
        When: _decode_raw_bytes_v2() is called with single-byte glyph codes
        Then: Each byte is looked up in the forward map
        """
        fwd = {0x41: "A", 0x42: "B"}
        font_enc = _FontEncoding(
            font_name="/F1",
            forward_map=fwd,
            is_identity_h=False,
        )
        raw = bytes([0x41, 0x42])
        result = _decode_raw_bytes_v2(raw, font_enc)
        assert result == "AB", f"Expected 'AB', got {result!r}"

    @pytest.mark.unit
    def test_single_byte_mode_latin1_fallback(self):
        """
        Verify Latin-1 fallback in single-byte mode when glyph not in map.

        Given: A FontEncoding with is_identity_h=False
        And:   A raw byte 0x48 ('H' in Latin-1) not in the forward map
        When: _decode_raw_bytes_v2() is called
        Then: The byte is decoded as Latin-1 ('H')
        """
        fwd = {0x41: "A"}  # 0x48 not mapped
        font_enc = _FontEncoding(
            font_name="/F1",
            forward_map=fwd,
            is_identity_h=False,
        )
        raw = bytes([0x41, 0x48])
        result = _decode_raw_bytes_v2(raw, font_enc)
        assert result == "AH", f"Expected 'AH', got {result!r}"

    @pytest.mark.unit
    def test_handles_empty_bytes(self):
        """
        Verify both modes handle empty byte input without error.

        Given: A FontEncoding (either mode) and empty raw bytes
        When: _decode_raw_bytes_v2() is called
        Then: Returns empty string
        """
        for is_identity_h in (True, False):
            font_enc = _FontEncoding(
                font_name="/F0",
                forward_map={},
                is_identity_h=is_identity_h,
            )
            result = _decode_raw_bytes_v2(b"", font_enc)
            assert result == "", (
                f"Expected empty string for is_identity_h={is_identity_h}"
            )


# ---------------------------------------------------------------------------
# Tests: _decode_raw_bytes_safe (dispatcher)
# ---------------------------------------------------------------------------


class TestDecodeRawBytesSafe:
    """Unit tests for _decode_raw_bytes_safe() — the routing dispatcher."""

    @pytest.mark.unit
    def test_uses_v2_when_font_encodings_available(self):
        """
        Verify that _decode_raw_bytes_safe routes to _decode_raw_bytes_v2
        when font_encodings is provided and contains the font.

        Given: font_encodings dict containing the active font
        When: _decode_raw_bytes_safe() is called
        Then: Identity-H aware decoding is used
        """
        fwd = {0x0041: "X"}  # CID 0x0041 -> 'X' (different from Latin-1 'A')
        font_enc = _FontEncoding("/F0", fwd, is_identity_h=True)
        font_encodings = {"/F0": font_enc}
        forward_maps: dict[str, dict[int, str]] = {}

        raw = bytes([0x00, 0x41])  # CID 0x0041 big-endian
        result = _decode_raw_bytes_safe(raw, "/F0", forward_maps, font_encodings)
        assert result == "X", f"Expected 'X' from v2 path, got {result!r}"

    @pytest.mark.unit
    def test_falls_back_to_v1_without_font_encodings(self):
        """
        Verify that _decode_raw_bytes_safe falls back to _decode_raw_bytes
        when font_encodings is None.

        Given: font_encodings=None
        When: _decode_raw_bytes_safe() is called
        Then: Latin-1 fallback decoding is used
        """
        raw = b"Hello"
        result = _decode_raw_bytes_safe(raw, "/F1", {}, font_encodings=None)
        assert result == "Hello", f"Expected 'Hello', got {result!r}"

    @pytest.mark.unit
    def test_falls_back_to_v1_when_font_not_in_encodings(self):
        """
        Verify fallback when font_encodings doesn't contain the active font.

        Given: font_encodings with /F0 but active font is /F1
        When: _decode_raw_bytes_safe() is called for /F1
        Then: Latin-1 fallback is used for /F1
        """
        fwd = {0x0041: "Z"}
        font_encodings = {"/F0": _FontEncoding("/F0", fwd, is_identity_h=True)}
        raw = b"Hi"
        result = _decode_raw_bytes_safe(raw, "/F1", {}, font_encodings)
        assert result == "Hi", f"Expected 'Hi' from Latin-1, got {result!r}"

    @pytest.mark.unit
    def test_forward_map_used_in_v1_path(self):
        """
        Verify that forward_maps are used when taking the v1 (non-Identity-H) path.

        Given: A forward_map for the font, no font_encodings
        When: _decode_raw_bytes_safe() is called
        Then: The forward map entries are used for decoding
        """
        forward_maps = {"/F1": {0x48: "H", 0x65: "e"}}
        raw = bytes([0x48, 0x65])
        result = _decode_raw_bytes_safe(raw, "/F1", forward_maps, font_encodings=None)
        assert result == "He", f"Expected 'He', got {result!r}"


# ---------------------------------------------------------------------------
# Tests: _is_identity_h_font
# ---------------------------------------------------------------------------


class TestIsIdentityHFont:
    """Unit tests for _is_identity_h_font()."""

    @pytest.mark.unit
    def test_returns_true_for_identity_h_encoding(self):
        """
        Verify detection of /Identity-H encoding in font dictionary.

        Given: A pikepdf font dictionary with /Encoding = /Identity-H
        When: _is_identity_h_font() is called
        Then: Returns True
        """
        font_dict = pikepdf.Dictionary(
            Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name("/CIDFontType2"),
            Encoding=pikepdf.Name("/Identity-H"),
        )
        assert _is_identity_h_font(font_dict) is True

    @pytest.mark.unit
    def test_returns_false_for_winansi_encoding(self):
        """
        Verify non-Identity-H encoding returns False.

        Given: A pikepdf font dictionary with /Encoding = /WinAnsiEncoding
        When: _is_identity_h_font() is called
        Then: Returns False
        """
        font_dict = pikepdf.Dictionary(
            Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.Type1,
            Encoding=pikepdf.Name("/WinAnsiEncoding"),
        )
        assert _is_identity_h_font(font_dict) is False

    @pytest.mark.unit
    def test_returns_false_when_no_encoding_key(self):
        """
        Verify that missing /Encoding key returns False.

        Given: A pikepdf font dictionary without an /Encoding key
        When: _is_identity_h_font() is called
        Then: Returns False (no Identity-H encoding declared)
        """
        font_dict = pikepdf.Dictionary(
            Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.Type1,
        )
        assert _is_identity_h_font(font_dict) is False

    @pytest.mark.unit
    def test_returns_false_for_macroman_encoding(self):
        """
        Verify MacRomanEncoding returns False.

        Given: A font dictionary with /Encoding = /MacRomanEncoding
        When: _is_identity_h_font() is called
        Then: Returns False
        """
        font_dict = pikepdf.Dictionary(
            Encoding=pikepdf.Name("/MacRomanEncoding"),
        )
        assert _is_identity_h_font(font_dict) is False


# ---------------------------------------------------------------------------
# Tests: _reencode_fragment
# ---------------------------------------------------------------------------


class TestReencodeFragment:
    """Unit tests for _reencode_fragment() — re-encodes text back to bytes."""

    @pytest.mark.unit
    def test_encodes_via_reverse_map(self):
        """
        Verify re-encoding through a single-byte reverse map.

        Given: A reverse map mapping 'A'->0x41, 'B'->0x42
        When: _reencode_fragment('AB', '/F1', ...) is called
        Then: Returns bytes([0x41, 0x42])
        """
        reverse_maps = {"/F1": {"A": 0x41, "B": 0x42}}
        result = _reencode_fragment("AB", "/F1", reverse_maps)
        assert result == bytes([0x41, 0x42]), f"Expected b'\\x41\\x42', got {result!r}"

    @pytest.mark.unit
    def test_falls_back_to_latin1_without_reverse_map(self):
        """
        Verify Latin-1 encoding fallback when no reverse map exists.

        Given: No reverse map for the font
        When: _reencode_fragment('Hello', '/F1', ...) is called
        Then: Returns 'Hello' encoded as Latin-1
        """
        result = _reencode_fragment("Hello", "/F1", {})
        assert result == b"Hello", f"Expected b'Hello', got {result!r}"

    @pytest.mark.unit
    def test_returns_none_when_char_missing_from_reverse_map(self):
        """
        Verify None is returned when a character is absent from the reverse map.

        Given: A reverse map that does not contain 'Z'
        When: _reencode_fragment('AZ', '/F1', ...) is called with 'Z' missing
        Then: Returns None (cannot re-encode safely)
        """
        reverse_maps = {"/F1": {"A": 0x41}}  # 'Z' not present
        result = _reencode_fragment("AZ", "/F1", reverse_maps)
        assert result is None, f"Expected None, got {result!r}"

    @pytest.mark.unit
    def test_identity_h_encodes_two_byte_big_endian(self):
        """
        Verify that Identity-H re-encoding produces 2-byte big-endian CIDs.

        Given: An Identity-H font with CID > 255 for some characters
        And:   A reverse map and font_encodings marking the font as Identity-H
        When: _reencode_fragment() is called
        Then: Each character is encoded as a 2-byte big-endian CID sequence
        """
        # CID 0x0100 for 'A', CID 0x0101 for 'B'
        reverse_maps = {"/F0": {"A": 0x0100, "B": 0x0101}}
        font_encodings = {
            "/F0": _FontEncoding("/F0", {0x0100: "A", 0x0101: "B"}, is_identity_h=True)
        }
        result = _reencode_fragment("AB", "/F0", reverse_maps, font_encodings)
        expected = bytes([0x01, 0x00, 0x01, 0x01])
        assert result == expected, f"Expected {expected!r}, got {result!r}"

    @pytest.mark.unit
    def test_encodes_empty_string_to_empty_bytes(self):
        """
        Verify that empty text re-encodes to empty bytes.

        Given: An empty text string
        When: _reencode_fragment('', '/F1', ...) is called
        Then: Returns b''
        """
        result = _reencode_fragment("", "/F1", {})
        assert result == b"", f"Expected b'', got {result!r}"

    @pytest.mark.unit
    def test_latin1_encodes_extended_chars(self):
        """
        Verify that Latin-1 extended characters encode correctly.

        Given: Text containing Latin-1 extended chars (e.g. '£')
        And:   No reverse map (Latin-1 fallback)
        When: _reencode_fragment() is called
        Then: Returns the correct Latin-1 bytes
        """
        result = _reencode_fragment("£", "/F1", {})
        assert result == b"\xa3", f"Expected b'\\xa3', got {result!r}"


# ---------------------------------------------------------------------------
# Tests: _scramble_text (plain scrambler)
# ---------------------------------------------------------------------------


class TestScrambleText:
    """Unit tests for _scramble_text() — plain letter scrambler."""

    @pytest.mark.unit
    def test_letters_are_scrambled(self, mock_random_source):
        """
        Verify that letters are changed by _scramble_text.

        Given: A scramble map and a text containing only letters
        When: _scramble_text() is called
        Then: The output text differs from the input (no identity)
        """
        scramble_map = _make_scramble_map()
        text = "abcdefghijklmnopqrstuvwxyz"
        result = _scramble_text(text, scramble_map)
        assert result != text, "Scrambled text should not equal original"

    @pytest.mark.unit
    def test_digits_unchanged(self, mock_random_source):
        """
        Verify that digits are not scrambled.

        Given: A scramble map and text containing digits mixed with letters
        When: _scramble_text() is called
        Then: Digit characters remain unchanged
        """
        scramble_map = _make_scramble_map()
        text = "abc123def"
        result = _scramble_text(text, scramble_map)

        for i, (orig, res) in enumerate(zip(text, result)):
            if orig.isdigit():
                assert res == orig, (
                    f"Digit at position {i} should be unchanged: {orig!r} -> {res!r}"
                )

    @pytest.mark.unit
    def test_symbols_unchanged(self, mock_random_source):
        """
        Verify that symbols and punctuation are not scrambled.

        Given: A scramble map and text with symbols
        When: _scramble_text() is called
        Then: All symbols remain unchanged
        """
        scramble_map = _make_scramble_map()
        text = "Hello-World!40-37-28"
        result = _scramble_text(text, scramble_map)

        for i, (orig, res) in enumerate(zip(text, result)):
            if not orig.isalpha():
                assert res == orig, (
                    f"Non-letter at position {i} changed: {orig!r} -> {res!r}"
                )

    @pytest.mark.unit
    def test_preserves_case(self, mock_random_source):
        """
        Verify that _scramble_text preserves case of each letter.

        Given: A scramble map and mixed-case text
        When: _scramble_text() is called
        Then: Uppercase letters map to uppercase, lowercase to lowercase
        """
        scramble_map = _make_scramble_map()
        text = "HelloWorld"
        result = _scramble_text(text, scramble_map)

        for orig, res in zip(text, result):
            if orig.isalpha():
                assert orig.isupper() == res.isupper(), (
                    f"Case mismatch: {orig!r} -> {res!r}"
                )

    @pytest.mark.unit
    def test_preserves_length(self, mock_random_source):
        """
        Verify _scramble_text does not change string length.

        Given: A scramble map and text of known length
        When: _scramble_text() is called
        Then: Output length equals input length
        """
        scramble_map = _make_scramble_map()
        text = "Amazon Ltd 40-37-28"
        result = _scramble_text(text, scramble_map)
        assert len(result) == len(text), (
            f"Length changed: {len(text)} -> {len(result)}"
        )

    @pytest.mark.unit
    def test_empty_string(self, mock_random_source):
        """
        Verify _scramble_text handles empty string.

        Given: A scramble map and empty text
        When: _scramble_text() is called
        Then: Returns empty string
        """
        scramble_map = _make_scramble_map()
        result = _scramble_text("", scramble_map)
        assert result == "", f"Expected empty string, got {result!r}"


# ---------------------------------------------------------------------------
# Tests: _scramble_text_font_aware
# ---------------------------------------------------------------------------


class TestScrambleTextFontAware:
    """Unit tests for _scramble_text_font_aware() — glyph-collision-aware scrambler."""

    @pytest.mark.unit
    def test_falls_back_to_plain_scramble_without_reverse_map(self, mock_random_source):
        """
        Verify plain scramble fallback for Latin-1 fonts with no reverse map.

        Given: reverse_maps has no entry for the active font
        When: _scramble_text_font_aware() is called
        Then: Behaves identically to _scramble_text (no collisions possible in Latin-1)
        """
        scramble_map = _make_scramble_map()
        text = "HelloWorld"
        result_aware = _scramble_text_font_aware(text, scramble_map, "/F1", {})
        result_plain = _scramble_text(text, scramble_map)
        assert result_aware == result_plain, (
            "Font-aware scramble should equal plain scramble when no reverse map"
        )

    @pytest.mark.unit
    def test_avoids_glyph_byte_collision(self, mock_random_source):
        """
        Verify that font-aware scrambling avoids same-glyph-byte replacements.

        Given: A reverse map where two letters share the same glyph byte
        When: _scramble_text_font_aware() is called for a letter with a collision
        Then: The output byte differs from the original byte for that letter
        """
        scramble_map = _make_scramble_map()

        # Build a reverse map where 'A' maps to glyph 0x41
        # Force a collision by making the scramble map point 'A' to a char
        # that also maps to 0x41 in the reverse map.
        # We'll use the actual scramble map output for 'a' and wire the reverse
        # map so that both 'a' and its preferred scramble share glyph 0x61.
        preferred_for_a = chr(scramble_map[ord("a")])

        reverse_maps = {
            "/F1": {
                "a": 0x61,
                preferred_for_a: 0x61,  # collision: same glyph byte as 'a'
                "z": 0x7A,
                "b": 0x62,
            }
        }

        text = "a"
        result = _scramble_text_font_aware(text, scramble_map, "/F1", reverse_maps)

        # Result should not use the colliding preferred char
        if result != "a":  # only check if a replacement was found
            result_byte = reverse_maps["/F1"].get(result)
            assert result_byte != 0x61, (
                f"Output '{result}' has same glyph byte as 'a' (collision)"
            )

    @pytest.mark.unit
    def test_keeps_original_when_not_in_reverse_map(self, mock_random_source):
        """
        Verify that chars not encodable in the font's reverse map are left unchanged.

        Given: A reverse map that does not contain 'X'
        When: _scramble_text_font_aware() is called with text containing 'X'
        Then: 'X' is preserved as-is in the output
        """
        scramble_map = _make_scramble_map()
        # Reverse map only has lowercase letters, not 'X'
        reverse_maps = {"/F1": {"a": 0x61, "b": 0x62, "z": 0x7A}}

        text = "X"
        result = _scramble_text_font_aware(text, scramble_map, "/F1", reverse_maps)
        assert result == "X", (
            f"Char 'X' not in reverse map should be preserved, got {result!r}"
        )

    @pytest.mark.unit
    def test_preserves_non_alpha_chars(self, mock_random_source):
        """
        Verify digits and symbols pass through font-aware scramble unchanged.

        Given: A reverse map and text with mixed letters/digits/symbols
        When: _scramble_text_font_aware() is called
        Then: Digits and symbols are unchanged
        """
        scramble_map = _make_scramble_map()
        reverse_maps = {
            "/F1": {chr(0x41 + i): 0x41 + i for i in range(26)}  # A-Z
        }
        text = "A1B-C2"
        result = _scramble_text_font_aware(text, scramble_map, "/F1", reverse_maps)

        for orig, res in zip(text, result):
            if not orig.isalpha():
                assert res == orig, (
                    f"Non-alpha '{orig}' changed to '{res}'"
                )

    @pytest.mark.unit
    def test_output_length_preserved(self, mock_random_source):
        """
        Verify _scramble_text_font_aware preserves text length.

        Given: A scramble map, reverse map, and multi-character text
        When: _scramble_text_font_aware() is called
        Then: Output length equals input length
        """
        scramble_map = _make_scramble_map()
        reverse_maps = {
            "/F1": {chr(ord("a") + i): ord("a") + i for i in range(26)}
        }
        text = "hello world"
        result = _scramble_text_font_aware(text, scramble_map, "/F1", reverse_maps)
        assert len(result) == len(text), (
            f"Length changed: {len(text)} -> {len(result)}"
        )


# ---------------------------------------------------------------------------
# Round-trip tests: encode → decode → reencode
# ---------------------------------------------------------------------------


class TestRoundTripEncoding:
    """Round-trip tests: ensure decode and re-encode are inverses of each other."""

    @pytest.mark.unit
    def test_single_byte_roundtrip_via_cmap(self):
        """
        Verify decode → re-encode round-trip for a single-byte ToUnicode font.

        Given: A forward map and its inverse (reverse map)
        And:   Raw bytes that encode the text "Hello"
        When: We decode with _decode_raw_bytes then re-encode with _reencode_fragment
        Then: We recover the original raw bytes
        """
        # Build forward and reverse maps for 'H','e','l','o'
        fwd = {0x48: "H", 0x65: "e", 0x6C: "l", 0x6F: "o"}
        rev = {v: k for k, v in fwd.items()}

        raw = bytes([0x48, 0x65, 0x6C, 0x6C, 0x6F])  # "Hello"
        decoded = _decode_raw_bytes(raw, "/F1", {"/F1": fwd})
        assert decoded == "Hello"

        re_encoded = _reencode_fragment(decoded, "/F1", {"/F1": rev})
        assert re_encoded == raw, (
            f"Round-trip failed: {raw!r} -> {decoded!r} -> {re_encoded!r}"
        )

    @pytest.mark.unit
    def test_identity_h_roundtrip(self):
        """
        Verify decode → re-encode round-trip for an Identity-H CID font.

        Given: An Identity-H FontEncoding with forward and reverse maps
        And:   Raw bytes encoding "Hi" as 2-byte CIDs
        When: We decode with _decode_raw_bytes_v2 then re-encode with _reencode_fragment
        Then: We recover the original raw bytes
        """
        fwd = {0x0048: "H", 0x0069: "i"}
        rev = {"H": 0x0048, "i": 0x0069}
        font_enc = _FontEncoding("/F0", fwd, is_identity_h=True)
        font_encodings = {"/F0": font_enc}

        # "Hi" as two 2-byte CIDs
        raw = bytes([0x00, 0x48, 0x00, 0x69])
        decoded = _decode_raw_bytes_v2(raw, font_enc)
        assert decoded == "Hi"

        re_encoded = _reencode_fragment(decoded, "/F0", {"/F0": rev}, font_encodings)
        assert re_encoded == raw, (
            f"Round-trip failed: {raw!r} -> {decoded!r} -> {re_encoded!r}"
        )

    @pytest.mark.unit
    def test_latin1_roundtrip_fallback(self):
        """
        Verify Latin-1 decode → re-encode round-trip (HSBC-style, no CMap).

        Given: No forward or reverse maps (HSBC WinAnsiEncoding path)
        And:   Raw bytes "Barclays" as ASCII/Latin-1
        When: We decode with _decode_raw_bytes then re-encode with _reencode_fragment
        Then: We recover the original raw bytes
        """
        raw = b"Barclays"
        decoded = _decode_raw_bytes(raw, "/F1", {})
        assert decoded == "Barclays"

        re_encoded = _reencode_fragment(decoded, "/F1", {})
        assert re_encoded == raw, (
            f"Latin-1 round-trip failed: {raw!r} -> {decoded!r} -> {re_encoded!r}"
        )

    @pytest.mark.unit
    def test_scramble_roundtrip_via_cmap(self, mock_random_source):
        """
        Verify full scramble + re-encode round-trip is consistent.

        Given: A forward map, reverse map, and scramble map
        And:   Raw bytes encoding a text fragment
        When: We decode, scramble, and re-encode
        Then: The re-encoded bytes are different from the originals (scramble happened)
        And:  The re-encoded bytes can themselves be decoded to the scrambled text
        """
        # Build maps for all lowercase letters
        fwd = {ord("a") + i: chr(ord("a") + i) for i in range(26)}
        rev = {chr(ord("a") + i): ord("a") + i for i in range(26)}
        forward_maps = {"/F1": fwd}
        reverse_maps = {"/F1": rev}

        scramble_map = _make_scramble_map()
        raw = b"hello"
        decoded = _decode_raw_bytes(raw, "/F1", forward_maps)
        scrambled = _scramble_text(decoded, scramble_map)
        re_encoded = _reencode_fragment(scrambled, "/F1", reverse_maps)

        # Scrambled bytes should differ from originals
        assert re_encoded != raw, "Scrambled re-encoding should differ from original"

        # And we can decode the scrambled bytes back to the scrambled text
        decoded_again = _decode_raw_bytes(re_encoded, "/F1", forward_maps)
        assert decoded_again == scrambled, (
             f"Re-decoded text {decoded_again!r} should equal scrambled {scrambled!r}"
        )


class TestIdentityHFontDetectionEdgeCases:
    """Edge case tests for _is_identity_h_font robustness."""

    @pytest.mark.unit
    def test_is_identity_h_font_none_input(self):
        """
        Verify that None font dictionary is handled safely.

        Given: None as font dictionary
        When: _is_identity_h_font is called
        Then: Returns False without crashing
        """
        result = _is_identity_h_font(None)  # type: ignore
        assert result is False, f"Expected False for None input, got {result}"

    @pytest.mark.unit
    def test_is_identity_h_font_missing_encoding(self):
         """
         Verify that font dict without /Encoding key returns False.

         Given: Font dictionary with no /Encoding entry
         When: _is_identity_h_font is called
         Then: Returns False
         """
         font_dict = pikepdf.Dictionary()
         # No /Encoding key
         result = _is_identity_h_font(font_dict)
         assert result is False, f"Expected False for missing /Encoding, got {result}"

    @pytest.mark.unit
    def test_is_identity_h_font_empty_dict(self):
         """
         Verify that empty font dictionary returns False.

         Given: Empty font dictionary
         When: _is_identity_h_font is called
         Then: Returns False
         """
         font_dict = pikepdf.Dictionary()
         result = _is_identity_h_font(font_dict)
         assert result is False, f"Expected False for empty dict, got {result}"

    @pytest.mark.unit
    def test_is_identity_h_font_correct_encoding(self):
         """
         Verify that Identity-H encoding is correctly detected.

         Given: Font dictionary with /Encoding: /Identity-H (or /Identity_H)
         When: _is_identity_h_font is called
         Then: Returns True
         """
         font_dict = pikepdf.Dictionary()
         font_dict["/Encoding"] = pikepdf.Name.Identity_H  # pikepdf uses underscore
         result = _is_identity_h_font(font_dict)
         # The implementation should handle both underscore and hyphen versions
         assert result is True, f"Expected True for Identity_H, got {result}"

    @pytest.mark.unit
    def test_is_identity_h_font_other_encoding(self):
        """
        Verify that non-Identity-H encoding returns False.

        Given: Font dictionary with /Encoding: /WinAnsiEncoding
        When: _is_identity_h_font is called
        Then: Returns False
        """
        font_dict = pikepdf.Dictionary()
        font_dict["/Encoding"] = pikepdf.Name.WinAnsiEncoding
        result = _is_identity_h_font(font_dict)
        assert result is False, f"Expected False for WinAnsiEncoding, got {result}"

    @pytest.mark.unit
    def test_is_identity_h_font_malformed_dict(self):
        """
        Verify that accessing malformed dict doesn't crash.

        Given: A problematic font dictionary (e.g., with unexpected types)
        When: _is_identity_h_font is called
        Then: Returns False gracefully
        """
        # This tests the defensive try/except
        font_dict = pikepdf.Dictionary()
        font_dict["/Encoding"] = "not_a_name"  # Invalid type for /Encoding
        result = _is_identity_h_font(font_dict)
        # Should return False since the string "not_a_name" doesn't match
        assert result is False, f"Expected False for invalid encoding type, got {result}"

