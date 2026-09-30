# Troubleshooting

This guide covers common issues and solutions when using uk-bank-statement-anonymiser.

## Text not being anonymised

### Cause: Pattern not recognized

**Symptoms:** Account numbers, sort codes, or other sensitive data remain visible in the anonymised PDF.

**Solution:**

1. Enable debug logging:
   ```python
   from bank_statement_anonymiser import set_verbosity
   set_verbosity("verbose")
   ```

2. Look for the value in the debug output `numeric_id_map`:
   ```
   numeric_id_map (8 entry/entries):
     '40 37 28' -> '00 00 00'
   ```

3. If your value is missing, it doesn't match any built-in pattern. Add it to `always_anonymise.toml`:
   ```toml
   "40-37-28" = "00-00-00"
   "Your Name" = "John Doe"
   ```

4. Re-run anonymisation with the custom config:
   ```python
   anonymise_pdf(
       "statement.pdf",
       always_anonymise_path="always_anonymise.toml"
   )
   ```

### Cause: Custom rule not matching

**Symptoms:** You added a rule to `always_anonymise.toml`, but it's still not being replaced.

**Solution:**

The library normalises both config entries and PDF text for matching:
- All text is lowercased
- All colons (`:`) are removed
- All whitespace (spaces, tabs, newlines) is removed

So these are all equivalent and will match the same patterns:

```toml
"ACCOUNT NUMBER" = "ACCT NUMB"
"Account Number" = "Acct Numb"
"Account: Number" = "Acct: Numb"
"account number" = "acct numb"
```

If your rule still isn't matching:

1. Add debug logging to see the normalised text:
   ```python
   from bank_statement_anonymiser import set_verbosity
   set_verbosity("verbose")
   ```

2. Look for `all_text (first 500 chars):` in the debug output
3. Verify that your normalised rule appears in that text

### Cause: Text protected by `never_anonymise.toml`

**Symptoms:** A specific phrase is not being anonymised even though you didn't add it to `never_anonymise.toml`.

**Solution:**

Check the system `never_anonymise_system.toml` bundled with the library. Common protected phrases include:

- "Balance Brought Forward" / "Balance Carried Forward"
- "Payments" / "Withdrawals" / "Deposits"
- Bank names and URLs
- Payment type codes (e.g., "FASTER PAYMENTS", "DIRECT DEBIT")

If you want to anonymise one of these phrases:

1. Create a user `never_anonymise.toml` that removes it:
   ```toml
   exclude = []
   ```

2. Pass it to `anonymise_pdf()`:
   ```python
   anonymise_pdf(
       "statement.pdf",
       never_anonymise_path="never_anonymise.toml"
   )
   ```

This overrides the system defaults for protected phrases.

---

## "Font not found" or encoding errors

### Cause: Unsupported PDF encoding

**Symptoms:** Error message contains "Font" or "encoding", or output PDF is corrupted/unreadable.

**Solution:**

uk-bank-statement-anonymiser supports:

- **Latin-1 (WinAnsiEncoding)** — HSBC, Barclays
- **Identity-H CID fonts** — Natwest, some other banks
- **ToUnicode CMaps** — TSB, custom-encoded PDFs

Debug output shows which fonts are detected:

```
page 1: fonts=['F1', 'F2'], bold=['F1']
```

If the PDF uses a different encoding strategy:

1. Enable debug logging to see encoding details
2. [Open an issue](https://github.com/boscorat/uk-bank-statement-anonymiser/issues) with:
   - Bank name
   - Debug output showing fonts
   - Redacted sample PDF (optional, if safe to share)

The library can likely be extended to support your bank.

---

## Anonymised PDF looks wrong

### Cause: Excessive scrambling / Over-aggressive anonymisation

**Symptoms:** Important text (merchant names, dates) is scrambled when it shouldn't be.

**Solution:**

Use `retain_descriptions=True` to keep transaction descriptions readable:

```python
anonymise_pdf(
    "statement.pdf",
    "anonymised.pdf",
    always_anonymise_path="always_anonymise.toml",
    retain_descriptions=True,
)
```

This disables default letter-scrambling, so only `always_anonymise` replacements and numeric IDs are applied. Merchant names, descriptions, and other free text remain untouched.

**Warning:** `retain_descriptions` requires a user `always_anonymise.toml` to replace sensitive names and addresses — otherwise they would remain un-anonymised.

### Cause: Missing text in anonymised output

**Symptoms:** Some text from the original PDF is completely missing in the anonymised version.

**Solution:**

This is rare. Debug output shows all fragments collected:

```
pre-pass collected 342 fragment(s), 8934 chars total
```

If text is missing:

1. Compare the original and anonymised PDFs visually
2. Enable debug logging and check `all_text (first 500 chars):`
3. Verify that missing text appears in the original
4. [Report the issue](https://github.com/boscorat/uk-bank-statement-anonymiser/issues) with:
   - Redacted debug output
   - Description of missing text
   - Bank name

---

## Performance issues

### Cause: Large PDF (100+ pages)

**Symptoms:** Anonymisation takes > 30 seconds for a multi-page statement.

**Solution:**

This is expected for large PDFs. The library:

1. Collects all text from all pages (pre-pass)
2. Detects numeric IDs consistently across pages
3. Processes each page sequentially

To profile performance:

```python
import time
from bank_statement_anonymiser import anonymise_pdf, set_verbosity

set_verbosity("verbose")

start = time.time()
anonymise_pdf("large_statement.pdf")
elapsed = time.time() - start

print(f"Anonymisation took {elapsed:.1f} seconds")
```

For **very large PDFs** (200+ pages), consider:

1. Splitting the PDF into smaller chunks
2. Processing in parallel
3. Reporting performance concerns as a GitHub issue

---

## Config file issues

### Cause: Invalid TOML syntax

**Symptoms:** Error message mentions TOML parsing or file format.

**Solution:**

Ensure your config files follow TOML syntax:

**always_anonymise.toml:**
```toml
# Comment
"original value" = "replacement"
"another original" = "another replacement"
```

**never_anonymise.toml:**
```toml
exclude = [
    "Protected phrase 1",
    "Protected phrase 2",
]
```

Common mistakes:
- Forgetting quotes around keys/values
- Using `=` instead of `=` (different Unicode)
- Mismatched brackets `[` vs `]`

### Cause: User config not being loaded

**Symptoms:** You pass `always_anonymise_path` or `never_anonymise_path`, but the file isn't being used.

**Solution:**

1. Verify file exists:
   ```python
   from pathlib import Path
   config_path = Path("always_anonymise.toml")
   assert config_path.exists(), f"File not found: {config_path}"
   ```

2. Use absolute paths to avoid relative path issues:
   ```python
   from pathlib import Path
   anonymise_pdf(
       "statement.pdf",
       always_anonymise_path=Path.home() / "always_anonymise.toml"
   )
   ```

3. Check debug output to confirm config is loaded:
   ```
   always_anonymise: 5 rule(s): [...]
   never_anonymise: 12 phrase(s)
   ```

---

## Privacy & security concerns

### General warning: Always review the anonymised PDF

**No anonymisation tool can guarantee 100% privacy.** Bank statement PDFs may contain:

- Embedded metadata (PDFs can contain creation date, author, modification history)
- Watermarks or embedded images
- Unusual formatting that the tool doesn't recognize
- Sensitive data in footers, headers, or page margins

**Always manually review every anonymised PDF before sharing it.** Look for:

1. Account numbers, sort codes, IBANs
2. Names, addresses, phone numbers
3. Balances and transaction amounts
4. Card numbers
5. Merchant details (if anonymising)

If sensitive data remains visible, [report it as an issue](https://github.com/boscorat/uk-bank-statement-anonymiser/issues) with redacted details (see [Debugging > Privacy considerations](debugging.md#privacy-considerations)).

### Debug output may contain sensitive data

When you enable verbose logging, debug output may include:

- Config file contents (which may include real names/numbers if misused)
- Text fragments from your PDF (first 500 characters)
- Numeric ID mappings

**Do not share debug logs without redacting sensitive values.** See [Debugging > Privacy considerations](debugging.md#privacy-considerations) for guidance.

---

## Getting help

If your issue is not covered here:

1. [Search existing issues](https://github.com/boscorat/uk-bank-statement-anonymiser/issues)
2. Enable verbose logging and capture output (redact sensitive data)
3. [Open a new issue](https://github.com/boscorat/uk-bank-statement-anonymiser/issues/new) with:
   - Python version
   - Library version (`python -c "import bank_statement_anonymiser; print(bank_statement_anonymiser.__version__)"`)
   - Bank name
   - Redacted debug output
   - Description of the problem
