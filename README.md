# uk-bank-statement-anonymiser

> Anonymise UK bank statement PDFs by scrambling personal data while preserving layout.

[![PyPI version](https://badge.fury.io/py/uk-bank-statement-anonymiser.svg)](https://pypi.org/project/uk-bank-statement-anonymiser/)
[![CI](https://github.com/boscorat/uk-bank-statement-anonymiser/actions/workflows/test.yml/badge.svg)](https://github.com/boscorat/uk-bank-statement-anonymiser/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Why?

You need to share bank statements with your accountant, solicitor, or lender — but the PDF contains sensitive data: account numbers, sort codes, IBANs, card numbers, and transaction details.

This tool scrambles that data while keeping the PDF looking like a real bank statement. Your financial data never leaves your machine.

## Quick start

**Using Python (API)**

```bash
pip install uk-bank-statement-anonymiser
```

```python
from bank_statement_anonymiser import anonymise_pdf

anonymise_pdf("statement.pdf", "anonymised.pdf")
```

**Using the command line**

~~~bash
anonymise-pdf statement.pdf
~~~

> Prefer [uv](https://docs.astral.sh/uv/getting-started/installation/)? See [Installation](#installation) for the uv workflow.

## Important: check before you share

This tool handles known patterns but **cannot guarantee that all personally identifiable information has been removed**. Bank statement PDFs may contain data in places this tool does not currently scan (e.g. embedded metadata, images, or unusual formatting).

- **You must review every anonymised PDF yourself before sharing it with any third party.** Verify that no account numbers, names, addresses, balances, or other sensitive data remain visible.
- **Do not attach PDFs — anonymised or otherwise — to GitHub issues, PRs, or discussion threads.** If anonymisation is failing, the statement will not be properly anonymised. Use text excerpts or screenshots with sensitive data redacted instead.
- **Do not paste log output, debug output, or console transcripts without checking them for PII.** These may contain account numbers, names, addresses, or other sensitive data. Redact any sensitive content before sharing.

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

![Anonymisation workflow](https://raw.githubusercontent.com/boscorat/uk-bank-statement-anonymiser/master/docs/diagrams/workflow-technical.svg)

1. **Identify sensitive data** — Detects sort codes, account numbers, IBANs, card numbers, and other patterns. Each gets a deterministic fake replacement so the same data is always replaced consistently across pages.

2. **Protect structural text** — Dates, payment type codes, bank URLs, and configured protected phrases are left unchanged.

3. **Scramble remaining text** — All other letters are replaced with random alternatives; digits and symbols stay intact. The PDF's layout, fonts, images, and line breaks are preserved.

All processing happens locally via [pikepdf](https://github.com/pikepdf/pikepdf). No network requests, no accounts, no data collection.

### Customisation

The anonymiser is designed to be extended for other bank formats (e.g. US, EU) or non-bank PDFs. Three areas control what gets anonymised:

![Customisation architecture](https://raw.githubusercontent.com/boscorat/uk-bank-statement-anonymiser/master/docs/diagrams/workflow-customization.svg)

1. **Pattern detection** — Regex patterns identify sort codes, account numbers, IBANs, card numbers, dates, amounts, and URLs. Add or modify patterns in the source to support new formats.

2. **System configs** — Default replacement rules (`always_anonymise_system.toml`) and protected phrases (`never_anonymise_system.toml`) ship with the package.

3. **User configs** — Optional TOML files passed via `--always-anonymise` / `--never-anonymise` (CLI) or `always_anonymise_path` / `never_anonymise_path` (Python API) to add custom rules. User replacements override system defaults; protected phrases are merged (union).

> **Regenerating diagrams:** Diagrams are authored in Mermaid (`.mmd` files in `docs/diagrams/`). To regenerate SVG/PNG, install [mermaid-cli](https://pypi.org/project/mermaid-cli/) (`uv add --group dev mermaid-cli`) and run `mmdc -i <input>.mmd -o <output>.svg`.

## Installation

### Option 1: uv (recommended)

If you have [uv](https://docs.astral.sh/uv/getting-started/installation/) installed, this is the simplest path — no virtual environment setup needed:

```bash
uv run anonymise-pdf statement.pdf
```

uv handles installation and environment isolation automatically. For the Python API:

```python
from bank_statement_anonymiser import anonymise_pdf
anonymise_pdf("statement.pdf", "anonymised.pdf")
```

### Option 2: pip + virtual environment

```bash
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows
pip install uk-bank-statement-anonymiser
anonymise-pdf statement.pdf
```

> **Note:** On Windows, use `.venv\Scripts\activate` instead. If you skip the virtual environment, `anonymise-pdf` may not be found on your PATH.

## CLI usage

```bash
anonymise-pdf statement.pdf
anonymise-pdf statement.pdf -o output.pdf
anonymise-pdf statement.pdf --always-anonymise rules.toml --never-anonymise protected.toml
```

| `-o`, `--output` | Output path (default: `anonymised_<stem><suffix>` alongside input) |
| `--never-anonymise` | TOML file with protected phrases |

See [Custom rules](#custom-rules) for TOML file format.

## Related projects

This library is used by other projects in the boscorat ecosystem:

- **[openstan](https://github.com/boscorat/openstan)** — Free, offline UK bank statement analyser. Parse, analyse, and export your statements to Excel, CSV, or JSON. Uses `uk-bank-statement-anonymiser` to redact statements for safe sharing. Website: [openstan.org](https://openstan.org)

- **[bank_statement_parser](https://github.com/boscorat/bank_statement_parser)** — Parse bank statement PDFs, extract structured transaction data, and persist results to Parquet or SQLite. Includes optional PDF anonymisation via `uk-bank-statement-anonymiser`.

## Contributing

The most valuable contribution is testing the anonymiser against real bank statements from your own accounts. Your PDFs never leave your machine — you only submit a review report.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow.

## Development (for contributors)

```bash
git clone https://github.com/boscorat/uk-bank-statement-anonymiser.git
cd uk-bank-statement-anonymiser
uv sync
uv run pytest
```

## License

MIT — see [LICENSE](LICENSE).
