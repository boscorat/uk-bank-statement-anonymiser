# uk-bank-statement-anonymiser

Anonymise UK bank statement PDFs by scrambling personal data while preserving the document's
visual structure and layout. All letters in transaction descriptions are replaced with random
alternatives; dates, payment codes, protected phrases, and numeric identifiers (sort codes,
account numbers, IBANs, card numbers) are handled deterministically so the anonymised output
remains internally consistent across pages.

## Supported statement types

- HSBC UK current account
- HSBC UK savings account
- Natwest current account
- TSB Spend & Save account
- TSB credit card

**Why only these banks?** The library supports these specific banks because each uses a different PDF encoding strategy. Other UK bank PDFs may work if they use one of the same approaches, but have not been tested.

The supported encoding types are:
- **HSBC** uses single-byte Latin-1 encoding (WinAnsiEncoding)
- **Natwest** uses multi-byte Identity-H CID fonts
- **TSB** uses custom ToUnicode CMap reencoding

For technical details on how these encodings are detected and handled, see [Technical design → Encoding strategies](#encoding-strategies).

## Requirements

- Python 3.14+
- [pikepdf](https://pikepdf.readthedocs.io/) (installed automatically)

## Installation

```bash
pip install uk-bank-statement-anonymiser
```

## Quick start

By default, the library automatically detects and anonymises dates, sort codes, account numbers, card numbers, and other sensitive patterns. For custom rules—to force specific replacements or protect additional phrases—see [User config files](#user-config-files) below.

```python
from bank_statement_anonymiser import anonymise_pdf

# Minimal — output written alongside input
anonymise_pdf("statement.pdf")
# Output: anonymised_statement.pdf (in the same directory as input)

# Explicit output path (recommended — avoids exposing the original filename)
anonymise_pdf("statement.pdf", "safe_output_name.pdf")
```

## User config files

The library ships two *system* config files (bundled in the package, committed to source
control) that cover common protected phrases and known numeric patterns:

| File | Purpose |
|---|---|
| `always_anonymise_system.toml` | Force specific strings to a known replacement value |
| `never_anonymise_system.toml` | Protect specific phrases from being scrambled |

You can supplement these with your own files passed as arguments to `anonymise_pdf`:

```python
anonymise_pdf(
    "statement.pdf",
    "output.pdf",
    always_anonymise_path="my_always_anonymise.toml",
    never_anonymise_path="my_never_anonymise.toml",
)
```

System config provides defaults; your custom config overrides or extends them. For `always_anonymise`: your rules win on any clash. For `never_anonymise`: both system and user lists are combined (union).

**User config files should not be committed to source control** — they will typically contain
real account numbers, sort codes, or names that you are trying to protect.

### `always_anonymise.toml` format

```toml
# Force exact string replacements before the scramble pass.
# User file wins over system file on a clash.

"40-37-28" = "00-00-00"
"12345678" = "00000000"
"Jason Farrar" = "John Doe"
```

### `never_anonymise.toml` format

```toml
# Phrases listed here are left exactly as-is during the scramble pass.
# Matching is case-insensitive and whitespace-insensitive.

exclude = [
    "My Bank",
    "My Employer Ltd",
]
```

### Example: Custom protection rules

If your bank statement includes regular suppliers, employers, or other names you want to keep readable, add them to your user `never_anonymise.toml`:

```toml
# my_never_anonymise.toml
exclude = [
    "ACME Corporation",
    "Salary Payment",
    "Rent Payment",
]
```

Then pass it to `anonymise_pdf`:

```python
anonymise_pdf(
    "statement.pdf",
    "output.pdf",
    never_anonymise_path="my_never_anonymise.toml",
)
```

The matched phrases will remain readable in the output PDF, while everything else is scrambled.

## API reference

### `anonymise_pdf`

```python
def anonymise_pdf(
    input_path: str | Path,
    output_path: str | Path | None = None,
    always_anonymise_path: str | Path | None = None,
    never_anonymise_path: str | Path | None = None,
    debug: bool = False,
) -> Path
```

Anonymises a single PDF and returns the path to the output file.

| Parameter | Description |
|---|---|
| `input_path` | Path to the input PDF |
| `output_path` | Path for the output PDF. If omitted, writes `anonymised_<stem><suffix>` in the same directory as the input |
| `always_anonymise_path` | Path to a user `always_anonymise.toml` (optional) |
| `never_anonymise_path` | Path to a user `never_anonymise.toml` (optional) |
| `debug` | When `True`, print diagnostic information about config loading, numeric ID detection, and per-page pair building to stdout (optional; default `False`) |
| **Returns** | **Absolute path to the output PDF file** |
| **Raises** | **FileNotFoundError** if `input_path` does not exist |

## Error handling

**FileNotFoundError**: Raised if `input_path` does not exist.

**Other errors**: PDF parsing or re-encoding failures are logged to stdout when `debug=True` but do not stop processing — the output PDF is written with any non-matching or un-reencoded fragments left unchanged.

When `debug=True`, diagnostic output includes:
- Config file loading status (system and user files)
- Numeric ID detection results (IBANs, sort codes, card numbers found)
- Per-page pair building details (count of always-anonymise, protected, and scramble pairs)

## How it works

The anonymiser works in three steps:

1. **Identify sensitive data** — Detects sort codes, account numbers, IBANs, card numbers, and other patterns defined in config. Each gets a deterministic fake replacement (e.g. `40-37-28` → `28-28-28` — last two digits repeated). This ensures the same data point is always replaced with the same fake value, even across multiple pages.

2. **Protect structural text** — Dates, payment type codes, bank URLs, and any phrases in your `never_anonymise` config are left unchanged. This preserves the document's readability and structure.

3. **Scramble remaining text** — All other letters are scrambled (e.g. `Barclays` → `Dqhyqbvd`), while digits and symbols stay intact. The PDF's layout, fonts, images, and line breaks remain unchanged.

This three-step approach ensures that the same sensitive data is replaced consistently across all pages, while non-sensitive text is randomized uniformly.

## Technical design

### Why content-stream parsing?

The library parses PDF content streams directly via `pikepdf.parse_content_stream()` rather than using pdfplumber or similar tools. This approach is essential because pdfplumber merges multiple `Tj` text operators into visual "words," which loses the fragment boundaries that the anonymiser relies on to match phrases like sort codes and account numbers. Direct content-stream parsing preserves the original PDF encoding structure, enabling accurate font detection and re-encoding of scrambled text back to valid PDF bytes.

### Encoding strategies

Different banks use different PDF text encodings. The library automatically detects and handles three encoding types. Latin-1 (WinAnsiEncoding) uses single-byte glyph codes where each byte from 0–255 maps to one character; HSBC statements use this encoding. ToUnicode CMaps define custom character-to-Unicode mappings embedded in the PDF font itself; TSB statements use this approach for special layout control. Identity-H CID fonts use multi-byte character IDs (CIDs) for complex encoding scenarios; Natwest 2025 statements employ this strategy with 2-byte big-endian CID sequences.

For each text fragment discovered in the content stream, the library: (1) decodes the raw bytes using the font's encoding (consulting the ToUnicode CMap if present, otherwise falling back to Latin-1), (2) applies the appropriate transformation (replacement, protection, or scrambling), and (3) re-encodes the result using the same encoding path, ensuring that replacement bytes are always valid for the target font.

### Per-page processing (three phases)

The three-step architecture described in "How it works" above operates as follows at the implementation level. **Phase 1 — Line-aware scan** walks through all text operators in the PDF content stream. A line accumulator tracks the current visual line and resets at `Td`, `TD`, `T*`, `Tm`, or `ET` operators; this enables phrase matching that spans multiple `Tj` operators rendered on the same line (critical for multi-word phrases like "My Employer Ltd"). Within each line, a sliding window tests each start position by extending rightward, joining decoded fragment texts, and comparing against user rules in `always_anonymise`, system and user rules in `never_anonymise`, and built-in patterns (dates, amounts, sort codes, payment codes). The first match wins; the start pointer advances past the matched span.

**Phase 2 — Build bytes pairs** iterates through all fragments discovered in Phase 1. For each fragment: if it matched an `always_anonymise` rule, the replacement text is distributed across the original fragment slots (filling to the original length, with the last slot absorbing overflow/underflow), creating a `(original_bytes, replacement_bytes)` pair. If the fragment is protected (matched `never_anonymise` or a built-in pattern), it is skipped. Otherwise, the fragment is scramblable: letters are replaced via a per-document scramble map, while digits and symbols remain unchanged, producing a `(original_bytes, scrambled_bytes)` pair.

**Phase 3 — Rewrite content stream** takes the pairs built in Phase 2 and performs a dictionary-based lookup: wherever the original byte sequence appears in the content stream, it is replaced with the corresponding replacement byte sequence. This final step applies all transformations simultaneously, ensuring deterministic and consistent output.

## Licence

MIT — see [LICENSE](LICENSE).
