# Debugging

uk-bank-statement-anonymiser provides comprehensive logging for diagnosing issues with PDF anonymisation.

## Enable verbose logging

By default, the library logs at INFO level (milestones only). To enable DEBUG-level logging:

### Python API

```python
from bank_statement_anonymiser import anonymise_pdf, set_verbosity

# Enable debug-level logging before calling anonymise_pdf
set_verbosity("verbose")

# Process your PDF
result = anonymise_pdf("statement.pdf", "anonymised.pdf")
```

### Command line

The `--debug` flag is deprecated since v1.0.0. Use Python's `logging` module instead:

```bash
python -c "
import logging
import sys
from bank_statement_anonymiser import anonymise_pdf, set_verbosity

# Configure console logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    stream=sys.stdout
)

# Enable verbose logging
set_verbosity('verbose')

# Run anonymisation
anonymise_pdf('statement.pdf')
"
```

Or configure logging in your application and call:

```python
from bank_statement_anonymiser import get_logger, set_verbosity

set_verbosity("verbose")
logger = get_logger("bank_statement_anonymiser.anonymise")
```

## What debug output tells you

Debug logging includes:

- **Config loading**: How many replacement rules and protected phrases are loaded from system and user config files
- **Numeric ID detection**: Sort codes, account numbers, IBANs, card numbers detected in the document
- **Per-page processing**: Font information, number of scramble pairs built for each page
- **Pair details** (first 20 per page): Original byte sequences and their replacements

Example debug output:

```
2026-09-30 14:23:45,123 | DEBUG    | bank_statement_anonymiser.anonymise | always_anonymise: 5 rule(s): [...]
2026-09-30 14:23:46,456 | DEBUG    | bank_statement_anonymiser.anonymise | never_anonymise: 12 phrase(s)
2026-09-30 14:23:47,789 | DEBUG    | bank_statement_anonymiser.anonymise | pre-pass collected 342 fragment(s), 8934 chars total
2026-09-30 14:23:48,234 | DEBUG    | bank_statement_anonymiser.anonymise | numeric_id_map (8 entry/entries):
2026-09-30 14:23:48,235 | DEBUG    | bank_statement_anonymiser.anonymise |   '40 37 28' -> '00 00 00'
2026-09-30 14:23:48,456 | DEBUG    | bank_statement_anonymiser.anonymise | page 1: fonts=['F1', 'F2'], bold=['F1']
2026-09-30 14:23:48,789 | DEBUG    | bank_statement_anonymiser.anonymise | page 1: 523 pair(s) built
2026-09-30 14:23:48,790 | DEBUG    | bank_statement_anonymiser.anonymise |   pair: b'4' -> b'0'
2026-09-30 14:23:48,790 | DEBUG    | bank_statement_anonymiser.anonymise |   pair: b'0' -> b'0'
...
```

## File logging

To capture logs to a file for later analysis:

```python
import logging
from pathlib import Path
from bank_statement_anonymiser import anonymise_pdf, set_verbosity

# Set up rotating file handler
log_path = Path.home() / "anonymiser_debug.log"
handler = logging.handlers.RotatingFileHandler(
    log_path,
    maxBytes=10485760,  # 10 MB
    backupCount=5
)
handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"))

# Add to library logger
logging.getLogger("bank_statement_anonymiser").addHandler(handler)

# Enable verbose logging
set_verbosity("verbose")

# Process PDFs — logs will go to file
anonymise_pdf("statement.pdf", "anonymised.pdf")
```

## Common debug scenarios

### "Font not found" errors

Debug output shows the fonts used in each PDF page:

```
page 1: fonts=['F1', 'F2'], bold=['F1']
```

If a font is missing from this list, the PDF may use a non-standard encoding. Check `test_font_encoding.py` for examples of different encoding strategies.

### Text extraction mismatch

If debug output shows fragments that don't match your PDF visually:

```
all_text (first 500 chars): 'ACCOUNT NUMBER 12 34 56 78 BALANCE ...'
```

This indicates the PDF uses unusual text positioning or encoding. The library accumulates fragments into "lines" based on PDF operators (`Td`, `Tm`, etc.); if fragments appear disconnected in the debug output, review the PDF's content stream directly with a tool like `pdfplumber.open().pages[0].extract_text()`.

### Pattern detection failures

Debug output shows detected numeric IDs:

```
numeric_id_map (8 entry/entries):
  '40 37 28' -> '00 00 00'
  '12 34 56 78' -> '11 11 11 11'
```

If a sensitive value isn't being anonymised, it may not match any built-in pattern. Check the regex patterns in `anonymise.py` and consider adding a custom rule via `always_anonymise.toml`.

## Privacy considerations

**Important:** Debug output may contain sensitive values from your PDF and config files. Before sharing debug logs with support:

1. Redact account numbers, sort codes, names, and addresses
2. Redact the `all_text` field (first 500 chars of document content)
3. Keep `numeric_id_map` entries redacted if they contain real values from your PDF

Example safe log excerpt:

```
always_anonymise: 5 rule(s): ['REDACTED_RULE_1', 'REDACTED_RULE_2', ...]
never_anonymise: 12 phrase(s)
pre-pass collected 342 fragment(s), 8934 chars total
numeric_id_map (8 entry/entries): [REDACTED]
page 1: fonts=['F1', 'F2'], bold=['F1']
page 1: 523 pair(s) built
```

## Reporting issues

If you believe the anonymiser is not correctly anonymising your PDF, please:

1. Enable verbose logging and capture the output
2. Test with a synthetic PDF (not your real statement)
3. Redact all sensitive values before sharing
4. [Open an issue](https://github.com/boscorat/uk-bank-statement-anonymiser/issues) with:
   - Redacted debug log output
   - Description of what was not anonymised
   - Your bank name (if publicly known)
   - Python version
