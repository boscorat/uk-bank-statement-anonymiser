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

Other UK bank PDFs may work, but have not been tested.

## Requirements

- Python 3.14+
- [pikepdf](https://pikepdf.readthedocs.io/) (installed automatically)

## Installation

```bash
pip install uk-bank-statement-anonymiser
```

## Quick start

```python
from bank_statement_anonymiser import anonymise_pdf

# Minimal — output written alongside input as "anonymised_<original_name>.pdf"
anonymise_pdf("statement.pdf")

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

User entries are merged with system entries. On a clash in `always_anonymise`, the user file
wins. `never_anonymise` is a union of both files.

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
| `debug` | Print diagnostic information to stdout when `True` |

## How it works

1. **Numeric ID detection** — a document-level scan identifies sort codes, account numbers,
   IBANs, and card numbers. Each is replaced with a deterministic fake value
   (last two digits tiled across the full length, e.g. `40-37-28` → `28-28-28`).
   `always_anonymise` overrides take priority.

2. **Protected phrase detection** — fragments matching dates, payment type codes, URLs,
   numeric values, or entries in `never_anonymise` configs are marked as protected and
   left unchanged.

3. **Content stream rewrite** — pikepdf rewrites the PDF content streams directly,
   substituting scrambled bytes for original text bytes. Font encoding (Latin-1 and
   ToUnicode/CMap) is handled transparently, including subset-embedded fonts.

## Licence

MIT — see [LICENSE](LICENSE).
