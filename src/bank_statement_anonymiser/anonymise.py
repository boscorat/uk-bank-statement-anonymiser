"""
anonymise — exclusion-based full-scramble PDF anonymisation utility.

Unlike a traditional inclusion-based approach (where you specify what to redact),
this module starts from a **completely scrambled PDF** — every *letter* on
every page is replaced with a different random letter of the same case —
and then uses the config files to specify what to force-replace and what to
leave unchanged.

Architecture
------------
All PDF text extraction is performed directly via pikepdf's content-stream
parser (``pikepdf.parse_content_stream``), operating on the raw ``Tj``/``TJ``
operator byte-string operands.  This avoids the model mismatch that occurs
when using pdfplumber's ``extract_words()``, which merges multiple ``Tj``
operators into single visual-word tokens — causing scramble pairs built at
the word level to silently fail to match during content-stream rewriting.

For each ``Tj``/``TJ`` fragment:

* If the active font has a ``/ToUnicode`` CMap, the raw bytes are decoded
  via that map (handles custom-encoded fonts, e.g. TSB).
* Otherwise the raw bytes are decoded as Latin-1 (handles WinAnsiEncoding
  fonts, e.g. HSBC).

Scrambled replacements are re-encoded using the same encoding path (reverse
CMap or Latin-1), so the output bytes are always valid for the font.

Per-page processing
-------------------
Phase 1 — Line-aware scan pass (read-only):
    Walk all operators in the content stream.  The line accumulator resets at
    every ``Td``, ``TD``, ``T*``, ``Tm``, or ``ET`` operator.  Within each
    line a sliding window checks each start position, extending rightward by
    joining decoded fragment texts, testing against:

    a. ``always_anonymise`` targets (system + user merged; user wins on clash)
       — mark with fixed replacement value.
    b. ``never_anonymise`` phrases (system + user merged, union)
       — mark as protected.
    c. Built-in patterns (dates, amounts, sort codes, payment codes)
       — mark as protected.

    First match at each start position wins; the start pointer advances past
    the matched span.

Phase 2 — Build bytes pairs:
    For each fragment:
    * ``always_anonymise`` match → distribute replacement chars across the
      original fragment slots (fill to original slot length; last slot absorbs
      overflow/underflow).  Build ``(original_bytes, replacement_bytes)`` pairs.
    * ``protected`` (never_anonymise or built-in pattern) → skip.
    * Scramblable → ``(original_bytes, scrambled_bytes)`` pair.

Phase 3 — Rewrite content stream (unchanged):
    Dict lookup of original_bytes → replacement_bytes.

Config files
------------
Four TOML files control behaviour.  All are bundled as package resources.
System files are committed to source control; user files are not.

``always_anonymise_system.toml`` / ``always_anonymise.toml``
    Flat ``"original" = "replacement"`` key/value pairs.
    User file wins on key clash.

``never_anonymise_system.toml`` / ``never_anonymise.toml``
    ``exclude = [...]`` list of words/phrases to preserve unchanged.
    Both lists are merged (union).

Public API
----------
    anonymise_pdf(input_path, output_path=None,
                  always_anonymise_path=None, never_anonymise_path=None) -> Path

Example
-------
    from pathlib import Path
    from bank_statement_anonymiser import anonymise_pdf

    out = anonymise_pdf(
        Path("tsb_statement.pdf"),
        always_anonymise_path=Path("my_always_anonymise.toml"),
        never_anonymise_path=Path("my_never_anonymise.toml"),
    )
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import NamedTuple

import pikepdf

from bank_statement_anonymiser._shared import (
    _ANONYMISED_PREFIX,
    _COMPOUND_TYPE_DESC_RE,
    _DATE_COMPACT_RE,
    _DATE_DAY_MONTH_RE,
    _DATE_RANGE_RE,
    _DATE_RE,
    _LOWER_LETTERS,
    _MONTH_COMPACT_RE,
    _MONTH_NAME_RE,
    _NUMERIC_ID_PATTERNS,
    _NUMERIC_RE,
    _PROTECTED_CHARRUN_PHRASES,
    _UPPER_LETTERS,
    _URL_RE,
    _decode_pdf_operand,
    _detect_numeric_ids,
    _make_scramble_map,
    _parse_tounicode_cmap,
    _rewrite_page_content_stream,
    _strip_numeric_separators,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DIGITS: frozenset[str] = frozenset("0123456789")

# Operators that always delimit a new visual line in a PDF content stream.
# Td/TD/T* are relative moves — they always advance to a new line.
# Tm (set text matrix) is handled separately: it only breaks the line when
# the y-coordinate changes, allowing same-y Tm repositioning (e.g. TSB wraps
# each word in its own BT/Tm/Tj/ET block at the same y) to accumulate across
# fragments for multi-word phrase matching.
_LINE_BREAK_OPS: frozenset[str] = frozenset({"Td", "TD", "T*"})

# Threshold (in PDF user units, roughly points) below which a Tm y-coordinate
# change is treated as the same visual line (e.g. baseline adjustment).
_TM_Y_THRESHOLD: float = 2.0


# ---------------------------------------------------------------------------
# Bundled resource helpers
# ---------------------------------------------------------------------------


def _bundled_path(filename: str) -> Path:
    """Return the filesystem path to a bundled package resource file."""
    with resources.as_file(resources.files("bank_statement_anonymiser").joinpath(filename)) as p:
        return Path(p)


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _AlwaysAnonymiseConfig:
    """Merged always-anonymise replacement rules (system + user)."""

    replacements: dict[str, str]  # original -> replacement; user wins on clash


@dataclass(frozen=True, slots=True)
class _NeverAnonymiseConfig:
    """Merged never-anonymise protected phrases (system + user, union)."""

    phrases: frozenset[str]  # normalised: lowercase, no whitespace


# ---------------------------------------------------------------------------
# Normalisation helper
# ---------------------------------------------------------------------------


def _normalise_phrase(text: str) -> str:
    """Lowercase, strip trailing colon, and strip all whitespace.

    Stripping the trailing colon means config entries like ``"Account number"``
    automatically match PDF fragments rendered as ``"Account number:"`` without
    needing duplicate entries in the config files.
    """
    t = text.strip().rstrip(":")
    return re.sub(r"\s+", "", t).lower()


# ---------------------------------------------------------------------------
# Config loaders
# ---------------------------------------------------------------------------


def _load_always_anonymise(
    system_path: Path,
    user_path: Path | None,
) -> _AlwaysAnonymiseConfig:
    """Load and merge always-anonymise replacement rules.

    The system file is always loaded.  The user file (if provided and exists)
    is merged on top — user entries win on key clash.
    """

    def _read_toml(path: Path) -> dict[str, str]:
        if not path.exists():
            return {}
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        # Top-level keys only — flat "original" = "replacement" format.
        return {k: v for k, v in data.items() if isinstance(v, str)}

    system_rules = _read_toml(system_path)
    user_rules = _read_toml(user_path) if user_path is not None else {}

    # Merge: system first, user overwrites on clash.
    merged = {**system_rules, **user_rules}
    return _AlwaysAnonymiseConfig(replacements=merged)


def _load_never_anonymise(
    system_path: Path,
    user_path: Path | None,
) -> _NeverAnonymiseConfig:
    """Load and merge never-anonymise protected phrases.

    Both system and user ``exclude`` lists are merged (union).
    """

    def _read_exclude(path: Path) -> list[str]:
        if not path.exists():
            return []
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        return data.get("exclude", [])

    system_phrases = _read_exclude(system_path)
    user_phrases = _read_exclude(user_path) if user_path is not None else []

    combined = frozenset(_normalise_phrase(p) for p in system_phrases + user_phrases if p.strip())
    return _NeverAnonymiseConfig(phrases=combined)


# ---------------------------------------------------------------------------
# Font encoding metadata
# ---------------------------------------------------------------------------


class _FontEncoding(NamedTuple):
    """Encoding metadata for a single PDF font."""
    font_name: str
    """Font resource name (e.g., '/F0')."""
    forward_map: dict[int, str]
    """CID/glyph_byte -> Unicode character mapping from ToUnicode CMap."""
    is_identity_h: bool
    """True if font uses Identity-H encoding (CID-keyed, multi-byte). 
    False for single-byte encodings like WinAnsiEncoding."""


# ---------------------------------------------------------------------------
# Decoding helper
# ---------------------------------------------------------------------------


def _decode_raw_bytes(
    raw: bytes,
    font: str,
    forward_maps: dict[str, dict[int, str]],
) -> str:
    """Decode raw PDF content-stream bytes using font's ToUnicode map or fallback encodings.

    Args:
        raw: The raw bytes from a Tj/TJ operand in the content stream.
        font: The active font name at the time this operand was encountered.
        forward_maps: Per-font ToUnicode forward maps (glyph_byte -> unicode),
            as returned by :func:`_build_font_maps`.

    Returns:
        Decoded unicode text. If a ToUnicode map exists for the font, uses that.
        Otherwise tries Latin-1 (common for HSBC), falling back to UTF-8 with
        replacement characters if Latin-1 fails.
    """
    fwd = forward_maps.get(font)
    if fwd is not None:
        return "".join(fwd.get(b, "") for b in raw)
    try:
        return raw.decode("latin-1")
    except Exception:
        return raw.decode("utf-8", errors="replace")


def _decode_raw_bytes_v2(
    raw: bytes,
    font_encoding: "_FontEncoding",
) -> str:
    """Decode raw PDF content-stream bytes using font encoding metadata.

    For Identity-H fonts (is_identity_h=True): treats raw bytes as 2-byte CID
    values in big-endian order. Looks up each CID in the forward map.

    For single-byte fonts (is_identity_h=False): treats each byte as a glyph
    code. Looks up in the forward map. Falls back to Latin-1 or UTF-8 if the
    glyph is not in the map.

    Args:
        raw: The raw bytes from a Tj/TJ operand in the content stream.
        font_encoding: Font encoding metadata with forward map and encoding type.

    Returns:
        Decoded unicode text.
    """
    fwd = font_encoding.forward_map
    
    if font_encoding.is_identity_h:
        # Identity-H: each 2-byte sequence is a CID (big-endian)
        result: list[str] = []
        i = 0
        while i < len(raw):
            if i + 1 < len(raw):
                # Combine two bytes into a 16-bit CID (big-endian)
                cid = (raw[i] << 8) | raw[i + 1]
                result.append(fwd.get(cid, ""))
                i += 2
            else:
                # Odd byte at end — treat as single byte (fallback)
                result.append(fwd.get(raw[i], ""))
                i += 1
        return "".join(result)
    else:
        # Single-byte font: each byte is a glyph code
        chars: list[str] = []
        for b in raw:
            if b in fwd:
                chars.append(fwd[b])
            else:
                # Fallback: try Latin-1 or UTF-8
                try:
                    chars.append(bytes([b]).decode("latin-1"))
                except Exception:
                    chars.append(bytes([b]).decode("utf-8", errors="replace"))
        return "".join(chars)


def _is_identity_h_font(f: "pikepdf.Dictionary") -> bool:
    """Detect if a PDF font uses Identity-H encoding (CID-based, multi-byte).

    A font is considered Identity-H if its /Encoding entry is the name
    '/Identity-H' (case-insensitive check on the string representation).

    Args:
        f: The font dictionary from /Resources /Font.

    Returns:
        True if the font uses Identity-H encoding, False otherwise.
    """
    encoding = f.get("/Encoding")
    if encoding is None:
        return False
    encoding_str = str(encoding)
    return encoding_str == "/Identity-H" or encoding_str == "Identity-H"



def _lookup_numeric_id(
    accumulated_spaced: str,
    accumulated: str,
    numeric_id_map: dict[str, str],
) -> str | None:
    """Return replacement text if a numeric ID match is found, else None.

    Attempts to match the numeric ID against the map in the following order:
    1. accumulated_spaced (space-joined fragments)
    2. accumulated_spaced.strip()
    3. accumulated (concatenated fragments)
    4. accumulated.strip()

    This order ensures that compound tokens like "403728 31243535" are matched
    before single tokens like "40-37-28", and that leading/trailing whitespace
    doesn't prevent matching.

    Args:
        accumulated_spaced: Space-joined fragment text (e.g., "40 37 28").
        accumulated: Concatenated fragment text (e.g., "40-37-28").
        numeric_id_map: Dict mapping numeric IDs to their replacements.

    Returns:
        The replacement text if a match is found, else None.
    """
    for key in [accumulated_spaced, accumulated_spaced.strip(), accumulated, accumulated.strip()]:
        if key in numeric_id_map:
            return numeric_id_map[key]
    return None
 
 
 # ---------------------------------------------------------------------------
 # Digit scrambling
 # ---------------------------------------------------------------------------

# (Digit scrambling removed: numeric IDs are now replaced by repeating the
# last two digits of each ID — see _shared._repeat_last_two.)


# ---------------------------------------------------------------------------
# Fragment classification (built-in protected patterns)
# ---------------------------------------------------------------------------


def _is_builtin_protected(text: str) -> bool:
    """Return True if *text* matches a built-in protected pattern.

    Protected patterns are universal date/numeric formats that are never
    meaningful to scramble regardless of bank or statement type.
    Single-character fragments are also protected.
    Complete URL/domain fragments are protected so bank web addresses survive.

    Bank-specific structural text (payment type codes, balance markers, etc.)
    is handled via ``never_anonymise_system.toml`` instead.
    """
    stripped = text.strip()
    if not stripped or len(stripped) < 2:
        return True
    if _DATE_RE.match(stripped):
        return True
    if _DATE_COMPACT_RE.match(stripped):
        return True
    if _DATE_DAY_MONTH_RE.match(stripped):
        return True
    if _MONTH_NAME_RE.match(stripped):
        return True
    if _MONTH_COMPACT_RE.match(stripped):
        return True
    if _NUMERIC_RE.match(stripped):
        return True
    if _DATE_RANGE_RE.fullmatch(stripped):
        return True
    if _URL_RE.fullmatch(stripped):
        return True
    return False


# ---------------------------------------------------------------------------
# Fragment slot: decoded info for one Tj/TJ operand
# ---------------------------------------------------------------------------


class _Fragment(NamedTuple):
    raw: bytes  # original raw bytes from content stream
    font: str  # active font name at time of this operand
    decoded: str  # decoded unicode text


# Marker values for fragment disposition
_DISP_SCRAMBLE = "scramble"
_DISP_PROTECTED = "protected"


@dataclass
class _FragmentDisposition:
    kind: str  # _DISP_SCRAMBLE or _DISP_PROTECTED or a replacement str
    replacement: str | None = None  # set when kind == "always_anonymise"


# ---------------------------------------------------------------------------
# Fragment collection helper
# ---------------------------------------------------------------------------


def _collect_fragments(
    pike_page: pikepdf.Page,
    forward_maps: dict[str, dict[int, str]],
    font_encodings: dict[str, "_FontEncoding"] | None = None,
) -> list[_Fragment]:
    """Parse *pike_page*'s content stream and return a flat list of fragments.

    Each ``Tj``/``TJ`` string operand with non-empty decoded text becomes one
    :class:`_Fragment`.  The active font name is tracked via ``Tf`` operators.

    When font_encodings is provided, uses Identity-H aware decoding for CID-based
    fonts. Otherwise falls back to single-byte decoding.

    Args:
        pike_page: The pikepdf page to inspect.
        forward_maps: Per-font ToUnicode forward maps (glyph_byte -> unicode),
            as returned by :func:`_build_font_maps`.
        font_encodings: Optional per-font encoding metadata with Identity-H flags.
            When provided, enables multi-byte CID decoding for Identity-H fonts.

    Returns:
        List of :class:`_Fragment` objects in content-stream order.
    """

    try:
        instructions = list(pikepdf.parse_content_stream(pike_page))
    except Exception:
        return []

    fragments: list[_Fragment] = []
    current_font: str = ""

    for _instr_idx, (operands, operator) in enumerate(instructions):
        op = str(operator)

        if op == "Tf" and operands:
            try:
                current_font = str(operands[0])
            except Exception:
                current_font = ""

        elif op == "Tj" and operands:
            try:
                raw = bytes(operands[0])
                if raw:
                    # Use v2 decoder if font_encodings available
                    if font_encodings and current_font in font_encodings:
                        dec = _decode_raw_bytes_v2(raw, font_encodings[current_font])
                    else:
                        dec = _decode_raw_bytes(raw, current_font, forward_maps)
                    fragments.append(_Fragment(raw=raw, font=current_font, decoded=dec))
            except Exception:
                pass

        elif op == "TJ" and operands:
            try:
                arr = operands[0]
                for item in list(arr):  # type: ignore[arg-type]
                    if isinstance(item, pikepdf.String):
                        raw = bytes(item)
                        if raw:
                            # Use v2 decoder if font_encodings available
                            if font_encodings and current_font in font_encodings:
                                dec = _decode_raw_bytes_v2(raw, font_encodings[current_font])
                            else:
                                dec = _decode_raw_bytes(raw, current_font, forward_maps)
                            fragments.append(_Fragment(raw=raw, font=current_font, decoded=dec))
            except Exception:
                pass

    return fragments


# ---------------------------------------------------------------------------
# User numeric overrides: canonical digit normalisation
# ---------------------------------------------------------------------------


def _extract_user_numeric_overrides(
    always_cfg: "_AlwaysAnonymiseConfig",
) -> dict[str, str]:
    """Extract numeric-ID overrides from *always_cfg* keyed on canonical raw digits.

    For each ``original -> replacement`` entry in *always_cfg*, if *original*
    matches one of the numeric-ID patterns (e.g. ``"40-37-28"``), the
    separators are stripped from both sides and the result is stored as
    ``raw_digits -> replacement_raw_digits``.

    This allows ``"40-37-28" = "XX-XX-XX"`` to override *all* display variants
    of the same sort code (``"40 37 28"``, ``"403728"``, etc.) regardless of
    how they appear in the PDF.

    Note: only purely digit-replacing entries are included.  If the user
    writes ``"403728" = "XXXXXX"`` the replacement contains non-digits, which
    is stored as-is so :func:`_reapply_separators` can render it correctly.

    Args:
        always_cfg: Merged always-anonymise config.

    Returns:
        Dict mapping canonical raw digits (separators stripped) to canonical
        replacement raw digits (separators stripped from the replacement value).
    """
    overrides: dict[str, str] = {}
    for original, replacement in always_cfg.replacements.items():
        stripped = original.strip()
        for pattern in _NUMERIC_ID_PATTERNS:
            m = pattern.search(stripped)
            if m and m.group(0) == stripped:
                raw_original = _strip_numeric_separators(stripped)
                raw_replacement = _strip_numeric_separators(replacement)
                overrides[raw_original] = raw_replacement
                break
    return overrides


# ---------------------------------------------------------------------------
# Re-encoding helpers
# ---------------------------------------------------------------------------


def _reencode_fragment(
    text: str,
    font: str,
    reverse_maps: dict[str, dict[str, int]],
    font_encodings: dict[str, "_FontEncoding"] | None = None,
) -> bytes | None:
    """Re-encode *text* back to bytes using *font*'s encoding.

    For Identity-H fonts, encodes CIDs as 2-byte big-endian values.
    For single-byte fonts, encodes as single bytes.

    Returns None if re-encoding fails (e.g. character not in font's glyph set).
    """
    if font in reverse_maps:
        rev = reverse_maps[font]
        
        # Check if this is an Identity-H font
        is_identity_h = False
        if font_encodings and font in font_encodings:
            is_identity_h = font_encodings[font].is_identity_h
        
        try:
            if is_identity_h:
                # For Identity-H, CIDs can be > 255, so encode as 2-byte big-endian
                result = bytearray()
                for c in text:
                    cid = rev[c]
                    # Encode as 2-byte big-endian
                    result.append((cid >> 8) & 0xFF)
                    result.append(cid & 0xFF)
                return bytes(result)
            else:
                # For single-byte fonts, all codes should be 0-255
                return bytes(rev[c] for c in text)
        except (KeyError, ValueError):
            return None
    else:
        try:
            return text.encode("latin-1")
        except UnicodeEncodeError:
            result = bytearray()
            for ch in text:
                try:
                    result.extend(ch.encode("latin-1"))
                except UnicodeEncodeError:
                    result.extend(ch.encode("latin-1", errors="replace")[:1])
            return bytes(result)


def _scramble_text(
    text: str,
    scramble_map: dict[int, int],
) -> str:
    """Scramble letters in *text* using *scramble_map*; digits and symbols unchanged."""
    return "".join(chr(scramble_map.get(ord(ch), ord(ch))) if ch.isalpha() else ch for ch in text)


def _scramble_text_font_aware(
    text: str,
    scramble_map: dict[int, int],
    font: str,
    reverse_maps: dict[str, dict[str, int]],
) -> str:
    """Scramble *text* avoiding glyph-byte collisions in custom-encoded fonts.

    Standard scrambling may produce a replacement that re-encodes to the same
    glyph bytes as the original in two scenarios:

    1. The font's reverse CMap maps multiple unicode characters to the same
       glyph byte (many-to-one), so a different unicode char still encodes
       to the same byte.
    2. The replacement unicode char is not present in the reverse CMap at all,
       so ``_reencode_fragment`` would raise ``KeyError`` and return ``None``,
       causing the pair to be silently dropped.

    This function handles both cases per-character:

    * If the original char is not in the reverse map (not encodable in this
      font), it is kept as-is — attempting to replace it would break re-encoding.
    * If the preferred replacement encodes to the same glyph byte as the
      original, or is not encodable, the same-case letter list is searched
      for the first encodable alternative with a different glyph byte.
    * If no valid alternative exists, the original char is kept.

    For Latin-1 fonts (no ToUnicode reverse map), falls back to plain
    :func:`_scramble_text` since Latin-1 is an injective encoding (no
    glyph-byte collisions are possible).

    Args:
        text: Source text to scramble.
        scramble_map: Per-document letter translation table.
        font: Active font resource name (e.g. ``"/F2"``).
        reverse_maps: Per-font unicode→glyph-byte maps from
            :func:`_build_font_maps`.

    Returns:
        Scrambled text where every letter position either uses an alternative
        that encodes to a different glyph byte, or keeps the original if no
        such alternative exists.  Result is always fully re-encodable via
        ``_reencode_fragment``.
    """
    rev = reverse_maps.get(font)
    if rev is None:
        # Latin-1 font: bijective encoding, no collision possible.
        return _scramble_text(text, scramble_map)

    result: list[str] = []
    for ch in text:
        if not ch.isalpha():
            result.append(ch)
            continue

        preferred = chr(scramble_map.get(ord(ch), ord(ch)))

        # Only scramble chars that are encodable in this font's reverse map.
        # If the original char is not in the reverse map, re-encoding any
        # replacement would fail → keep the char as-is.
        orig_byte = rev.get(ch)
        if orig_byte is None:
            result.append(ch)
            continue

        pref_byte = rev.get(preferred)

        # No collision: preferred encodes to a different byte.
        if pref_byte is not None and pref_byte != orig_byte:
            result.append(preferred)
            continue

        # Either preferred is not encodable or encodes to the same byte.
        # Search same-case letters for one that is encodable AND encodes
        # to a byte different from orig_byte.
        candidates = _UPPER_LETTERS if ch.isupper() else _LOWER_LETTERS
        fallback = ch  # keep original if no valid replacement found
        for alt in candidates:
            if alt == ch:
                continue  # never map to self
            alt_byte = rev.get(alt)
            if alt_byte is not None and alt_byte != orig_byte:
                fallback = alt
                break

        result.append(fallback)

    return "".join(result)


# ---------------------------------------------------------------------------
# Core: Phase 1 + Phase 2 unified pair builder
# ---------------------------------------------------------------------------


def _build_scramble_bytes_pairs(
    pike_page: pikepdf.Page,
    scramble_map: dict[int, int],
    always_cfg: _AlwaysAnonymiseConfig,
    never_cfg: _NeverAnonymiseConfig,
    font_encodings: dict[str, "_FontEncoding"],
    forward_maps: dict[str, dict[int, str]],
    reverse_maps: dict[str, dict[str, int]],
    bold_fonts: frozenset[str],
    numeric_id_map: dict[str, str] | None = None,
) -> list[tuple[bytes, bytes]]:
    """Build ``(original_raw_bytes, replacement_raw_bytes)`` pairs for *pike_page*.

    Implements the three-phase architecture described in the module docstring.

    Args:
        pike_page: The pikepdf page to inspect.
        scramble_map: Letter translation table from :func:`_make_scramble_map`.
        always_cfg: Merged always-anonymise replacement rules.
        never_cfg: Merged never-anonymise protected phrases.
        font_encodings: Per-font encoding metadata with Identity-H flags.
        forward_maps: Per-font ToUnicode forward maps (glyph_byte -> unicode).
        reverse_maps: Per-font ToUnicode reverse maps (unicode -> glyph_byte).
        bold_fonts: Set of font resource names whose BaseFont is bold.
            Fragments rendered in these fonts are protected from scrambling.
        numeric_id_map: Optional document-level map of detected numeric ID
            display forms to their replacement display forms (produced by the
            pre-pass in :func:`anonymise_pdf`).  When provided, any accumulated
            fragment text matching a key is treated as an ``always`` replacement.

    Returns:
        List of ``(original_raw_bytes, replacement_raw_bytes)`` pairs, longest
        first.  May be empty if the page has no text or all fragments are
        protected.
    """
    if numeric_id_map is None:
        numeric_id_map = {}

    # ------------------------------------------------------------------
    # Phase 1 — Line-aware scan.
    # ------------------------------------------------------------------
    # Use _collect_fragments to get the flat fragment list; we also need
    # instruction indices for the pair builder, so we re-parse once more
    # to build the indexed list with line boundaries.
    # ------------------------------------------------------------------

    try:
        instructions = list(pikepdf.parse_content_stream(pike_page))
    except Exception:
        return []

    # Step 1a: collect (instr_idx, fragment) tuples and line boundaries.
    indexed_fragments: list[tuple[int, _Fragment]] = []
    current_font: str = ""
    line_ends: list[int] = []
    _last_tm_y: float | None = None  # y-coordinate of the most recent Tm

    for instr_idx, (operands, operator) in enumerate(instructions):
        op = str(operator)

        if op == "Tf" and operands:
            try:
                current_font = str(operands[0])
            except Exception:
                current_font = ""

        elif op in _LINE_BREAK_OPS:
            line_ends.append(len(indexed_fragments))

        elif op == "Tm" and operands and len(operands) >= 6:
            # Tm operands: [a b c d tx ty] — ty is the y position.
            # Only treat as a line break when y changes significantly.
            try:
                ty = float(str(operands[5]))
                if _last_tm_y is None or abs(ty - _last_tm_y) > _TM_Y_THRESHOLD:
                    line_ends.append(len(indexed_fragments))
                    _last_tm_y = ty
            except Exception:
                line_ends.append(len(indexed_fragments))

        elif op == "Tj" and operands:
            try:
                raw = bytes(operands[0])
                if raw:
                    # Use v2 decoder if font_encodings available
                    if current_font in font_encodings:
                        dec = _decode_raw_bytes_v2(raw, font_encodings[current_font])
                    else:
                        dec = _decode_raw_bytes(raw, current_font, forward_maps)
                    indexed_fragments.append((instr_idx, _Fragment(raw=raw, font=current_font, decoded=dec)))
            except Exception:
                pass

        elif op == "TJ" and operands:
            try:
                arr = operands[0]
                for item in list(arr):  # type: ignore[arg-type]
                    if isinstance(item, pikepdf.String):
                        raw = bytes(item)
                        if raw:
                            # Use v2 decoder if font_encodings available
                            if current_font in font_encodings:
                                dec = _decode_raw_bytes_v2(raw, font_encodings[current_font])
                            else:
                                dec = _decode_raw_bytes(raw, current_font, forward_maps)
                            indexed_fragments.append((instr_idx, _Fragment(raw=raw, font=current_font, decoded=dec)))
            except Exception:
                pass

    if not indexed_fragments:
        return []

    # Step 1b: build line ranges.
    total_frags = len(indexed_fragments)
    break_points = sorted(set([0] + line_ends + [total_frags]))
    lines: list[range] = []
    for i in range(len(break_points) - 1):
        start = break_points[i]
        end = break_points[i + 1]
        if end > start:
            lines.append(range(start, end))

    # Step 1c: for each fragment, assign a disposition via the sliding window.
    dispositions: list[str | None] = [None] * total_frags
    always_replacements: dict[int, str] = {}

    # Pre-normalise always_anonymise keys for fast lookup.
    always_normalised: dict[str, str] = {_normalise_phrase(k): v for k, v in always_cfg.replacements.items()}

    for line_range in lines:
        frags_in_line = [indexed_fragments[i][1] for i in line_range]
        n = len(frags_in_line)
        matched: set[int] = set()

        pos = 0
        while pos < n:
            if pos in matched:
                pos += 1
                continue

            found = False
            accumulated = ""  # no separator — for always/never/builtin checks
            accumulated_spaced = ""  # space-joined — mirrors pre-pass all_text for numeric ID lookup
            for end in range(pos, n):
                frag_decoded = frags_in_line[end].decoded
                accumulated += frag_decoded
                accumulated_spaced = accumulated_spaced + " " + frag_decoded if accumulated_spaced else frag_decoded
                norm = _normalise_phrase(accumulated)

                # 1. Check always_anonymise first (user wins; already merged).
                if norm in always_normalised:
                    replacement = always_normalised[norm]
                    for i in range(pos, end + 1):
                        frag_idx = line_range[i]
                        dispositions[frag_idx] = "always"
                        matched.add(i)
                    _distribute_replacement(
                        replacement,
                        [line_range[i] for i in range(pos, end + 1)],
                        frags_in_line[pos : end + 1],
                        always_replacements,
                    )
                    pos = end + 1
                    found = True
                    break

                # 2. Check never_anonymise phrases.
                if norm in never_cfg.phrases:
                    for i in range(pos, end + 1):
                        frag_idx = line_range[i]
                        dispositions[frag_idx] = "protected"
                        matched.add(i)
                    pos = end + 1
                    found = True
                    break

                # 3. Check numeric ID map — must come before built-in protected
                #    because _NUMERIC_RE would otherwise protect bare digit strings
                #    (e.g. 8-digit account numbers) before we can replace them.
                #    Check both the space-joined form (matches compound tokens
                #    like "403728 31243535") and the concatenated form (matches
                #    single-fragment tokens like "40-37-28").
                #    Also try stripped variants to handle fragments with leading/
                #    trailing whitespace (e.g. "                 5402 2250 0307 2770").
                replacement = _lookup_numeric_id(accumulated_spaced, accumulated, numeric_id_map)
                if replacement is not None:
                    for i in range(pos, end + 1):
                        frag_idx = line_range[i]
                        dispositions[frag_idx] = "always"
                        matched.add(i)
                    _distribute_replacement(
                        replacement,
                        [line_range[i] for i in range(pos, end + 1)],
                        frags_in_line[pos : end + 1],
                        always_replacements,
                    )
                    pos = end + 1
                    found = True
                    break

                # 4. Check built-in protected patterns.
                if _is_builtin_protected(accumulated):
                    for i in range(pos, end + 1):
                        frag_idx = line_range[i]
                        dispositions[frag_idx] = "protected"
                        matched.add(i)
                    pos = end + 1
                    found = True
                    break

            if not found:
                pos += 1

    # Step 1d: assign default (scramble) to all unmatched fragments.
    for i in range(total_frags):
        if dispositions[i] is None:
            _, frag = indexed_fragments[i]
            if frag.font in bold_fonts:
                dispositions[i] = "protected"
            elif _is_builtin_protected(frag.decoded):
                dispositions[i] = "protected"
            else:
                dispositions[i] = "scramble"

    # ------------------------------------------------------------------
    # Phase 2 — Build bytes pairs.
    # ------------------------------------------------------------------
    pairs: list[tuple[bytes, bytes]] = []
    seen_raw: set[bytes] = set()

    for i, (instr_idx, frag) in enumerate(indexed_fragments):
        raw = frag.raw
        if raw in seen_raw:
            continue

        disp = dispositions[i]

        if disp == "protected":
            seen_raw.add(raw)
            continue

        elif disp == "always":
            replacement_text = always_replacements.get(i)
            if replacement_text is None:
                seen_raw.add(raw)
                continue
            replacement_raw = _reencode_fragment(replacement_text, frag.font, reverse_maps, font_encodings)
            if replacement_raw is None or replacement_raw == raw:
                seen_raw.add(raw)
                continue
            pairs.append((raw, replacement_raw))
            seen_raw.add(raw)

        elif disp == "scramble":
            dec = frag.decoded
            if not dec:
                seen_raw.add(raw)
                continue

            # Handle compound tokens (payment-type prefix + description).
            compound = _COMPOUND_TYPE_DESC_RE.match(dec)
            if compound:
                prefix = compound.group(1)
                desc_part = compound.group(2)
                scrambled_desc = _scramble_text_font_aware(desc_part, scramble_map, frag.font, reverse_maps)
                if scrambled_desc == desc_part:
                    seen_raw.add(raw)
                    continue
                scrambled_full = prefix + scrambled_desc
            else:
                scrambled_full = _scramble_text_font_aware(dec, scramble_map, frag.font, reverse_maps)
                if scrambled_full == dec:
                    seen_raw.add(raw)
                    continue

            scrambled_raw = _reencode_fragment(scrambled_full, frag.font, reverse_maps, font_encodings)
            if scrambled_raw is None or scrambled_raw == raw:
                seen_raw.add(raw)
                continue

            pairs.append((raw, scrambled_raw))
            seen_raw.add(raw)

    # Longest-first to prevent short sequences matching inside longer ones.
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


# ---------------------------------------------------------------------------
# Replacement distribution helper
# ---------------------------------------------------------------------------


def _distribute_replacement(
    replacement: str,
    frag_indices: list[int],
    frags: list[_Fragment],
    always_replacements: dict[int, str],
) -> None:
    """Distribute *replacement* text across *frag_indices* slots.

    Each slot receives characters up to the length of the original fragment.
    The final slot absorbs any overflow or underflow (remainder or empty string).

    Args:
        replacement: The full replacement string to distribute.
        frag_indices: Global fragment indices for the matched span.
        frags: The _Fragment objects for the matched span (same order).
        always_replacements: Dict to write per-fragment replacement strings into.
    """
    remaining = replacement
    for slot_i, (frag_idx, frag) in enumerate(zip(frag_indices, frags)):
        is_last = slot_i == len(frag_indices) - 1
        slot_len = len(frag.decoded)
        if is_last:
            # Last slot absorbs all remaining characters.
            always_replacements[frag_idx] = remaining
        else:
            always_replacements[frag_idx] = remaining[:slot_len]
            remaining = remaining[slot_len:]


# ---------------------------------------------------------------------------
# Font map builder (extracted so anonymise_pdf can pass them in)
# ---------------------------------------------------------------------------


def _build_font_maps(
    pike_page: pikepdf.Page,
) -> tuple[dict[str, dict[int, str]], dict[str, dict[str, int]], frozenset[str]]:
    """Build per-font ToUnicode maps and bold font name set from page /Resources.

    Bold detection: a font is considered bold if its ``/BaseFont`` name contains
    the substring ``"Bold"`` (case-insensitive).  This covers ``Times-Bold``,
    ``Times-BoldItalic``, ``Helvetica-Bold``, custom embedded fonts with Bold
    in their PostScript name, etc.  Fragments rendered in a bold font are
    protected from scrambling regardless of their text content.

    Returns:
        Tuple of (forward_maps, reverse_maps, bold_fonts) where:
        forward_maps: font_name -> {glyph_byte -> unicode_char}
        reverse_maps: font_name -> {unicode_char -> glyph_byte}
        bold_fonts: set of font resource names (e.g. ``"/F2"``) that are bold
    """
    forward_maps: dict[str, dict[int, str]] = {}
    reverse_maps: dict[str, dict[str, int]] = {}
    bold_fonts: set[str] = set()

    try:
        res = pike_page.obj.get("/Resources", pikepdf.Dictionary())
        font_dict = res.get("/Font", pikepdf.Dictionary()) if res else pikepdf.Dictionary()
    except Exception:
        return forward_maps, reverse_maps, frozenset()

    for fname in font_dict.keys():
        try:
            f = font_dict[fname]

            # Detect bold by BaseFont name.
            base_font = str(f.get("/BaseFont", ""))
            if "bold" in base_font.lower():
                bold_fonts.add(str(fname))

            to_uni = f.get("/ToUnicode")
            if to_uni is None:
                continue
            fwd = _parse_tounicode_cmap(bytes(to_uni.read_bytes()))
            if not fwd:
                continue
            rev: dict[str, int] = {}
            for gb, uc in fwd.items():
                if uc not in rev:
                    rev[uc] = gb
            forward_maps[str(fname)] = fwd
            reverse_maps[str(fname)] = rev
        except Exception:
            continue

    return forward_maps, reverse_maps, frozenset(bold_fonts)


def _build_font_maps_v2(
    pike_page: pikepdf.Page,
) -> tuple[dict[str, "_FontEncoding"], dict[str, dict[str, int]], frozenset[str]]:
    """Build per-font font encodings, reverse maps, and bold font name set.

    Returns font encoding metadata (forward map + Identity-H flag), reverse maps
    for re-encoding, and the set of bold fonts.

    Returns:
        Tuple of (font_encodings, reverse_maps, bold_fonts) where:
        - font_encodings: font_name -> _FontEncoding (with forward_map and is_identity_h flag)
        - reverse_maps: font_name -> {unicode_char -> cid_or_byte}
        - bold_fonts: set of font resource names (e.g. '/F2') that are bold
    """
    font_encodings: dict[str, "_FontEncoding"] = {}
    reverse_maps: dict[str, dict[str, int]] = {}
    bold_fonts: set[str] = set()

    try:
        res = pike_page.obj.get("/Resources", pikepdf.Dictionary())
        font_dict = res.get("/Font", pikepdf.Dictionary()) if res else pikepdf.Dictionary()
    except Exception:
        return font_encodings, reverse_maps, frozenset()

    for fname in font_dict.keys():
        try:
            f = font_dict[fname]

            # Detect bold by BaseFont name.
            base_font = str(f.get("/BaseFont", ""))
            if "bold" in base_font.lower():
                bold_fonts.add(str(fname))

            to_uni = f.get("/ToUnicode")
            if to_uni is None:
                continue
            fwd = _parse_tounicode_cmap(bytes(to_uni.read_bytes()))
            if not fwd:
                continue

            # Detect Identity-H encoding
            is_identity_h = _is_identity_h_font(f)

            # Build reverse map and font encoding metadata
            rev: dict[str, int] = {}
            for glyph_code, unicode_char in fwd.items():
                if unicode_char not in rev:
                    rev[unicode_char] = glyph_code

            fname_str = str(fname)
            font_encodings[fname_str] = _FontEncoding(
                font_name=fname_str,
                forward_map=fwd,
                is_identity_h=is_identity_h,
            )
            reverse_maps[fname_str] = rev
        except Exception:
            continue

    return font_encodings, reverse_maps, frozenset(bold_fonts)


def anonymise_pdf(
    input_path: Path,
    output_path: Path | None = None,
    always_anonymise_path: Path | None = None,
    never_anonymise_path: Path | None = None,
    debug: bool = False,
) -> Path:
    """Anonymise a single PDF using exclusion-based full-page letter scrambling.

    The library detects and replaces sensitive data (sort codes, account numbers,
    card numbers, and other patterns) with deterministic fake values. Structural
    text like dates, payment codes, and protected phrases remain readable. All other
    letters are scrambled while digits and symbols stay intact. The PDF's layout,
    fonts, and images are preserved.

    Args:
        input_path: Path to the source PDF to anonymise.
        output_path: Destination path for the anonymised PDF. When ``None``,
            the output filename is derived from *input_path* by prepending
            ``anonymised_`` and leaving the stem unchanged.
        always_anonymise_path: Path to a user ``always_anonymise.toml``.
            When ``None``, only the bundled system file is used.
        never_anonymise_path: Path to a user ``never_anonymise.toml``.
            When ``None``, only the bundled system file is used.
        debug: When ``True``, print diagnostic information about config loading,
            numeric ID detection, and per-page pair building.

    Returns:
        Path to the anonymised output PDF.

    Raises:
        FileNotFoundError: If *input_path* does not exist.
    """

    def _dbg(msg: str) -> None:
        if debug:
            print(f"[DEBUG] {msg}")

    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_path}")

    # Load configs.
    always_cfg = _load_always_anonymise(
        system_path=_bundled_path("always_anonymise_system.toml"),
        user_path=Path(always_anonymise_path) if always_anonymise_path is not None else None,
    )
    never_cfg = _load_never_anonymise(
        system_path=_bundled_path("never_anonymise_system.toml"),
        user_path=Path(never_anonymise_path) if never_anonymise_path is not None else None,
    )

    _dbg(f"always_anonymise: {len(always_cfg.replacements)} rule(s): {list(always_cfg.replacements.keys())}")
    _dbg(f"never_anonymise: {len(never_cfg.phrases)} phrase(s)")

    if output_path is None:
        output_path = input_path.with_name(f"{_ANONYMISED_PREFIX}{input_path.stem}{input_path.suffix}")
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    scramble_map = _make_scramble_map()
    total_pairs = 0

    pike_doc = pikepdf.open(str(input_path))
    try:
        # ------------------------------------------------------------------
        # Document-level pre-pass: collect all fragment text and detect
        # numeric IDs (sort codes, account numbers, card numbers, etc.)
        # consistently across the whole document.
        # ------------------------------------------------------------------
        all_text_parts: list[str] = []
        for pike_page in pike_doc.pages:
            forward_maps_pre, _, _ = _build_font_maps(pike_page)
            for frag in _collect_fragments(pike_page, forward_maps_pre):
                if frag.decoded:
                    all_text_parts.append(frag.decoded)
        all_text = " ".join(all_text_parts)

        _dbg(f"pre-pass collected {len(all_text_parts)} fragment(s), {len(all_text)} chars total")
        _dbg(f"all_text (first 500 chars): {all_text[:500]!r}")

        # Build user numeric overrides (canonical raw digits -> replacement raw digits).
        user_numeric_overrides = _extract_user_numeric_overrides(always_cfg)
        _dbg(f"user_numeric_overrides (canonical digits): {user_numeric_overrides}")

        # Build the document-level numeric ID map.
        numeric_id_map = _detect_numeric_ids(all_text, user_numeric_overrides)
        _dbg(f"numeric_id_map ({len(numeric_id_map)} entry/entries):")
        for k, v in numeric_id_map.items():
            _dbg(f"  {k!r} -> {v!r}")

        # ------------------------------------------------------------------
        # Main per-page pass.
        # ------------------------------------------------------------------
        for page_num, pike_page in enumerate(pike_doc.pages, start=1):
            forward_maps, reverse_maps, bold_fonts = _build_font_maps(pike_page)
            font_encodings, _, _ = _build_font_maps_v2(pike_page)
            _dbg(f"page {page_num}: fonts={list(forward_maps.keys())}, bold={list(bold_fonts)}")

            pairs = _build_scramble_bytes_pairs(
                pike_page,
                scramble_map,
                always_cfg,
                never_cfg,
                font_encodings,
                forward_maps,
                reverse_maps,
                bold_fonts,
                numeric_id_map=numeric_id_map,
            )
            _dbg(f"page {page_num}: {len(pairs)} pair(s) built")
            if debug:
                for orig_b, repl_b in pairs[:20]:  # cap at 20 to avoid flooding
                    try:
                        orig_s = orig_b.decode("latin-1")
                    except Exception:
                        orig_s = repr(orig_b)
                    try:
                        repl_s = repl_b.decode("latin-1")
                    except Exception:
                        repl_s = repr(repl_b)
                    print(f"[DEBUG]   pair: {orig_s!r} -> {repl_s!r}")
                if len(pairs) > 20:
                    print(f"[DEBUG]   ... ({len(pairs) - 20} more pair(s) not shown)")

            if pairs:
                _rewrite_page_content_stream(pike_page, pike_doc, pairs)
                total_pairs += len(pairs)

        pike_doc.save(str(output_path), compress_streams=True)
    finally:
        pike_doc.close()

    print(f"Anonymised: {input_path.name} -> {output_path.name} ({total_pairs} scramble pair(s))")
    return output_path
