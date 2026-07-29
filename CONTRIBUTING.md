# Contributing to uk-bank-statement-anonymiser

Thanks for your interest in contributing! The most valuable contribution you can make is testing the anonymiser against real bank statements from your own accounts.

Your bank statement PDFs **must stay on your machine** — never attach them to issues, PRs, or discussions. If anonymisation is failing, the statement will not be properly anonymised. You only submit a review report describing what you observed.

Log output, debug output, and console transcripts may contain personally identifiable information (account numbers, names, addresses, etc.). Check contents before sharing, or use text excerpts with sensitive data redacted.

## Quick start

```bash
git clone https://github.com/boscorat/uk-bank-statement-anonymiser.git
cd uk-bank-statement-anonymiser
uv sync
```

## Test a bank statement

1. **Anonymise your statement:**

   ```bash
   uv run anonymise-pdf statement.pdf
   ```

   This creates `anonymised_statement.pdf` alongside the original. The original is untouched.

   Optional flags:

   | Flag | Purpose |
   |------|---------|
   | `-o output.pdf` | Custom output path |
   | `--always-anonymise rules.toml` | Force specific replacements |
   | `--never-anonymise rules.toml` | Protect phrases from scrambling |
   | `--debug` | Print diagnostic info |

2. **Open the anonymised PDF and visually inspect it.** Check that personal data is scrambled, the layout is preserved, and transaction values are intact.

3. **Fill in the review template:**

   ```bash
   cp reviews/TEMPLATE.md "reviews/<bank>-<account-type>-<YYYY-MM>-<your-username>.md"
   ```

   For example: `reviews/hsbc-advance-current-2024-01-jasonfarrar.md`

4. **Submit a PR** with your review file. A maintainer will review it and may ask for follow-up.

## What to check

The review template includes a full checklist, but the key items are:

- Account numbers, sort codes, IBANs, and card numbers are all anonymised
- Names and addresses are anonymised
- Transaction values and types are **not** anonymised
- No personally identifiable information remains visible

## Config files (optional)

If your bank statement has specific strings that need forced replacement or protection, create local config files:

```toml
# always_anonymise.toml — force specific replacements
"Your Name" = "John Doe"
"12345678" = "00000000"
```

```toml
# never_anonymise.toml — protect phrases from scrambling
exclude = ["Your Employer Ltd", "Salary Payment"]
```

Pass them via `--always-anonymise` and `--never-anonymise` flags.

**Do not commit these files** — they may contain real personal data.

## Running the test suite

```bash
uv run pytest          # all tests
uv run ruff check src tests  # lint
```

## Code style

- Line length: 140 characters
- No type checker configured, but the codebase is typed
- Follow existing patterns and conventions
