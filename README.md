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

By default, the library automatically detects and anonymises dates, sort codes, account numbers, card numbers, and other sensitive patterns. For custom rules—to force specific replacements or protect additional phrases—see [User config files](#user-config-files) below.

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
| **Returns** | **Path to the output PDF file** |

## How it works

The anonymiser works in three steps:

1. **Identify sensitive data** — Detects sort codes, account numbers, IBANs, card numbers, and other patterns defined in config. Each gets a deterministic fake replacement (e.g. `40-37-28` → `28-28-28` — last two digits repeated). This ensures the same data point is always replaced with the same fake value, even across multiple pages.

2. **Protect structural text** — Dates, payment type codes, bank URLs, and any phrases in your `never_anonymise` config are left unchanged. This preserves the document's readability and structure.

3. **Scramble remaining text** — All other letters are scrambled (e.g. `Barclays` → `Dqhyqbvd`), while digits and symbols stay intact. The PDF's layout, fonts, images, and line breaks remain unchanged.

## Licence

MIT — see [LICENSE](LICENSE).
