# uk-bank-statement-anonymiser

> Anonymise UK bank statement PDFs by scrambling personal data while preserving layout.

[![PyPI version](https://badge.fury.io/py/uk-bank-statement-anonymiser.svg)](https://pypi.org/project/uk-bank-statement-anonymiser/)
[![CI](https://github.com/boscorat/uk-bank-statement-anonymiser/actions/workflows/test.yml/badge.svg)](https://github.com/boscorat/uk-bank-statement-anonymiser/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Why?

You need to share bank statements with your accountant, solicitor, or lender — but the PDF contains sensitive data: account numbers, sort codes, IBANs, card numbers, and transaction details.

This tool scrambles that data while keeping the PDF looking like a real bank statement. Your financial data never leaves your machine.

## Quick start

```bash
pip install uk-bank-statement-anonymiser
```

```python
from bank_statement_anonymiser import anonymise_pdf

anonymise_pdf("statement.pdf", "anonymised.pdf")
```

One function. One command. Done.

## Important: check before you share

This tool handles known patterns but **cannot guarantee that all personally identifiable information has been removed**. Bank statement PDFs may contain data in places this tool does not currently scan (e.g. embedded metadata, images, or unusual formatting).

- **You must review every anonymised PDF yourself before sharing it with any third party.** Verify that no account numbers, names, addresses, balances, or other sensitive data remain visible.
- **Do not attach PDFs — anonymised or otherwise — to GitHub issues or discussion threads.** Use text excerpts or screenshots with sensitive data redacted instead.

## What gets anonymised

| Data type | Method |
|-----------|--------|
| Sort codes | Scrambled to valid format |
| Account numbers | Replaced with random numbers |
| IBANs | Replaced with random IBANs |
| Card numbers | Replaced with random card numbers |
| Merchant names | Scrambled |
| All other text | Letters scrambled, layout preserved |

## Supported banks

- HSBC UK (current & savings)
- Natwest
- TSB (Spend & Save & credit card)
- Halifax

More banks can be added — see [Contributing](#development).

**Why these banks?** Each bank uses a different PDF encoding strategy. HSBC uses Latin-1, Natwest uses Identity-H CID fonts, and TSB uses custom ToUnicode CMaps. Other UK bank PDFs may work if they use one of the same approaches.

## Custom rules

By default, the library handles common patterns automatically. You can supplement with your own rules:

```python
anonymise_pdf(
    "statement.pdf",
    "output.pdf",
    always_anonymise_path="my_replacements.toml",
    never_anonymise_path="my_protected_phrases.toml",
)
```

- **`always_anonymise.toml`** — Force specific strings to known replacements:

  ```toml
  "40-37-28" = "00-00-00"
  "Jason Farrar" = "John Doe"
  ```

- **`never_anonymise.toml`** — Protect phrases from being scrambled:

  ```toml
  exclude = ["My Employer Ltd", "Salary Payment"]
  ```

User config files override system config on clashes. Both system and user `never_anonymise` lists are combined.

**Do not commit user config files to source control** — they may contain real account numbers or names.

## API reference

```python
def anonymise_pdf(
    input_path: str | Path,
    output_path: str | Path | None = None,
    always_anonymise_path: str | Path | None = None,
    never_anonymise_path: str | Path | None = None,
    debug: bool = False,
) -> Path
```

| Parameter | Description |
|---|---|
| `input_path` | Path to the input PDF |
| `output_path` | Output path. If omitted, writes `anonymised_<stem><suffix>` alongside the input |
| `always_anonymise_path` | User replacement rules (optional) |
| `never_anonymise_path` | User protected phrases (optional) |
| `debug` | Print diagnostic info to stdout (default `False`) |
| **Returns** | Absolute path to the output PDF |
| **Raises** | `FileNotFoundError` if `input_path` does not exist |

## How it works

1. **Identify sensitive data** — Detects sort codes, account numbers, IBANs, card numbers, and other patterns. Each gets a deterministic fake replacement so the same data is always replaced consistently across pages.

2. **Protect structural text** — Dates, payment type codes, bank URLs, and configured protected phrases are left unchanged.

3. **Scramble remaining text** — All other letters are replaced with random alternatives; digits and symbols stay intact. The PDF's layout, fonts, images, and line breaks are preserved.

All processing happens locally via [pikepdf](https://github.com/pikepdf/pikepdf). No network requests, no accounts, no data collection.

## CLI usage

```bash
pip install uk-bank-statement-anonymiser
anonymise-pdf statement.pdf
```

```bash
anonymise-pdf statement.pdf -o output.pdf
anonymise-pdf statement.pdf --always-anonymise rules.toml --never-anonymise protected.toml
```

## Contributing

The most valuable contribution is testing the anonymiser against real bank statements from your own accounts. Your PDFs never leave your machine — you only submit a review report.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow.

## Development

```bash
git clone https://github.com/boscorat/uk-bank-statement-anonymiser.git
cd uk-bank-statement-anonymiser
uv sync
uv run pytest
```

## License

MIT — see [LICENSE](LICENSE).
