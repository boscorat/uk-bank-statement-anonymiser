"""
_shared — shared constants, patterns, and engine functions for PDF anonymisation.

This internal module is imported by :mod:`anonymise`.  It contains:

* Compiled regex patterns for universal date and numeric token classification
  (payment type codes and bank-specific structural text live in
  ``never_anonymise_system.toml`` instead)
* The per-document scramble-map builder (:func:`_make_scramble_map`)
* The pikepdf content-stream rewriter (:func:`_rewrite_page_content_stream`)
* ToUnicode CMap parsing helpers

None of the symbols here form part of the public API.  Import from
:mod:`anonymise` instead.

All PDF text extraction is performed directly via pikepdf's content-stream
parser.  pdfplumber is not used — this avoids the model mismatch between
pdfplumber's visual/rendered word model and the PDF encoding model, which
caused multi-Tj word merging and space attribution bugs.
"""

from __future__ import annotations

import re
import secrets

import pikepdf

# ---------------------------------------------------------------------------
# ToUnicode CMap parsing
# ---------------------------------------------------------------------------


def _parse_tounicode_cmap(stream_bytes: bytes) -> dict[int, str]:
    """Parse a PDF ToUnicode CMap stream into a glyph-byte → Unicode-char mapping.

    Handles the ``beginbfchar`` / ``endbfchar`` sections found in standard
    ToUnicode CMaps.  Only single-byte glyph codes (``<XX>``) mapping to a
    single Unicode code point (``<YYYY>``) are extracted; multi-byte codes and
    range sections (``beginbfrange``) are ignored.

    Supports both UTF-16-BE (with BOM prefix) and Latin-1 encoded streams,
    which can occur in PDFs with custom font encodings.

    Args:
        stream_bytes: Raw bytes of the ToUnicode CMap stream.

    Returns:
        Dict mapping each glyph byte value (0–255) to the Unicode character it
        represents.  Entries where the Unicode code point is U+0000 (unmapped)
        are omitted.
    """
    # Detect UTF-16-BE encoding (BOM prefix: \xfe\xff) used in some bank PDFs.
    # If not UTF-16-BE, fall back to Latin-1 (common for most PDFs).
    if stream_bytes.startswith(b"\xfe\xff"):
        try:
            text = stream_bytes.decode("utf-16-be")
        except Exception:
            text = stream_bytes.decode("latin-1", errors="replace")
    else:
        text = stream_bytes.decode("latin-1", errors="replace")
    result: dict[int, str] = {}
    for m in re.finditer(r"<([0-9a-fA-F]{2})>\s*<([0-9a-fA-F]{4})>", text):
        glyph_byte = int(m.group(1), 16)
        unicode_cp = int(m.group(2), 16)
        if unicode_cp != 0:
            result[glyph_byte] = chr(unicode_cp)
    return result


# ---------------------------------------------------------------------------
# Output filename prefix
# ---------------------------------------------------------------------------

_ANONYMISED_PREFIX: str = "anonymised_"

# ---------------------------------------------------------------------------
# Description-scrambling constants
# ---------------------------------------------------------------------------

# Month names: 3-letter abbreviations and full names, case-sensitive initial cap.
# Covers both "Jan" and "January", "Jun" and "June", etc.
# Must be defined first as it is referenced by all date patterns below.
_MONTH_NAMES: str = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?"
    r"|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)

# Transaction date: "d Mmm yy" or "d Mmm yyyy"  (e.g. "23 Jan 25", "24 Aug 2019",
# "15 June 2025").
_DATE_RE: re.Pattern[str] = re.compile(
    rf"^\d{{1,2}}\s{_MONTH_NAMES}\s\d{{2}}(?:\d{{2}})?$",
    re.IGNORECASE,
)

# Partial date — day + month only (e.g. "03 Jan", "15 June").
_DATE_DAY_MONTH_RE: re.Pattern[str] = re.compile(
    rf"^\d{{1,2}}\s{_MONTH_NAMES}$",
    re.IGNORECASE,
)

# Compact date — month+year appended without space (e.g. "11 Dec21", "15 June2025").
# Supports 2- or 4-digit year suffix.
_DATE_COMPACT_RE: re.Pattern[str] = re.compile(
    rf"^\d{{1,2}}\s{_MONTH_NAMES}\d{{2}}(?:\d{{2}})?$",
    re.IGNORECASE,
)

# Date range: "d Mmm [yy[yy]] to d Mmm [yy[yy]]"
# e.g. "24 Aug 2019 to 24 Sep 2019", "16 May 2025 to 15 June 2025"
# Year is optional on either side; 2- or 4-digit year both accepted.
_DATE_PART: str = rf"\d{{1,2}}\s{_MONTH_NAMES}(?:\s\d{{2}}(?:\d{{2}})?)?"
_DATE_RANGE_RE: re.Pattern[str] = re.compile(
    rf"^{_DATE_PART}\sto\s{_DATE_PART}$",
    re.IGNORECASE,
)

# Compound token: payment-type prefix merged with description word.
# The payment type codes here mirror those in never_anonymise_system.toml.
# This pattern is kept in code because it requires algorithmic prefix-stripping
# (not just phrase matching) — the description part after the prefix is scrambled.
_COMPOUND_TYPE_DESC_RE: re.Pattern[str] = re.compile(
    r"^(BP|\)\)\)|VIS|DD|TFR|SO|CR|DR|ATM|CC|OBP)([A-Za-z].*)$",
    re.IGNORECASE,
)

# Numeric value / polarity suffix.
_NUMERIC_RE: re.Pattern[str] = re.compile(r"^[\d£$€\s,\.\-]+(?:CR|D)?$|^CR$|^D$")

# Reference number: starts with digit, contains only digits and hyphens, ≥5 chars.
_REF_NUMBER_RE: re.Pattern[str] = re.compile(r"^\d[\d\-]{4,}$", re.IGNORECASE)

# Standalone month name — 3-letter abbreviation or full name (e.g. "Jan", "June").
_MONTH_NAME_RE: re.Pattern[str] = re.compile(rf"^{_MONTH_NAMES}$", re.IGNORECASE)

# Compact month+year token — abbreviation or full name with 2-digit year appended
# (e.g. "Dec21", "June21").
_MONTH_COMPACT_RE: re.Pattern[str] = re.compile(rf"^{_MONTH_NAMES}\d{{2}}$", re.IGNORECASE)

# Exact phrase strings (no spaces) that some PDFs render as single-character Tj runs.
# These are protected by the charrun pre-pass in _rewrite_page_content_stream.
# Kept here because the detection is structural (single-char Tj runs), not phrase matching.
_PROTECTED_CHARRUN_PHRASES: frozenset[str] = frozenset(
    {
        "BALANCEBROUGHTFORWARD",
        "BALANCECARRIEDFORWARD",
        "SummaryOfInterestOnThisStatement",
    }
)

# ---------------------------------------------------------------------------
# Numeric ID patterns
# ---------------------------------------------------------------------------

# Sort code: 6 digits with hyphens or spaces as separators.
# Matches: 40-37-28  40 37 28  40-37 28  etc.
# Does NOT match bare 6-digit runs (too many false positives with phone numbers).
_SORT_CODE_RE: re.Pattern[str] = re.compile(r"\b(\d{2})[-\s](\d{2})[-\s](\d{2})\b")

# Account number: bare 8-digit run, word-boundary anchored.
_ACCOUNT_RE: re.Pattern[str] = re.compile(r"\b(\d{8})\b")

# Compound sort-code + account on same token: 6 digits, single space, 8 digits.
# e.g. "403728 31243535"
_SORT_ACCT_RE: re.Pattern[str] = re.compile(r"\b(\d{6}) (\d{8})\b")

# Credit/debit card: 16 digits in 4 groups of 4, separated by spaces.
# e.g. "3333 2222 1111 0000"
_CARD_RE: re.Pattern[str] = re.compile(r"\b(\d{4}) (\d{4}) (\d{4}) (\d{4})\b")

# MICR card format: 4 digits, space, 12 digits (e.g. "5402 225003072770").
# Used on bank giro credit slips where the card number is printed without
# internal spaces in the 12-digit portion.
_CARD_MICR_RE: re.Pattern[str] = re.compile(r"\b(\d{4}) (\d{12})\b")

# MICR giro line: 16-digit card number followed by MICR tail ending in a
# single letter check character.
# e.g. "<5402225003072770< 774831+< 73   X"
# group(1) = 16-digit card number; group(2) = everything from the second '<'
# to the trailing check letter (inclusive).
# The full match (group 0) becomes the numeric_id_map key so the entire
# fragment text is replaced in one hit.
_MICR_LINE_RE: re.Pattern[str] = re.compile(r"<(\d{16})(<[^A-Za-z\n]*[A-Za-z])")

# Full IBAN token: letters/digits prefix followed by exactly 14 trailing digits
# (sort code 6 + account 8 concatenated).
# e.g. "VN72JNEB40372831243535" — only the last 14 digits are replaced;
# the letter/check-digit prefix is preserved verbatim.
_IBAN_FULL_RE: re.Pattern[str] = re.compile(r"\b[A-Z0-9]*[A-Z](\d{14})\b", re.IGNORECASE)

# Spaced UK IBAN: 2-letter country code + 2 check digits + 4-letter bank code +
# 14 sensitive digits rendered in groups of 4-4-4-2 separated by spaces.
# e.g. "GB19 NWBK 6016 2400 3980 04"
# Group 1 captures the preserved prefix ("GB19 NWBK "); group 2 captures the
# 14 sensitive digit groups ("6016 2400 3980 04") which are replaced.
_IBAN_SPACED_RE: re.Pattern[str] = re.compile(
    r"\b([A-Z]{2}\d{2} [A-Z]{4} )(\d{4} \d{4} \d{4} \d{2})\b",
    re.IGNORECASE,
)

# IBAN tail: exactly 14 consecutive digits (sort code 6 + account 8 concatenated).
# Fallback for when the IBAN tail appears as a bare digit run without a letter prefix.
_IBAN_TAIL_RE: re.Pattern[str] = re.compile(r"\b(\d{14})\b")

# URL pattern: complete URL or domain — used for single-fragment protection.
# Matches http(s):// or www. prefixed strings, or tokens ending in a known TLD.
_URL_RE: re.Pattern[str] = re.compile(
    r"(?:https?://\S+|www\.\S+|\S+\.(?:co\.uk|com|org|net|gov\.uk|bank))",
    re.IGNORECASE,
)

# All numeric-ID patterns in priority order (most specific first).
# IMPORTANT: _SORT_ACCT_RE / _SORT_CODE_RE / _ACCOUNT_RE must come before
# _IBAN_SPACED_RE / _IBAN_FULL_RE / _IBAN_TAIL_RE so that sort+account raw digits
# are already cached in raw_to_scrambled when the IBAN composition logic runs.
_NUMERIC_ID_PATTERNS: tuple[re.Pattern[str], ...] = (
    _CARD_RE,  # 16 digits (4×4) — most specific card format
    _CARD_MICR_RE,  # 16 digits (4+12) — MICR giro slip card format
    _MICR_LINE_RE,  # <16digits< — MICR giro line (card number in delimiters)
    _SORT_ACCT_RE,  # 6+8 compound — caches both halves before IBAN processing
    _SORT_CODE_RE,  # 6 digits with separators
    _ACCOUNT_RE,  # bare 8 digits
    _IBAN_SPACED_RE,  # spaced UK IBAN e.g. "GB19 NWBK 6016 2400 3980 04"
    _IBAN_FULL_RE,  # compact IBAN token (tail-only replacement)
    _IBAN_TAIL_RE,  # bare 14-digit run fallback
)

# The 26 lowercase and uppercase ASCII letters as tuples.
_LOWER_LETTERS: tuple[str, ...] = tuple("abcdefghijklmnopqrstuvwxyz")
_UPPER_LETTERS: tuple[str, ...] = tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


# ---------------------------------------------------------------------------
# Scramble-map builder
# ---------------------------------------------------------------------------


def _make_scramble_map() -> dict[int, int]:
    """Build a randomised character-translation table for letter scrambling.

    Each lowercase letter is mapped to a different randomly-chosen lowercase
    letter; each uppercase letter is mapped to a different randomly-chosen
    uppercase letter.  Generated once per document call for consistency.

    Returns:
        A translation table suitable for use with :meth:`str.translate`.
    """
    rng = secrets.SystemRandom()

    lower_shuffled = list(_LOWER_LETTERS)
    while True:
        rng.shuffle(lower_shuffled)
        if all(orig != shuf for orig, shuf in zip(_LOWER_LETTERS, lower_shuffled)):
            break

    upper_shuffled = list(_UPPER_LETTERS)
    while True:
        rng.shuffle(upper_shuffled)
        if all(orig != shuf for orig, shuf in zip(_UPPER_LETTERS, upper_shuffled)):
            break

    mapping: dict[int, int] = {}
    for orig, shuf in zip(_LOWER_LETTERS, lower_shuffled):
        mapping[ord(orig)] = ord(shuf)
    for orig, shuf in zip(_UPPER_LETTERS, upper_shuffled):
        mapping[ord(orig)] = ord(shuf)
    return mapping


# ---------------------------------------------------------------------------
# Numeric ID detection and scrambling
# ---------------------------------------------------------------------------


def _strip_numeric_separators(text: str) -> str:
    """Return only the digit characters from *text*."""
    return "".join(ch for ch in text if ch.isdigit())


def _reapply_separators(original_display: str, new_digits: str) -> str:
    """Re-apply the separator characters from *original_display* to *new_digits*.

    Walks *original_display* character by character.  Each digit position is
    filled from *new_digits* in order; non-digit characters (separators) are
    copied verbatim.  If *new_digits* is exhausted early the remainder of
    *original_display* is appended as-is; if *new_digits* has surplus digits
    they are appended at the end.

    Args:
        original_display: The original text string (e.g. ``"40-37-28"``).
        new_digits: The replacement digit string (e.g. ``"756291"``).

    Returns:
        The display form with separators from *original_display* and digits
        from *new_digits* (e.g. ``"75-62-91"``).
    """
    result: list[str] = []
    digit_iter = iter(new_digits)
    for ch in original_display:
        if ch.isdigit():
            try:
                result.append(next(digit_iter))
            except StopIteration:
                # new_digits exhausted — keep original separator tail
                result.append(ch)
        else:
            result.append(ch)
    # Append any surplus new digits.
    for ch in digit_iter:
        result.append(ch)
    return "".join(result)


def _repeat_last_two(raw_digits: str) -> str:
    """Build a replacement digit string by repeating the last two digits.

    The replacement is constructed by tiling the last two digits of
    *raw_digits* to fill the same length, making anonymised numeric IDs
    obviously fake and cross-document consistent (same account always
    produces the same replacement).

    Fallback rules (in order):
    1. If repeating the last two digits reproduces *raw_digits* exactly,
       repeat the last single digit instead.
    2. If that also reproduces *raw_digits* (entire string is a single
       repeated digit), use ``'0'`` repeated — or ``'1'`` if the original
       is all zeros.

    Args:
        raw_digits: String of digit characters only (e.g. ``"40372831243535"``).

    Returns:
        Replacement digit string of the same length (e.g. ``"35353535353535"``).
    """
    n = len(raw_digits)
    tail2 = raw_digits[-2:]
    candidate = (tail2 * ((n // 2) + 1))[:n]
    if candidate != raw_digits:
        return candidate

    # Last-two repetition reproduces the original — try last single digit.
    tail1 = raw_digits[-1]
    candidate1 = tail1 * n
    if candidate1 != raw_digits:
        return candidate1

    # Single-digit repetition also reproduces the original (e.g. "8888").
    # Use fixed fallback: '0' unless original is all zeros, then '1'.
    fallback = "1" if raw_digits[0] == "0" else "0"
    return fallback * n


def _detect_numeric_ids(
    all_text: str,
    user_overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Scan *all_text* for numeric IDs and build a display-form replacement map.

    Detects sort codes, account numbers, credit card numbers, compound
    sort+account tokens, full IBAN tokens, bare IBAN tails, MICR card formats,
    and MICR giro lines.  Each unique raw-digit string is replaced using
    :func:`_repeat_last_two` — tiling the last two digits across the full
    length — so replacements are deterministic, obviously fake, and consistent
    across runs and documents sharing the same account.

    Separator format is preserved per-occurrence: ``40-37-28`` stays
    hyphenated, ``40 37 28`` stays spaced, ``403728`` stays bare.

    For full IBAN tokens (e.g. ``VN72JNEB40372831243535``), only the trailing
    14 digits (sort code 6 + account 8) are replaced; the letter/check-digit
    prefix is preserved verbatim.

    For any 14-digit raw string, if its first 6 digits and last 8 digits have
    already been assigned replacement values (from sort code / account detection
    earlier in the same pass), those cached values are concatenated to form the
    IBAN tail replacement — ensuring the IBAN tail is consistent with the
    sort code and account number replacements elsewhere in the document.

    *user_overrides* maps canonical raw digits (separators stripped) to
    canonical replacement raw digits.  When a detected numeric ID's raw digits
    appear in *user_overrides*, the user's replacement digits are used instead
    of the computed ones.  Separators are still re-applied from the original
    display form.

    Args:
        all_text: Concatenation of all decoded fragment text from the document
            (pages joined by spaces).
        user_overrides: Optional mapping of
            ``canonical_raw_digits -> canonical_replacement_digits`` derived
            from the user's ``always_anonymise`` config.

    Returns:
        Dict mapping each detected display-form occurrence (as it appears in
        *all_text*) to its replacement display-form string.
    """
    if user_overrides is None:
        user_overrides = {}

    # Cache: canonical raw digits -> replacement raw digits (computed once).
    raw_to_scrambled: dict[str, str] = {}

    def _get_replacement_digits(raw: str) -> str:
        # User override always wins.
        if raw in user_overrides:
            return user_overrides[raw]
        if raw in raw_to_scrambled:
            return raw_to_scrambled[raw]
        # For 14-digit IBAN tails: try to compose from cached sort (6) + account (8).
        if len(raw) == 14:
            sort_part = raw[:6]
            acct_part = raw[6:]
            sort_scrambled = raw_to_scrambled.get(sort_part) or user_overrides.get(sort_part)
            acct_scrambled = raw_to_scrambled.get(acct_part) or user_overrides.get(acct_part)
            if sort_scrambled is not None and acct_scrambled is not None:
                composed = sort_scrambled + acct_scrambled
                raw_to_scrambled[raw] = composed
                return composed
        # Compute replacement using last-two-digits repetition.
        replacement = _repeat_last_two(raw)
        raw_to_scrambled[raw] = replacement
        return replacement

    result: dict[str, str] = {}

    for pattern in _NUMERIC_ID_PATTERNS:
        for m in pattern.finditer(all_text):
            display = m.group(0)
            if display in result:
                continue  # already mapped by a higher-priority pattern

            if pattern is _IBAN_FULL_RE:
                # Only replace the 14-digit tail; preserve the letter prefix verbatim.
                tail_raw = _strip_numeric_separators(m.group(1))  # group(1) = the 14 digits
                replacement_tail = _get_replacement_digits(tail_raw)
                # Also cache the tail digits independently for consistency.
                raw_to_scrambled.setdefault(tail_raw, replacement_tail)
                # Build the replacement display: prefix unchanged + scrambled tail.
                tail_start = m.start(1) - m.start(0)  # offset of tail within display
                prefix = display[:tail_start]
                result[display] = prefix + replacement_tail

            elif pattern is _IBAN_SPACED_RE:
                # Group 1 = preserved prefix e.g. "GB19 NWBK "
                # Group 2 = spaced digit section e.g. "6016 2400 3980 04"
                digit_section = m.group(2)
                tail_raw = _strip_numeric_separators(digit_section)  # 14 bare digits
                replacement_tail = _get_replacement_digits(tail_raw)
                raw_to_scrambled.setdefault(tail_raw, replacement_tail)
                # Re-apply the original spacing (4-4-4-2) to replacement digits.
                replacement_digit_section = _reapply_separators(digit_section, replacement_tail)
                prefix = m.group(1)
                result[display] = prefix + replacement_digit_section

            elif pattern is _MICR_LINE_RE:
                # Preserve '<' delimiters and all non-card-number content verbatim;
                # only replace the 16-digit card number (group 1).
                # group(2) is everything from the second '<' to the trailing check char.
                card_raw = m.group(1)
                tail = m.group(2)  # already includes the leading '<'
                replacement_digits = _get_replacement_digits(card_raw)
                raw_to_scrambled.setdefault(card_raw, replacement_digits)
                result[display] = "<" + replacement_digits + tail

            else:
                raw = _strip_numeric_separators(display)
                replacement_digits = _get_replacement_digits(raw)
                replacement_display = _reapply_separators(display, replacement_digits)
                result[display] = replacement_display

    return result


# ---------------------------------------------------------------------------
# Content-stream operand decoder
# ---------------------------------------------------------------------------


def _decode_pdf_operand(obj: pikepdf.Object) -> str:
    """Decode a pikepdf string operand to a Python str, best-effort.

    Tries UTF-16-BE (BOM-prefixed) first, then Latin-1.

    Args:
        obj: A ``pikepdf.String`` or ``pikepdf.Object`` from a content stream.

    Returns:
        Python str of the decoded text.
    """
    raw: bytes = bytes(obj)
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", errors="replace")
    try:
        return raw.decode("latin-1")
    except Exception:
        return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Content-stream rewriter
# ---------------------------------------------------------------------------


def _rewrite_page_content_stream(
    pike_page: pikepdf.Page,
    pike_doc: pikepdf.Pdf,
    scramble_bytes_pairs: list[tuple[bytes, bytes]],
) -> bool:
    """Apply bytes-level scramble pairs to *pike_page*'s content stream.

    Parses the page content stream and for every ``Tj`` / ``TJ`` text-showing
    operator performs an exact-bytes match against *scramble_bytes_pairs*,
    replacing matching operands in place.

    A pre-pass identifies ``Tj`` instructions that form single-character runs
    spelling a phrase in :data:`_PROTECTED_CHARRUN_PHRASES` and excludes them
    from replacement.

    Args:
        pike_page: The pikepdf page to modify in place.
        pike_doc: The owning :class:`pikepdf.Pdf` document.
        scramble_bytes_pairs: List of ``(original_raw_bytes, scrambled_raw_bytes)``
            pairs.  Matching is exact equality on ``bytes(operand)``.

    Returns:
        ``True`` if at least one replacement was made; ``False`` otherwise.
    """
    if not scramble_bytes_pairs:
        return False

    try:
        instructions = list(pikepdf.parse_content_stream(pike_page))
    except Exception:
        return False

    # Build a fast lookup: original_bytes -> scrambled_bytes
    lookup: dict[bytes, bytes] = dict(scramble_bytes_pairs)

    # ------------------------------------------------------------------
    # Pre-pass: identify Tj indices that are part of a single-char run
    # spelling a protected phrase — these must not be scrambled.
    # ------------------------------------------------------------------
    frozen_indices: set[int] = set()
    pending: list[tuple[int, str]] = []

    def _any_starts_with(prefix: str) -> bool:
        return any(p.startswith(prefix) for p in _PROTECTED_CHARRUN_PHRASES)

    def _flush(complete: bool) -> None:
        if not pending:
            return
        if complete and "".join(c for _, c in pending) in _PROTECTED_CHARRUN_PHRASES:
            for idx, _ in pending:
                frozen_indices.add(idx)
        pending.clear()

    for idx, (operands, operator) in enumerate(instructions):
        op = str(operator)
        if op == "Tm":
            continue
        if op == "Tj" and operands and isinstance(operands[0], pikepdf.String):
            ch = _decode_pdf_operand(operands[0])
            if len(ch) == 1:
                candidate = "".join(c for _, c in pending) + ch
                if _any_starts_with(candidate):
                    pending.append((idx, ch))
                    if candidate in _PROTECTED_CHARRUN_PHRASES:
                        _flush(complete=True)
                    continue
                else:
                    _flush(complete=False)
                    if _any_starts_with(ch):
                        pending.append((idx, ch))
                        continue
            else:
                _flush(complete=False)
        else:
            _flush(complete=False)

    _flush(complete=False)

    # ------------------------------------------------------------------
    # Main pass: replace matching operands.
    # ------------------------------------------------------------------
    changed = False
    new_instructions: list[tuple[list[pikepdf.Object], pikepdf.Operator]] = []

    for idx, (operands, operator) in enumerate(instructions):
        op = str(operator)

        if op == "Tj" and operands and idx not in frozen_indices:
            obj = operands[0]
            if isinstance(obj, pikepdf.String):
                raw = bytes(obj)
                replacement = lookup.get(raw)
                if replacement is not None:
                    operands = [pikepdf.String(replacement)]
                    changed = True

        elif op == "TJ" and operands:
            arr = operands[0]
            if isinstance(arr, pikepdf.Array):
                new_items: list[pikepdf.Object] = []
                arr_changed = False
                for item in list(arr):  # type: ignore[arg-type]
                    if isinstance(item, pikepdf.String):
                        raw = bytes(item)
                        replacement = lookup.get(raw)
                        if replacement is not None:
                            new_items.append(pikepdf.String(replacement))
                            arr_changed = True
                            changed = True
                        else:
                            new_items.append(item)
                    else:
                        new_items.append(item)
                if arr_changed:
                    operands = [pikepdf.Array(new_items)]  # type: ignore[assignment]

        new_instructions.append((operands, operator))  # type: ignore[arg-type]

    if changed:
        new_stream = pikepdf.unparse_content_stream(new_instructions)
        pike_page.obj["/Contents"] = pike_doc.make_stream(new_stream)

    return changed
