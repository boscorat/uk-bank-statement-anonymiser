"""
phrase_replace_pdf — Character-by-character phrase replacement in anonymised PDFs.

This module provides a post-anonymisation function to replace sequences of
characters in already-anonymised PDFs. Unlike the anonymisation pipeline itself,
this function operates in complete isolation, searching for individual characters
in sequence across the PDF content stream (ignoring non-character operators) and
replacing them according to user-provided rules.

Use Case
--------
After anonymisation, some phrases may not have been anonymised correctly due to
non-standard formatting. For example, a non-standard date format like "21st Sep"
(with ordinal suffix, no year) won't match built-in date patterns and may be
scrambled character-by-character to "21a Uad". The phrase_replace_pdf() function
allows users to reverse this by providing a config file with the mapping.

Algorithm
---------
For each phrase replacement rule ("21a Uad" -> "21st Sep"):
1. Build font maps to decode glyph bytes to Unicode text
2. Extract character arrays from search phrase ['2', '1', 'a', ' ', 'U', 'a', 'd']
3. Extract character arrays from replacement phrase ['2', '1', 's', ' ', 'S', 'e', 'p']
4. Parse page content stream and extract character operators (Tj, TJ)
5. For each string in operators:
   - Decode bytes to text using font's ToUnicode map
   - Scan for search phrase match in decoded text
   - When match found, record positions of matching bytes
   - Replace those bytes with corresponding replacement bytes
6. Rebuild content stream and write back to page

Key Design Decisions
--------------------
- Characters are matched by first decoding bytes using font's ToUnicode CMap
- Matching is done on decoded text, replacements applied to raw bytes
- Non-character operators (Tm, TL, Td, etc.) are ignored
- Matching is scoped to individual pages (not cross-page)
- Both search and replacement phrases must be exactly the same length
- No safety guardrails beyond length validation; user verifies manually

Public API
----------
    phrase_replace_pdf(input_path, output_path=None, phrase_replace_path=None) -> Path

Example
-------
    from pathlib import Path
    from bank_statement_anonymiser import phrase_replace_pdf

    out = phrase_replace_pdf(
        Path("anonymised_statement.pdf"),
        phrase_replace_path=Path("my_phrase_replace.toml"),
    )
"""

from __future__ import annotations

from pathlib import Path

import pikepdf

from bank_statement_anonymiser.anonymise import (
    _build_font_maps,
    _load_phrase_replace,
)
from bank_statement_anonymiser.logging_config import get_logger

logger = get_logger(__name__)

# Character operators in PDF content streams (these carry actual text)
_CHARACTER_OPS: frozenset[str] = frozenset({"Tj", "TJ"})

# Debug flag - set to True for verbose replacement logging
_DEBUG_REPLACEMENTS = False


def _replace_phrases_on_page(
    pike_page: pikepdf.Page,
    pike_doc: pikepdf.Pdf,
    phrase_rules: dict[str, str],
    forward_maps: dict[str, dict[int, str]],
    reverse_maps: dict[str, dict[str, int]],
) -> bool:
    """Replace character sequences on a single PDF page.

    Scans the page's content stream for sequences of characters matching the
    search phrases in phrase_rules, and replaces each character individually
    with the corresponding character from the replacement phrase.

    Algorithm:
    1. Get raw (uncompressed) content stream bytes
    2. Parse to identify Tj/TJ operators and their byte positions
    3. Decode operator bytes to text using font maps
    4. For each phrase rule, scan decoded text for matches
    5. When match found, directly modify the hex digits in raw stream at original positions
    6. Write modified stream back to page

    Args:
        pike_page: The pikepdf page to modify in-place.
        pike_doc: The pikepdf document (needed for make_stream).
        phrase_rules: Dict mapping search phrase -> replacement phrase.
                      Both phrases must be same length.
        forward_maps: Font encoding maps (glyph byte -> unicode char).
        reverse_maps: Reverse font encoding maps (unicode char -> glyph byte).

    Returns:
        True if any replacements were made, False otherwise.

    Raises:
        (Logged but not re-raised): If content stream cannot be parsed.
    """
    if not phrase_rules:
        return False

    try:
        # Get raw stream bytes (automatically decompressed by pikepdf)
        raw_stream = pike_page.obj["/Contents"].read_bytes()
        # Parse to get instruction structure
        instructions = list(pikepdf.parse_content_stream(pike_page))
    except (pikepdf.PdfError, AttributeError) as e:
        logger.warning(f"Failed to parse content stream for page: {e}")
        return False

    # Build character sequence with byte positions and hex positions in raw stream
    # (decoded_char, hex_pos, font_name)
    # hex_pos = position of the first hex character for this byte's value (2 chars per byte)
    char_sequence: list[tuple[str, int, str]] = []
    current_font = ""
    stream_search_pos = 0

    for instr_idx, (operands, operator) in enumerate(instructions):
        op_str = str(operator)

        # Track current font
        if op_str == "Tf" and operands:
            try:
                current_font = str(operands[0])
            except (TypeError, AttributeError):
                current_font = ""

        # Process character operators - find hex patterns in raw stream
        elif op_str in _CHARACTER_OPS and operands:
            try:
                if op_str == "Tj":
                    # Simple: just one string
                    raw_bytes = bytes(operands[0])
                    if raw_bytes:
                        hex_str = raw_bytes.hex().upper()
                        pattern = b"<" + hex_str.encode() + b">"

                        # Find this pattern in the raw stream
                        pattern_pos = raw_stream.find(pattern, stream_search_pos)
                        if pattern_pos >= 0:
                            hex_start = pattern_pos + 1  # Position after '<'
                            for byte_idx, raw_byte in enumerate(raw_bytes):
                                decoded_char = _decode_byte(raw_byte, current_font, forward_maps)
                                # Each byte is 2 hex characters
                                hex_pos = hex_start + (byte_idx * 2)
                                char_sequence.append((decoded_char, hex_pos, current_font))
                            stream_search_pos = pattern_pos + len(pattern)

                elif op_str == "TJ":
                    # Array of strings and spacing values
                    arr = operands[0]
                    for item in list(arr):  # type: ignore[arg-type]
                        if isinstance(item, pikepdf.String):
                            raw_bytes = bytes(item)
                            if raw_bytes:
                                hex_str = raw_bytes.hex().upper()
                                pattern = b"<" + hex_str.encode() + b">"

                                # Find this pattern in the raw stream
                                pattern_pos = raw_stream.find(pattern, stream_search_pos)
                                if pattern_pos >= 0:
                                    hex_start = pattern_pos + 1
                                    for byte_idx, raw_byte in enumerate(raw_bytes):
                                        decoded_char = _decode_byte(raw_byte, current_font, forward_maps)
                                        hex_pos = hex_start + (byte_idx * 2)
                                        char_sequence.append((decoded_char, hex_pos, current_font))
                                    stream_search_pos = pattern_pos + len(pattern)
            except (TypeError, AttributeError):
                pass

    if not char_sequence:
        return False

    # Try to match and replace
    replacements_made = False
    modified_stream = bytearray(raw_stream)

    for search_phrase, replacement_phrase in phrase_rules.items():
        # Scan for matching sequences
        pos = 0
        match_start = 0

        for char_idx in range(len(char_sequence)):
            decoded_char, hex_pos, font_name = char_sequence[char_idx]

            if decoded_char == search_phrase[pos]:
                # Character matches
                if pos == 0:
                    match_start = char_idx

                pos += 1

                if pos == len(search_phrase):
                    # Complete sequence matched!
                    match_end = char_idx + 1
                    matched_sequence = char_sequence[match_start:match_end]

                    if _apply_replacements_raw(
                        modified_stream,
                        matched_sequence,
                        replacement_phrase,
                        reverse_maps,
                        _DEBUG_REPLACEMENTS,
                    ):
                        replacements_made = True

                    # Reset for next match
                    pos = 0
            else:
                # Mismatch: try to reset
                if decoded_char == search_phrase[0]:
                    match_start = char_idx
                    pos = 1
                else:
                    pos = 0

    # Write back modified content stream
    if replacements_made:
        try:
            new_stream = pike_doc.make_stream(bytes(modified_stream))
            pike_page.obj["/Contents"] = new_stream
        except Exception as e:
            logger.warning(f"Failed to write content stream: {e}")
            return False

    return replacements_made


def _decode_byte(raw_byte: int, font_name: str, forward_maps: dict[str, dict[int, str]]) -> str:
    """Decode a single byte using font's ToUnicode map or Latin-1 fallback.

    Args:
        raw_byte: The raw byte value (0-255).
        font_name: The font resource name (e.g., '/F1').
        forward_maps: Dict mapping font_name -> {glyph_byte -> unicode_char}.

    Returns:
        Decoded unicode character, or empty string if not found.
    """
    fwd = forward_maps.get(font_name, {})
    if raw_byte in fwd:
        return fwd[raw_byte]

    # Fallback: try Latin-1
    try:
        return bytes([raw_byte]).decode("latin-1")
    except (UnicodeDecodeError, ValueError):
        return ""


def _apply_replacements_raw(
    modified_stream: bytearray,
    matched_sequence: list[tuple[str, int, str]],
    replacement_phrase: str,
    reverse_maps: dict[str, dict[str, int]],
    debug: bool = False,
) -> bool:
    """Apply character replacements to hex-encoded bytes in raw stream.

    Each byte is encoded as 2 hex characters in the PDF content stream
    (e.g., 0x42 as "42"). This function modifies those hex characters.

    Args:
        modified_stream: Mutable bytearray of the content stream.
        matched_sequence: List of (decoded_char, hex_pos, font_name) tuples
                         where hex_pos is the position of the first hex character.
        replacement_phrase: Phrase to replace with (same length as matched_sequence).
        reverse_maps: Font encoding reverse maps ({font_name -> {unicode_char -> glyph_byte}}).
        debug: Enable debug logging.

    Returns:
        True if replacements were applied successfully.
    """
    if len(matched_sequence) != len(replacement_phrase):
        logger.error(
            f"Mismatch in replacement application: "
            f"{len(matched_sequence)} matched chars vs {len(replacement_phrase)} replacement chars"
        )
        return False

    if debug:
        logger.debug(f"Applying replacement for '{replacement_phrase}' at {len(matched_sequence)} positions:")

    success_count = 0

    for rep_idx, (decoded_char, hex_pos, font_name) in enumerate(matched_sequence):
        replacement_char = replacement_phrase[rep_idx]

        # Look up the glyph byte for the replacement character
        rev = reverse_maps.get(font_name, {})
        if replacement_char in rev:
            replacement_byte = rev[replacement_char]
        else:
            # Fallback: try ASCII value (won't work for most PDFs but try anyway)
            try:
                replacement_byte = ord(replacement_char)
            except (TypeError, ValueError):
                logger.warning(
                    f"Cannot find replacement byte for '{replacement_char}' in font {font_name}; "
                    f"cannot apply replacement"
                )
                return False

        # Convert replacement byte to 2 hex characters (uppercase)
        hex_bytes = f"{replacement_byte:02X}".encode("ascii")

        # Modify the stream at this hex position
        try:
            # Get original hex characters
            original_hex = modified_stream[hex_pos : hex_pos + 2]
            # Replace them
            modified_stream[hex_pos : hex_pos + 2] = hex_bytes
            success_count += 1

            if debug:
                logger.debug(
                    f"  [{rep_idx}] hex_pos={hex_pos}: "
                    f"'{decoded_char}' ({original_hex.decode('ascii')}) -> '{replacement_char}' ({hex_bytes.decode('ascii')})"
                )
        except (IndexError, TypeError, UnicodeDecodeError) as e:
            logger.warning(f"Failed to modify hex at position {hex_pos}: {e}")
            return False

    return success_count == len(matched_sequence)



def phrase_replace_pdf(
    input_path: str | Path,
    output_path: str | Path | None = None,
    phrase_replace_path: Path | None = None,
) -> Path:
    """Replace character sequences in an already-anonymised PDF.

    Opens an anonymised PDF and applies character-by-character replacements
    based on rules from a phrase_replace config file. This function operates
    independently of the anonymisation pipeline and can be used to reverse or
    modify anonymisation outcomes.

    The function scans the PDF content stream for sequences of individual
    characters (ignoring non-character operators like Tm, TL, Td) and replaces
    matching sequences according to user-provided rules.

    Args:
        input_path: Path to already-anonymised PDF to process.
        output_path: Output path (default: phrase_replaced_<stem>.pdf next to input).
        phrase_replace_path: Path to user phrase_replace.toml config file.
            If not provided, uses defaults (likely empty, so no-op).

    Returns:
        Path to the modified PDF.

    Raises:
        FileNotFoundError: If input_path doesn't exist.
        ValueError: If phrase_replace_path is invalid or output_path cannot be written.

    Example:
        >>> from pathlib import Path
        >>> from bank_statement_anonymiser import phrase_replace_pdf
        >>>
        >>> # Replace "21a Uad" with "21st Sep" (character-by-character)
        >>> out = phrase_replace_pdf(
        ...     Path("anonymised.pdf"),
        ...     phrase_replace_path=Path("phrase_replace.toml")
        ... )
        >>> print(f"Modified PDF: {out}")
    """
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_path}")

    # Determine output path
    if output_path is None:
        output_path = input_path.parent / f"phrase_replaced_{input_path.stem}{input_path.suffix}"
    output_path = Path(output_path)

    # Load phrase replace config
    try:
        phrase_cfg = _load_phrase_replace(phrase_replace_path)
    except (FileNotFoundError, ValueError) as e:
        raise ValueError(f"Failed to load phrase_replace config: {e}") from e

    if not phrase_cfg.rules:
        logger.info("No phrase replacement rules loaded; copying input to output unchanged")
        try:
            output_path.write_bytes(input_path.read_bytes())
            return output_path
        except (OSError, PermissionError) as e:
            raise ValueError(f"Failed to copy input to output: {e}") from e

    # Process PDF
    try:
        pike_doc = pikepdf.open(input_path)
    except (OSError, pikepdf.PdfError) as e:
        raise ValueError(f"Failed to open input PDF: {e}") from e

    try:
        replacements_total = 0

        for page_num, pike_page in enumerate(pike_doc.pages, start=1):
            try:
                # Build font maps for this page (includes both forward and reverse maps)
                forward_maps, reverse_maps, _ = _build_font_maps(pike_page)

                if _replace_phrases_on_page(
                    pike_page,
                    pike_doc,
                    phrase_cfg.rules,
                    forward_maps,
                    reverse_maps,
                ):
                    replacements_total += 1
                    logger.debug(f"Made replacements on page {page_num}")
            except Exception as e:
                logger.warning(f"Error processing page {page_num}: {e}")
                continue

        # Write output PDF
        try:
            pike_doc.save(output_path)
            logger.info(
                f"Phrase replacement complete: {replacements_total} pages modified, "
                f"saved to {output_path}"
            )
        except (OSError, pikepdf.PdfError) as e:
            raise ValueError(f"Failed to write output PDF: {e}") from e

    finally:
        try:
            pike_doc.close()
        except Exception:
            pass

    return output_path
