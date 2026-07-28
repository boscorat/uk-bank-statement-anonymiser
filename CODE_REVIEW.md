# Comprehensive Code Review: uk-bank-statement-anonymiser

## Executive Summary
The repository demonstrates solid architecture with a three-phase processing pipeline for PDF anonymization. All 508 tests pass successfully. However, there are several issues across quality, correctness, and maintainability categories that warrant attention.

---

## 1. CODE QUALITY & CORRECTNESS

### 1.1 Blind Exception Catching (HIGH)
**Files:** `anonymise.py`, `_shared.py`
**Lines:** Multiple (e.g., 285, 524, 536, 545, 557, 811, 826, 840, 849, 861, 1106, 1130, 1157, 1192, 1315, 1319)
**Severity:** HIGH
**Issue:** Excessive use of `except Exception:` without specificity silently swallows critical errors. This violates the principle of explicit exception handling and makes debugging PDF corruption or encoding issues extremely difficult.

**Example (line 811-812):**
```python
try:
    instructions = list(pikepdf.parse_content_stream(pike_page))
except Exception:
    return []  # Silent failure — user never knows PDF parse failed
```

**Impact:** 
- A malformed PDF will be silently processed, returning empty results with no diagnostic output
- Hard to distinguish between "no text in page" and "PDF parsing failed"
- Users cannot troubleshoot PDF compatibility issues

**Suggested Fix:**
```python
try:
    instructions = list(pikepdf.parse_content_stream(pike_page))
except (pikepdf.PdfError, ValueError, KeyError) as e:
    if debug:
        print(f"[DEBUG] Warning: Failed to parse content stream: {e}")
    return []
```

**Priority:** HIGH — This affects all pages with any encoding issue

---

### 1.2 Type Annotation Inconsistencies (MEDIUM)
**File:** `anonymise.py`
**Lines:** 291-292, 364, 501, 614, 768, 1138, 1150
**Severity:** MEDIUM
**Issue:** Unnecessary string quotes in forward references. PEP 563 (`from __future__ import annotations`) is already imported, making string quotes redundant.

**Examples:**
```python
# Line 291-292: Should not quote
font_encodings: dict[str, "_FontEncoding"] | None = None,

# Line 768: Should not quote
font_encodings: dict[str, "_FontEncoding"],

# Line 1138: Should not quote
) -> tuple[dict[str, "_FontEncoding"], dict[str, dict[str, int]], frozenset[str]]:
```

**Suggested Fix:** Remove quotes:
```python
font_encodings: dict[str, _FontEncoding] | None = None
```

**Priority:** MEDIUM — Code style/linting issue, all tests pass regardless

---

### 1.3 Resource Cleanup Protection (MEDIUM)
**File:** `anonymise.py`
**Lines:** 1263-1331
**Severity:** MEDIUM
**Issue:** While the code has a `try/finally` block (line 1264-1331), there's no guarantee the PDF file handle is released if an exception occurs during iteration through pages or if `pikepdf.open()` fails.

**Current Code:**
```python
pike_doc = pikepdf.open(str(input_path))
try:
    # ... processing ...
    pike_doc.save(str(output_path), compress_streams=True)
finally:
    pike_doc.close()
```

**Potential Issue:** If `pikepdf.save()` fails and raises an exception, the `close()` is still called (good), but no error context is preserved.

**Suggested Fix:**
```python
try:
    pike_doc = pikepdf.open(str(input_path))
except (FileNotFoundError, pikepdf.PdfError) as e:
    raise ValueError(f"Failed to open PDF '{input_path}': {e}") from e

try:
    # ... processing ...
    pike_doc.save(str(output_path), compress_streams=True)
except Exception as e:
    raise ValueError(f"Failed to anonymise or save PDF: {e}") from e
finally:
    pike_doc.close()
```

**Priority:** MEDIUM — Current implementation is safe but error messages could be clearer

---

### 1.4 Unused Imports and Variables (LOW)
**Files:** `conftest.py`, `test_content_stream_processing.py`, `test_font_encoding.py`, `test_pattern_detection.py`, `test_pdf_structure_preservation.py`, `test_text_transformations.py`
**Severity:** LOW
**Issue:** Ruff reports 112 lint violations including:
- `tempfile` imported but unused (conftest.py:13)
- `string` imported but unused (test_text_transformations.py:16)
- `_Fragment` imported but unused (test_content_stream_processing.py:38)
- Multiple unused imports in test files

**Suggested Fix:** Run `ruff check --fix` to auto-remove unused imports.

**Priority:** LOW — Hygiene issue, no functional impact

---

## 2. LOGIC ISSUES

### 2.1 Off-by-One Possibility in Tm Threshold Check (MEDIUM)
**File:** `anonymise.py`
**Lines:** 832-841
**Severity:** MEDIUM
**Issue:** The logic uses `> _TM_Y_THRESHOLD` (line 837) to detect line breaks, but the threshold is hardcoded to 2.0 PDF units. Depending on how TSB or other banks render text, a y-coordinate change of exactly 2.0 could be mishandled.

**Current Code:**
```python
_TM_Y_THRESHOLD: float = 2.0

if _last_tm_y is None or abs(ty - _last_tm_y) > _TM_Y_THRESHOLD:
    line_ends.append(len(indexed_fragments))
    _last_tm_y = ty
```

**Edge Case:** If TSB renders words with `Tm` y-coordinates that differ by exactly 2.0, the comparison `> 2.0` will NOT trigger a line break, causing words on different visual lines to be accumulated together and matched as multi-word phrases.

**Suggested Fix:**
```python
_TM_Y_THRESHOLD: float = 2.0

if _last_tm_y is None or abs(ty - _last_tm_y) >= _TM_Y_THRESHOLD:  # Use >= instead of >
    line_ends.append(len(indexed_fragments))
    _last_tm_y = ty
```

**Priority:** MEDIUM — Affects line accumulation, which is critical for multi-word phrase matching. No tests currently verify this edge case.

---

### 2.2 IBAN Tail Composition Logic (LOW)
**File:** `_shared.py`
**Lines:** 424-433
**Severity:** LOW
**Issue:** The logic to compose a 14-digit IBAN tail from cached 6-digit + 8-digit parts is correct, but it relies on strict key lookup. If either the sort code or account number was never detected (e.g., they appear after the IBAN), the composition fails gracefully and falls back to `_repeat_last_two`, which is correct.

**Current Code:**
```python
if len(raw) == 14:
    sort_part = raw[:6]
    acct_part = raw[6:]
    sort_scrambled = raw_to_scrambled.get(sort_part) or user_overrides.get(sort_part)
    acct_scrambled = raw_to_scrambled.get(acct_part) or user_overrides.get(acct_part)
    if sort_scrambled is not None and acct_scrambled is not None:
        composed = sort_scrambled + acct_scrambled
        raw_to_scrambled[raw] = composed
        return composed
```

**Observation:** This is correct but the comment in `_shared.py` (line 227-231) states that patterns must come before IBAN processing. The actual order in `_NUMERIC_ID_PATTERNS` tuple (lines 232-242) does respect this, so no bug here, but it's fragile.

**Suggested Fix:** Add a runtime assertion or test that verifies pattern ordering:
```python
# In _detect_numeric_ids, after the function definition:
_SORT_ACCT_IDX = _NUMERIC_ID_PATTERNS.index(_SORT_ACCT_RE)
_IBAN_FULL_IDX = _NUMERIC_ID_PATTERNS.index(_IBAN_FULL_RE)
assert _SORT_ACCT_IDX < _IBAN_FULL_IDX, "Pattern order violation: SORT_ACCT must come before IBAN"
```

**Priority:** LOW — Current implementation is correct; this is defensive programming.

---

### 2.3 Normalisation Phrase Edge Case (LOW)
**File:** `anonymise.py`
**Lines:** 176-184
**Severity:** LOW
**Issue:** The `_normalise_phrase()` function strips trailing colons before stripping whitespace. This means a phrase like `"Account :"` becomes `"Account"` (correct), but `"  Account Number  :"` becomes `"account:number"` (unexpected).

**Current Implementation:**
```python
def _normalise_phrase(text: str) -> str:
    t = text.strip().rstrip(":")
    return re.sub(r"\s+", "", t).lower()
```

**Problem:** 
- Input: `"  Account  :  Number  :"`
- After `strip()`: `"Account  :  Number  :"`
- After `rstrip(":")`: `"Account  :  Number"` (only trailing colon removed)
- After `re.sub()`: `"account:number"` (internal colons preserved)

If config has `"Account : Number"` it won't match `"Account  :  Number  :"` in the PDF.

**Suggested Fix:**
```python
def _normalise_phrase(text: str) -> str:
    t = text.strip()
    # Remove all colons (not just trailing) to handle internal structure
    t = t.replace(":", "")
    return re.sub(r"\s+", "", t).lower()
```

**Priority:** LOW — Edge case that hasn't manifested in testing, but could affect config matching for complex phrases.

---

### 2.4 Font Encoding Detection Asymmetry (MEDIUM)
**File:** `anonymise.py`
**Lines:** 341-357, 668-756
**Severity:** MEDIUM
**Issue:** The code has two parallel paths: `_is_identity_h_font()` detection and font-aware scrambling. However, the scrambling fallback (_scramble_text) doesn't validate that the font is actually Identity-H capable.

**Current Code:**
```python
def _is_identity_h_font(f: "pikepdf.Dictionary") -> bool:
    encoding = f.get("/Encoding")
    if encoding is None:
        return False
    encoding_str = str(encoding)
    return encoding_str == "/Identity-H" or encoding_str == "Identity-H"
```

**Issue:** The check is fragile. If a font's `/Encoding` field is stored differently (e.g., as a name object `/Identity-H` vs. a string `Identity-H`), the check might fail silently. Also, no test case verifies this detection against real bank PDFs.

**Suggested Fix:**
```python
def _is_identity_h_font(f: "pikepdf.Dictionary") -> bool:
    try:
        encoding = f.get("/Encoding")
        if encoding is None:
            return False
        encoding_str = str(encoding).strip("/")
        return encoding_str.upper() == "IDENTITY-H"
    except Exception:
        return False  # Safer fallback
```

**Priority:** MEDIUM — Affects multi-byte font support; failures would be silent in current code.

---

## 3. PERFORMANCE & SCALABILITY

### 3.1 Repeated Dictionary Key Iterations (LOW)
**File:** `anonymise.py`
**Lines:** 1109, 1160
**Severity:** LOW
**Issue:** Code uses `.keys()` explicitly in loops, which is redundant in Python 3.7+.

**Current Code:**
```python
for fname in font_dict.keys():
    try:
        f = font_dict[fname]
```

**Suggested Fix:**
```python
for fname in font_dict:
    try:
        f = font_dict[fname]
```

**Priority:** LOW — Micro-optimization only, no functional impact.

---

### 3.2 Regex Compilation (LOW)
**File:** `_shared.py`
**Severity:** LOW
**Issue:** All regex patterns are module-level compiled constants, which is good. However, there's no pre-compilation cache or memoization for `_normalise_phrase()` calls during the sliding window scan (line 902 in `anonymise.py`).

**Observation:** On large documents, `_normalise_phrase()` is called thousands of times with mostly unique inputs. The cost is minimal, but for very large PDFs (100+ pages), this could add up.

**Suggested Optimization (if profiling shows slowdown):**
```python
from functools import lru_cache

@lru_cache(maxsize=1024)
def _normalise_phrase(text: str) -> str:
    ...
```

**Priority:** LOW — No performance issues reported; premature optimization discouraged.

---

### 3.3 Memory Overhead of Font Maps (LOW)
**File:** `anonymise.py`
**Lines:** 1082-1133, 1136-1195
**Severity:** LOW
**Issue:** Per-page font maps are built for every page, even if fonts are identical across pages. For a 100-page document with the same fonts on every page, this repeats work unnecessarily.

**Current Approach:**
```python
for page_num, pike_page in enumerate(pike_doc.pages, start=1):
    forward_maps, reverse_maps, bold_fonts = _build_font_maps(pike_page)  # Repeated per page
    font_encodings, _, _ = _build_font_maps_v2(pike_page)  # Repeated per page
```

**Suggested Optimization (if profiling shows slowdown):**
```python
# Build document-level font maps once
doc_font_encodings = {}
doc_reverse_maps = {}
doc_bold_fonts = set()
for pike_page in pike_doc.pages:
    enc, rev, bold = _build_font_maps_v2(pike_page)
    doc_font_encodings.update(enc)
    doc_reverse_maps.update(rev)
    doc_bold_fonts.update(bold)

# Use cached maps for each page
for pike_page in pike_doc.pages:
    pairs = _build_scramble_bytes_pairs(
        pike_page,
        ...
        font_encodings=doc_font_encodings,
        reverse_maps=doc_reverse_maps,
        bold_fonts=doc_bold_fonts,
    )
```

**Priority:** LOW — No scaling issues reported; optimization premature unless profiling shows bottleneck.

---

## 4. TESTING & RELIABILITY

### 4.1 Test Coverage Gaps (MEDIUM)
**Files:** `tests/`
**Severity:** MEDIUM
**Issue:** While 508 tests exist, several critical paths lack explicit coverage:

1. **Tm Threshold Edge Case (Line 837):** No test verifies behavior when y-coordinate change is exactly 2.0
2. **Odd-Byte Fallback (Line 323):** No test for Identity-H fonts with incomplete byte sequences
3. **Config Merge Conflicts:** No test for user config overriding system config with identical keys
4. **Real Bank PDFs:** All tests use synthetic fixtures (`simple_text_pdf`), not real TSB/HSBC/NatWest statements
5. **Large Document Handling:** No tests for PDFs with 50+ pages
6. **Font Encoding Detection Failure:** No test for malformed `/Encoding` fields

**Suggested Tests:**

```python
def test_tm_threshold_exact_2_units():
    """Verify line accumulation when Tm y-coord changes by exactly 2.0."""
    # Create PDF with Tm operators that differ by exactly 2.0
    # Verify they're NOT accumulated as same line
    pass

def test_identity_h_odd_byte_fallback():
    """Verify odd-byte handling in Identity-H font decoding."""
    # Create fragment with odd number of bytes
    # Verify last byte is looked up individually
    pass

def test_config_user_override_priority():
    """Verify user config wins on key collision."""
    user_cfg = {"System Phrase": "User Replacement"}
    result = anonymise_pdf(..., always_anonymise_path=user_cfg)
    # Verify "System Phrase" is replaced with "User Replacement"
    pass
```

**Priority:** MEDIUM — Gaps could lead to latent bugs in real-world usage with edge case PDFs.

---

### 4.2 Mock Seeding Behavior (LOW)
**File:** `conftest.py`
**Lines:** 22-54, 265-277
**Severity:** LOW
**Issue:** The `mock_random_source` fixture patches `secrets.SystemRandom()` but doesn't verify the patch is active during tests. If a test forgets to use the fixture, it will silently use real randomness, making the test non-deterministic.

**Current Implementation:**
```python
@pytest.fixture
def mock_random_source() -> Generator[MagicMock, None, None]:
    seeded_random = random.Random()
    seeded_random.seed(42)
    mock = MagicMock()
    mock.choice = seeded_random.choice
    mock.shuffle = seeded_random.shuffle
    # ...
    with patch("secrets.SystemRandom", return_value=mock):
        yield mock
```

**Suggested Fix:** Make the fixture automatic or add a test that verifies scramble map determinism:

```python
@pytest.fixture(autouse=True)
def ensure_deterministic_random():
    """Ensure all tests use seeded random for reproducibility."""
    with patch("secrets.SystemRandom") as mock_rng:
        seeded = random.Random(42)
        mock_rng.return_value.shuffle = seeded.shuffle
        mock_rng.return_value.choice = seeded.choice
        yield
```

**Priority:** LOW — Current implementation works; suggestion is defensive.

---

### 4.3 Fixture Limitations (LOW)
**File:** `conftest.py`
**Lines:** 57-157
**Severity:** LOW
**Issue:** The `simple_text_pdf` fixture generates a minimal synthetic PDF with standard fonts. This doesn't test:
- CID fonts with Identity-H encoding (TSB, NatWest)
- Custom ToUnicode CMap streams
- Fonts with gaps in glyph mappings
- Multi-byte character sequences
- Real layout complexity

**Suggested Enhancement:**
```python
@pytest.fixture
def identity_h_text_pdf(tmp_path: Path) -> Path:
    """Generate PDF with Identity-H CID font (like TSB/NatWest real statements)."""
    # Create a PDF with /Identity-H encoding
    # Add ToUnicode CMap with multi-byte CID mappings
    # Use CID fonts instead of standard Type1 fonts
    pass
```

**Priority:** LOW — Synthetic fixtures sufficient for current test suite; real-world integration testing recommended separately.

---

## 5. API & CONFIGURATION

### 5.1 Config Path Validation (MEDIUM)
**File:** `anonymise.py`
**Lines:** 1243-1248
**Severity:** MEDIUM
**Issue:** User-provided config paths are passed to `_load_always_anonymise()` and `_load_never_anonymise()`, which check `path.exists()` and silently return empty configs if the path doesn't exist. No validation or warning is issued.

**Current Code:**
```python
always_cfg = _load_always_anonymise(
    system_path=_bundled_path("always_anonymise_system.toml"),
    user_path=Path(always_anonymise_path) if always_anonymise_path is not None else None,
)
```

**If user provides a typo in path:** The typo is silently ignored, and default config is used. User won't notice their custom rules weren't applied.

**Suggested Fix:**
```python
if always_anonymise_path is not None:
    user_path = Path(always_anonymise_path)
    if not user_path.exists():
        raise FileNotFoundError(f"User always_anonymise config not found: {user_path}")
else:
    user_path = None

if never_anonymise_path is not None:
    user_path = Path(never_anonymise_path)
    if not user_path.exists():
        raise FileNotFoundError(f"User never_anonymise config not found: {user_path}")
else:
    user_path = None
```

**Priority:** MEDIUM — Silent failures violate principle of least surprise.

---

### 5.2 Debug Output to stdout (LOW)
**File:** `anonymise.py`
**Lines:** 1232-1234, 1333
**Severity:** LOW
**Issue:** Debug output and final summary are printed to `stdout` unconditionally. For library usage, this is unexpected and can clutter user's console.

**Current Code:**
```python
def _dbg(msg: str) -> None:
    if debug:
        print(f"[DEBUG] {msg}")  # Direct print
# ...
print(f"Anonymised: {input_path.name} -> {output_path.name} ({total_pairs} scramble pair(s))")  # Always printed
```

**Suggested Fix:**
```python
import logging

logger = logging.getLogger("bank_statement_anonymiser")

def anonymise_pdf(..., debug: bool = False) -> Path:
    if debug:
        logger.setLevel(logging.DEBUG)
    # ...
    logger.info(f"Anonymised: {input_path.name} -> {output_path.name} ({total_pairs} scramble pair(s))")
```

**Priority:** LOW — Cosmetic issue; current behavior is acceptable for a CLI tool.

---

## 6. DEPENDENCIES & COMPATIBILITY

### 6.1 Pikepdf Version Constraint (LOW)
**File:** `pyproject.toml`
**Lines:** 34
**Severity:** LOW
**Issue:** Dependency is `pikepdf>=10.3.0`, which is quite permissive. No upper bound is specified, so future breaking changes in pikepdf (e.g., API changes in v11, v12) could cause runtime failures.

**Current:**
```toml
dependencies = [
    "pikepdf>=10.3.0",
]
```

**Suggested Fix:**
```toml
dependencies = [
    "pikepdf>=10.3.0,<11.0.0",  # Or <12.0.0 depending on testing
]
```

**Note:** This should be validated by testing against multiple pikepdf versions (10.3, 10.8, 11.0) in CI.

**Priority:** LOW — Future-proofing; current code likely compatible with pikepdf 11+.

---

### 6.2 Python 3.11+ Compatibility (LOW)
**File:** `pyproject.toml`, `src/bank_statement_anonymiser/`
**Severity:** LOW
**Issue:** Code targets Python 3.11+ (`requires-python = ">=3.11"`), but uses `from __future__ import annotations` which is unnecessary for 3.11 (available since 3.7). This is not a bug but an over-specification.

**Suggested Clarification:**
```toml
requires-python = ">=3.11"
# Or if supporting 3.9+:
requires-python = ">=3.9"
```

**Priority:** LOW — Code works as-is; just a minor style clarification.

---

## 7. CODE MAINTAINABILITY

### 7.1 Complex Nested Loop (MEDIUM)
**File:** `anonymise.py`
**Lines:** 884-966
**Severity:** MEDIUM
**Issue:** The sliding window line-scan loop is deeply nested (4 levels) and difficult to follow:
```python
for line_range in lines:  # Level 1
    frags_in_line = [...]
    n = len(frags_in_line)
    matched: set[int] = set()

    pos = 0
    while pos < n:  # Level 2
        if pos in matched:
            pos += 1
            continue

        found = False
        accumulated = ""
        accumulated_spaced = ""
        for end in range(pos, n):  # Level 3
            frag_decoded = frags_in_line[end].decoded
            accumulated += frag_decoded
            accumulated_spaced = ...
            norm = _normalise_phrase(accumulated)

            if norm in always_normalised:  # Level 4
                # ... complex branch logic ...
                break
```

**Suggested Refactoring:**
Extract the inner matching logic into a helper function:

```python
def _find_match_in_line(
    frags_in_line: list[_Fragment],
    pos: int,
    always_normalised: dict[str, str],
    never_cfg: _NeverAnonymiseConfig,
    numeric_id_map: dict[str, str],
) -> tuple[str | None, int] | None:
    """Find a match starting at position pos. Return (disposition, end_pos) or None."""
    for end in range(pos, len(frags_in_line)):
        # Accumulation and matching logic here
        if match_found:
            return (disposition, end)
    return None

for line_range in lines:
    frags_in_line = [...]
    pos = 0
    while pos < len(frags_in_line):
        if pos in matched:
            pos += 1
            continue
        
        result = _find_match_in_line(...)
        if result:
            disposition, end = result
            # Mark and advance
        else:
            pos += 1
```

**Priority:** MEDIUM — Complexity increases risk of subtle bugs during maintenance.

---

### 7.2 Magic Numbers (LOW)
**File:** `_shared.py`, `anonymise.py`
**Severity:** LOW
**Issue:** Several hardcoded numbers lack explanation:
- `2.0` (Tm Y threshold) — explained in code but should be a named constant
- Numeric pattern priorities are implicit in tuple order
- Regex patterns use hardcoded lengths (e.g., `\d{6}`, `\d{8}`)

**Suggested Fix:**
```python
# _shared.py
_SORT_CODE_DIGITS = 6
_ACCOUNT_DIGITS = 8
_IBAN_TAIL_DIGITS = 14  # 6 + 8
_CARD_FULL_DIGITS = 16
_CARD_MICR_PREFIX_DIGITS = 4
_CARD_MICR_SUFFIX_DIGITS = 12

_SORT_CODE_RE: re.Pattern[str] = re.compile(rf"\b(\d{{{_SORT_CODE_DIGITS}}}...")

# anonymise.py
_TM_Y_THRESHOLD_UNITS: float = 2.0  # PDF user units, roughly points
```

**Priority:** LOW — Code is readable as-is; improvement is nice-to-have.

---

### 7.3 Documentation of Edge Cases (LOW)
**File:** `anonymise.py`
**Severity:** LOW
**Issue:** Critical algorithm decisions lack docstring documentation:
- Why is Tm y-threshold 2.0 specifically?
- Why must numeric ID patterns come before IBAN?
- What happens if a fragment's font is not in reverse_maps?

**Suggested Fix:** Enhance module docstring:
```python
"""
...

Algorithm Decisions
-------------------
1. **Tm Y-Threshold (2.0 units):** Baselines and small vertical adjustments within
   the same visual line can vary by < 2.0 units (e.g., superscripts, subscripts).
   The 2.0-unit threshold prevents false line breaks on same-line repositioning.
   
   Note: Banks like TSB may render each word in its own BT/Tm/ET block at the same
   Y-coordinate. The threshold allows these to accumulate for multi-word matching.

2. **Numeric ID Pattern Order:** Patterns are processed in priority order defined
   by _NUMERIC_ID_PATTERNS. SORT_ACCT_RE must come before IBAN_FULL_RE so that
   6-digit sort codes and 8-digit accounts are cached before IBAN 14-digit tails
   are composed (ensuring consistency: IBAN tail = cached_sort + cached_account).

3. **Font Encoding Fallback:** If a glyph/character is not in a font's reverse map
   (_reencode_fragment), it cannot be re-encoded. This happens when custom ToUnicode
   CMaps map bytes to characters not in the font's baseline Latin-1 set. These
   fragments are protected (marked "protected" or left unchanged).
"""
```

**Priority:** LOW — Nice-to-have for maintainability.

---

## 8. SPECIFIC CODE LOCATIONS REQUIRING ATTENTION

### 8.1 _lookup_numeric_id Order of Checks (LINE 419-422)
The function checks four variants in order: `accumulated_spaced`, `accumulated_spaced.strip()`, `accumulated`, `accumulated.strip()`. This order is correct but should have a comment explaining why `accumulated_spaced` (space-joined) is checked first (it matches compound tokens like "403728 31243535" which have the space from the pre-pass).

### 8.2 Pendulum in charrun pre-pass (LINES 559-595)
The `_flush()` function in `_rewrite_page_content_stream` uses a `pending` list to accumulate characters spelling protected phrases. The logic is sound but uses mutable list operations within a nested function. Consider extracting to a class:

```python
class CharRunAccumulator:
    def __init__(self, protected_phrases):
        self.pending = []
        self.protected_phrases = protected_phrases
    
    def add_char(self, idx, ch):
        # Logic here
    
    def flush(self, complete):
        # Logic here
```

### 8.3 seen_raw Set in _build_scramble_bytes_pairs (LINES 983-1040)
The `seen_raw` set prevents duplicate pairs but grows unbounded. For very large documents with many unique byte sequences, this could consume memory. Consider using a WeakSet or dropping duplicates at the end.

---

## SUMMARY TABLE

| Category | Finding | Severity | Lines | Type |
|----------|---------|----------|-------|------|
| Correctness | Blind Exception Catching | HIGH | Multiple | Error Handling |
| Correctness | Type Annotations Unnecessary Quotes | MEDIUM | 291-292, 364, 501, 614, 768, 1138, 1150 | Style |
| Correctness | Resource Cleanup Error Context | MEDIUM | 1263-1331 | Exception Handling |
| Correctness | Tm Threshold Boundary Condition | MEDIUM | 837 | Logic |
| Correctness | Font Encoding Detection Robustness | MEDIUM | 341-357 | Encoding |
| Configuration | Config Path Validation | MEDIUM | 1243-1248 | Input Validation |
| Testing | Test Coverage Gaps | MEDIUM | tests/ | Testing |
| Maintainability | Complex Nested Loop | MEDIUM | 884-966 | Refactoring |
| Logging | Debug Output to stdout | LOW | 1232-1234, 1333 | Output |
| Performance | Unused .keys() iterations | LOW | 1109, 1160 | Optimization |
| Dependencies | Pikepdf Version Constraint | LOW | pyproject.toml:34 | Dependencies |
| Documentation | Magic Numbers | LOW | Multiple | Documentation |
| Testing | Mock Seeding Behavior | LOW | conftest.py | Testing |
| Testing | Fixture Limitations | LOW | conftest.py | Testing |
| Code Quality | Unused Imports | LOW | Multiple test files | Hygiene |

---

## RECOMMENDATIONS (Priority Order)

### Immediate (Next Release)
1. Replace blind `except Exception:` with specific exception types
2. Add config path validation with clear error messages
3. Fix Tm threshold comparison from `>` to `>=`
4. Add tests for Tm threshold edge case and odd-byte fallback

### Short Term (Within 2 Weeks)
5. Fix type annotation quotes (ruff --fix can auto-do this)
6. Improve error context in resource cleanup
7. Add defensive checks for font encoding detection
8. Extract nested loop logic into helper function

### Medium Term (Polish)
9. Add documentation for algorithm decisions
10. Create Identity-H test fixtures for real bank PDF compatibility
11. Add upper bound constraint to pikepdf dependency
12. Clean up unused imports (ruff --fix)

### Long Term (Future Enhancement)
13. Consider using logging instead of print() for debug output
14. Cache document-level font maps if profiling shows bottleneck
15. Add CircleCI/GitHub Actions integration test against real bank PDFs

---

## CONCLUSION

The codebase is **fundamentally sound** with a well-architected three-phase pipeline and comprehensive test coverage (508 tests, all passing). The main risks are:

1. **Silent failures** due to blind exception catching (HIGH risk)
2. **Line accumulation edge cases** that could affect phrase matching (MEDIUM risk)
3. **Configuration validation** gaps that could lead to unnoticed config misapplication (MEDIUM risk)

Addressing the HIGH and MEDIUM severity issues will significantly improve robustness, especially for edge case PDFs from TSB, NatWest, and HSBC with non-standard encodings and layouts.

