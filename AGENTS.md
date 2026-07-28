# AGENTS.md — uk-bank-statement-anonymiser

## Quick setup
```bash
uv sync           # Install all dependencies (dev included)
uv run pytest     # Run all tests (508 tests)
uv run ruff check src tests  # Lint
```

## What this project does
A Python library that anonymises UK bank statement PDFs by scrambling personal data (sort codes, account numbers, IBANs, card numbers, transaction data, merchant names) while preserving PDF structure, layout, and fonts.

**Key distinction:** Exclusion-based approach. Starts with a completely scrambled PDF, then uses config files to specify what to force-replace (`always_anonymise`) and what to leave unchanged (`never_anonymise`).

## Architecture & entrypoints

**Public API:** `bank_statement_anonymiser.anonymise_pdf()` (in `src/bank_statement_anonymiser/__init__.py`)

**Core logic:** `src/bank_statement_anonymiser/anonymise.py` — contains the three-phase processing pipeline:
1. **Phase 1** — Line-aware scan pass (reads content stream, detects sensitive patterns, marks for protection/replacement).
   - **Line accumulation:** Fragments are accumulated into a "line" for phrase matching. `Tm` (Text Matrix) operators do NOT break the line unless the Y-coordinate changes by >2.0 units (handles word-by-word positioning).
2. **Phase 2** — Build byte pairs (maps original bytes to replacement bytes).
   - **Numeric ID strategy:** `_repeat_last_two` tiles the last two digits of a sort code/account/IBAN to fill the length. This ensures replacements are obviously fake but deterministic across pages/runs.
3. **Phase 3** — Rewrite content stream (dict lookup and substitute).
   - **Character Run Protection:** A pre-pass identifies `Tj` sequences that spell protected phrases (e.g., "BALANCE BROUGHT FORWARD") one character at a time. These are frozen before the main scramble pass.

**Key technical detail:** Uses `pikepdf.parse_content_stream()` to work on raw `Tj`/`TJ` operator byte strings, NOT `pdfplumber.extract_words()`. This avoids model mismatch where pdfplumber merges multiple operators into visual words, breaking scramble pair matching.

**Font encoding handling:** Supports multi-byte CID fonts (`Identity-H`) and single-byte fonts (Latin-1/WinAnsi).
- `/ToUnicode` CMap is parsed to build CID → Unicode maps.
- UTF-16-BE (with BOM) or Latin-1 fallbacks are used for CMap stream decoding.
- Scrambled chars are re-encoded back into the font's specific encoding.

## Testing structure
- **Markers:** `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.slow` (defined in `pyproject.toml`)
- **Fixtures:** `conftest.py` provides `mock_random_source` (seeded with 42), `simple_text_pdf`, `always_anonymise_config`, `never_anonymise_config`, `output_dir`.
- **Reproducibility:** The `reset_random_seed` fixture auto-runs before each test to ensure deterministic scrambling.

**Run a focused subset:**
```bash
uv run pytest tests/test_public_api.py -v              # Just public API tests (14 tests)
uv run pytest tests/ -k "test_pattern_detection" -v   # Just pattern detection
uv run pytest tests/ -m unit -v                        # Just unit tests
uv run pytest tests/test_font_encoding.py -v           # Font encoding tests
```

## Config files (TOML)
Located in `src/bank_statement_anonymiser/`:
- **System files** — committed; bundled as package resources.
  - `always_anonymise_system.toml` — default forced replacements.
  - `never_anonymise_system.toml` — default protected phrases.
- **User files** — .gitignored; passed via `always_anonymise_path`, `never_anonymise_path` args.
  - **Always Anonymise:** Flat `"original" = "replacement"` map. User wins on key clash.
  - **Never Anonymise:** `exclude = [...]` list. Union of system + user (all are protected).
  - **Normalisation:** Phrases are lowercased, internal whitespace collapsed, and trailing colons stripped before matching.

**Do NOT commit user config files** — they may contain real account numbers or names.

## Lint & type checking
```bash
uv run ruff check src tests   # Lint check only
ruff format src tests          # Format fix (may need uv run prefix)
```
- **Line length:** 140 chars (configured in `pyproject.toml`)
- **Target Python:** 3.14 (configured in `pyproject.toml`)
- **Unfixable violations:** F401 (unused imports) — must be fixed manually

**No type checker configured** — code is typed but no mypy/pyright enforcement.

## Build & release
- **Build tool:** `uv_build` backend (via uv)
- **Package name:** `uk-bank-statement-anonymiser` (PyPI)
- **Module name:** `bank_statement_anonymiser` (import)
- **Version:** Managed via `__version__` in `__init__.py` (generated from package metadata)
- **CI:** GitHub Actions (`.github/workflows/test.yml`, `release.yml`)
  - Tests run on Python 3.14 only
  - Lint runs before tests; coverage report generated (but non-blocking)

## Common patterns

**Pattern detection (built-in):** Sort codes, account numbers, IBANs, card numbers, amounts, dates, payment codes. See `anonymise.py` for regex patterns.

**Deterministic output:** Same input + same config = identical output (random source seeded).

**Output naming:** Default is `anonymised_<stem><suffix>` alongside input (e.g., `statement.pdf` → `anonymised_statement.pdf`).

**Debug mode:** Pass `debug=True` to `anonymise_pdf()` to print diagnostic info to stdout.

## Gotchas for agents

1. **Font encoding is critical.** Different banks use different PDF encoding strategies (Latin-1, ToUnicode CMap, Identity-H). Tests exist for each; check `test_font_encoding.py` when adding new bank support.

2. **Do not use pdfplumber.extract_words().** This is explicitly avoided; use `pikepdf` and work at the content-stream operator level.

3. **Test fixtures generate synthetic PDFs.** They do not depend on external sample files; all test data is created by `simple_text_pdf` fixture.

4. **Markers exist but are optional.** The CI runs all tests; use markers to filter locally.

5. **Config file merging is asymmetric.** User always_anonymise overrides system keys; never_anonymise is unioned.

6. **Scramble determinism depends on mocked random.** If you modify random generation, update `conftest.py` mock.
