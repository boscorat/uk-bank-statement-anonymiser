"""
Unit tests for pattern detection in the bank_statement_anonymiser.

This module tests:
- Date patterns (_DATE_RE, _DATE_DAY_MONTH_RE, _DATE_COMPACT_RE, _DATE_RANGE_RE)
- Month patterns (_MONTH_NAME_RE, _MONTH_COMPACT_RE)
- Numeric / amount patterns (_NUMERIC_RE, _REF_NUMBER_RE)
- Compound payment-type pattern (_COMPOUND_TYPE_DESC_RE)
- URL pattern (_URL_RE)
- The _is_builtin_protected() gate function (which combines all of the above)
- Numeric ID regex patterns (_SORT_CODE_RE, _ACCOUNT_RE, _SORT_ACCT_RE,
  _CARD_RE, _CARD_MICR_RE, _MICR_LINE_RE, _IBAN_FULL_RE, _IBAN_SPACED_RE,
  _IBAN_TAIL_RE)

All regex tests follow the same convention: a plain list of strings that must
match (SHOULD_MATCH) and a list that must not match (SHOULD_NOT_MATCH) are
defined at the top of each class; parametrised methods then iterate them.
This eliminates boilerplate while making intent explicit.
"""

from __future__ import annotations

import pytest

from bank_statement_anonymiser._shared import (
    _COMPOUND_TYPE_DESC_RE,
    _DATE_COMPACT_RE,
    _DATE_DAY_MONTH_RE,
    _DATE_RANGE_RE,
    _DATE_RE,
    _MONTH_COMPACT_RE,
    _MONTH_NAME_RE,
    _NUMERIC_RE,
    _REF_NUMBER_RE,
    _URL_RE,
    _SORT_CODE_RE,
    _ACCOUNT_RE,
    _SORT_ACCT_RE,
    _CARD_RE,
    _CARD_MICR_RE,
    _MICR_LINE_RE,
    _IBAN_FULL_RE,
    _IBAN_SPACED_RE,
    _IBAN_TAIL_RE,
)
from bank_statement_anonymiser.anonymise import _is_builtin_protected


# ============================================================================
# Date patterns
# ============================================================================


class TestDateRe:
    """Tests for _DATE_RE: "d Mmm yy" or "d Mmm yyyy" full transaction dates."""

    SHOULD_MATCH = [
        "23 Jan 25",
        "1 Jan 25",
        "24 Aug 2019",
        "15 June 2025",
        "3 Dec 99",
        "31 Mar 24",
        "1 February 2024",
        "28 Feb 24",
        "9 sep 23",          # lowercase
        "09 SEP 2023",       # uppercase
        "15 July 2024",
    ]

    SHOULD_NOT_MATCH = [
        "Jan 25",            # missing day
        "23 Jan",            # missing year
        "2024-01-23",        # ISO format
        "23/01/2024",        # DD/MM/YYYY
        "23 January",        # missing year
        "Jan 2025",          # month-year only
        "hello",
        "",
        "23 Xyz 25",         # invalid month
        "23  Jan 25",        # double space
    ]

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_MATCH)
    def test_date_re_matches(self, text):
        """_DATE_RE should match valid full dates."""
        assert _DATE_RE.match(text), f"Expected match for: {text!r}"

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_NOT_MATCH)
    def test_date_re_rejects(self, text):
        """_DATE_RE should not match non-date strings."""
        assert not _DATE_RE.match(text), f"Expected no match for: {text!r}"


class TestDateDayMonthRe:
    """Tests for _DATE_DAY_MONTH_RE: day + month only, no year."""

    SHOULD_MATCH = [
        "03 Jan",
        "15 June",
        "1 Mar",
        "28 Feb",
        "31 December",
        "9 oct",             # lowercase
        "1 AUGUST",          # uppercase
    ]

    SHOULD_NOT_MATCH = [
        "Jan",               # month only
        "03 Jan 25",         # has year
        "03/01",             # slash format
        "03-Jan",            # hyphen format
        "03 Xyz",            # invalid month
        "hello",
        "",
    ]

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_MATCH)
    def test_day_month_re_matches(self, text):
        """_DATE_DAY_MONTH_RE should match day-month pairs."""
        assert _DATE_DAY_MONTH_RE.match(text), f"Expected match for: {text!r}"

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_NOT_MATCH)
    def test_day_month_re_rejects(self, text):
        """_DATE_DAY_MONTH_RE should not match other strings."""
        assert not _DATE_DAY_MONTH_RE.match(text), f"Expected no match for: {text!r}"


class TestDateCompactRe:
    """Tests for _DATE_COMPACT_RE: day + month immediately followed by 2 or 4-digit year."""

    SHOULD_MATCH = [
        "11 Dec21",
        "15 June2025",
        "1 Jan24",
        "31 Mar2024",
        "9 sep23",           # lowercase
        "03 AUG99",          # uppercase 2-digit year
        "1 February2024",
    ]

    SHOULD_NOT_MATCH = [
        "11 Dec 21",         # has space before year (normal _DATE_RE territory)
        "Dec21",             # no day
        "11Dec21",           # no space after day
        "11 Dec",            # no year
        "11 Xyz21",          # invalid month
        "",
    ]

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_MATCH)
    def test_compact_date_matches(self, text):
        """_DATE_COMPACT_RE should match compact day-month-year tokens."""
        assert _DATE_COMPACT_RE.match(text), f"Expected match for: {text!r}"

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_NOT_MATCH)
    def test_compact_date_rejects(self, text):
        """_DATE_COMPACT_RE should not match other strings."""
        assert not _DATE_COMPACT_RE.match(text), f"Expected no match for: {text!r}"


class TestDateRangeRe:
    """Tests for _DATE_RANGE_RE: "d Mmm [yy[yy]] to d Mmm [yy[yy]]"."""

    SHOULD_MATCH = [
        "24 Aug 2019 to 24 Sep 2019",
        "16 May 2025 to 15 June 2025",
        "1 Jan to 31 Jan",           # both sides year-less
        "1 Jan 25 to 31 Jan 25",     # both sides 2-digit year
        "1 Jan 2025 to 31 Jan 2025", # both sides 4-digit year
        "1 jan 25 to 31 jan 25",     # lowercase
    ]

    SHOULD_NOT_MATCH = [
        "24 Aug 2019 24 Sep 2019",   # missing "to"
        "24 Aug 2019",               # single date
        "Aug 2019 to Sep 2019",      # no day
        "2019-08-24 to 2019-09-24",  # ISO format
        "",
    ]

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_MATCH)
    def test_date_range_matches(self, text):
        """_DATE_RANGE_RE should match date-range strings."""
        assert _DATE_RANGE_RE.fullmatch(text), f"Expected match for: {text!r}"

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_NOT_MATCH)
    def test_date_range_rejects(self, text):
        """_DATE_RANGE_RE should not match non-date-range strings."""
        assert not _DATE_RANGE_RE.fullmatch(text), f"Expected no match for: {text!r}"


# ============================================================================
# Month name patterns
# ============================================================================


class TestMonthNameRe:
    """Tests for _MONTH_NAME_RE: standalone 3-letter abbreviation or full name."""

    SHOULD_MATCH = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul",
        "Aug", "Sep", "Oct", "Nov", "Dec",
        "January", "February", "March", "April", "June",
        "July", "August", "September", "October", "November", "December",
        "jan", "JAN", "JANUARY",  # case insensitive
    ]

    SHOULD_NOT_MATCH = [
        "Ja",        # too short
        "Janu",      # truncated
        "Janx",      # invalid suffix
        "15 Jan",    # has day
        "Jan 25",    # has year
        "hello",
        "",
        "1",
    ]

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_MATCH)
    def test_month_name_matches(self, text):
        """_MONTH_NAME_RE should match standalone month names."""
        assert _MONTH_NAME_RE.match(text), f"Expected match for: {text!r}"

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_NOT_MATCH)
    def test_month_name_rejects(self, text):
        """_MONTH_NAME_RE should not match non-month strings."""
        assert not _MONTH_NAME_RE.match(text), f"Expected no match for: {text!r}"


class TestMonthCompactRe:
    """Tests for _MONTH_COMPACT_RE: month name immediately followed by 2-digit year."""

    SHOULD_MATCH = [
        "Dec21",
        "June21",
        "Jan99",
        "july25",    # lowercase
        "AUG24",     # uppercase
        "September23",
    ]

    SHOULD_NOT_MATCH = [
        "Dec 21",    # has space before year
        "Dec2021",   # 4-digit year
        "De21",      # truncated month
        "21",        # year only
        "Decxx",     # non-digit year
        "",
    ]

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_MATCH)
    def test_month_compact_matches(self, text):
        """_MONTH_COMPACT_RE should match compact month+year tokens."""
        assert _MONTH_COMPACT_RE.match(text), f"Expected match for: {text!r}"

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_NOT_MATCH)
    def test_month_compact_rejects(self, text):
        """_MONTH_COMPACT_RE should not match non-compact-month strings."""
        assert not _MONTH_COMPACT_RE.match(text), f"Expected no match for: {text!r}"


# ============================================================================
# Numeric / amount patterns
# ============================================================================


class TestNumericRe:
    """Tests for _NUMERIC_RE: numeric values, amounts, and polarity suffixes."""

    SHOULD_MATCH = [
        "1234.56",
        "1,234.56",
        "£1,234.56",
        "1234",
        "0.00",
        "1234.56CR",
        "1234.56D",
        "CR",
        "D",
        "£0.00",
        "12 34",          # digit with space
        "1234.56 CR",     # space before CR
        "-1234.56",
        "1.2.3",          # dots pass (pattern is permissive)
    ]

    SHOULD_NOT_MATCH = [
        "hello",
        "Amazon Ltd",
        "12abc",          # letter in middle (not CR suffix)
        "abc123",
        "1234CR5",        # CR not at end
        "",
    ]

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_MATCH)
    def test_numeric_re_matches(self, text):
        """_NUMERIC_RE should match numeric amount tokens."""
        assert _NUMERIC_RE.match(text), f"Expected match for: {text!r}"

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_NOT_MATCH)
    def test_numeric_re_rejects(self, text):
        """_NUMERIC_RE should not match non-numeric strings."""
        assert not _NUMERIC_RE.match(text), f"Expected no match for: {text!r}"


class TestRefNumberRe:
    """Tests for _REF_NUMBER_RE: reference numbers starting with digit, ≥5 chars."""

    SHOULD_MATCH = [
        "12345",           # 5 digits minimum
        "12-345",          # 5 chars with hyphen
        "123456789",       # long reference
        "12345-6789",      # hyphenated reference
        "1-2-3-4",         # multi-hyphen
    ]

    SHOULD_NOT_MATCH = [
        "1234",            # only 4 chars (pattern requires ≥5 via \d[\d\-]{4,})
        "abcde",           # no leading digit
        "1abc5",           # non-digit/hyphen chars in middle
        "12 345",          # space not hyphen
        "",
    ]

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_MATCH)
    def test_ref_number_matches(self, text):
        """_REF_NUMBER_RE should match valid reference numbers."""
        assert _REF_NUMBER_RE.match(text), f"Expected match for: {text!r}"

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_NOT_MATCH)
    def test_ref_number_rejects(self, text):
        """_REF_NUMBER_RE should not match non-reference strings."""
        assert not _REF_NUMBER_RE.match(text), f"Expected no match for: {text!r}"


# ============================================================================
# Compound payment-type pattern
# ============================================================================


class TestCompoundTypeDescRe:
    """Tests for _COMPOUND_TYPE_DESC_RE: payment-type prefix merged with description."""

    SHOULD_MATCH = [
        # (full match, group 1 = type code, group 2 = description)
        ("BPAmazon", "BP", "Amazon"),
        ("VISWaitrose", "VIS", "Waitrose"),
        ("DDCouncilTax", "DD", "CouncilTax"),
        ("TFRSavings", "TFR", "Savings"),
        ("SOElectricity", "SO", "Electricity"),
        ("CRSalary", "CR", "Salary"),
        ("DRPayment", "DR", "Payment"),
        ("ATMCash", "ATM", "Cash"),
        ("CCSpend", "CC", "Spend"),
        ("OBPPayee", "OBP", "Payee"),
        (")))Marker", ")))", "Marker"),  # TSB internal marker prefix (3 closing parens)
        ("bpamazon", "bp", "amazon"),    # lowercase — description starts with any letter
        ("BPamazon", "BP", "amazon"),    # description starts with lowercase letter — valid
    ]

    SHOULD_NOT_MATCH = [
        "Amazon",         # no payment-type prefix
        "123Amazon",      # starts with digit
        "BP",             # prefix only, no description
        "",
    ]

    @pytest.mark.unit
    @pytest.mark.parametrize("full,code,desc", SHOULD_MATCH)
    def test_compound_matches_and_groups(self, full, code, desc):
        """_COMPOUND_TYPE_DESC_RE should match and capture type code and description."""
        m = _COMPOUND_TYPE_DESC_RE.match(full)
        assert m is not None, f"Expected match for: {full!r}"
        assert m.group(1).upper() == code.upper(), (
            f"Group 1 (type code) mismatch for {full!r}: "
            f"expected {code!r}, got {m.group(1)!r}"
        )
        assert m.group(2) == desc, (
            f"Group 2 (description) mismatch for {full!r}: "
            f"expected {desc!r}, got {m.group(2)!r}"
        )

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_NOT_MATCH)
    def test_compound_rejects(self, text):
        """_COMPOUND_TYPE_DESC_RE should not match strings lacking a payment prefix."""
        assert not _COMPOUND_TYPE_DESC_RE.match(text), f"Expected no match for: {text!r}"


# ============================================================================
# URL pattern
# ============================================================================


class TestUrlRe:
    """Tests for _URL_RE: URLs and domain names."""

    SHOULD_MATCH = [
        "https://www.hsbc.co.uk",
        "http://natwest.com",
        "www.tsb.co.uk",
        "tsb.co.uk",
        "natwest.com",
        "example.org",
        "example.net",
        "bank.gov.uk",
        "mybank.bank",
        "https://secure.hsbc.co.uk/login",
    ]

    SHOULD_NOT_MATCH = [
        "gov.uk",         # bare TLD only — no subdomain or path, so no match
        "hello world",
        "Amazon Ltd",
        "40-37-28",
        "example",        # no TLD
        "",
    ]

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_MATCH)
    def test_url_re_matches(self, text):
        """_URL_RE should match URLs and known domain patterns."""
        assert _URL_RE.search(text), f"Expected match for: {text!r}"

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_NOT_MATCH)
    def test_url_re_rejects(self, text):
        """_URL_RE should not match non-URL strings."""
        assert not _URL_RE.fullmatch(text), f"Expected no match for: {text!r}"


# ============================================================================
# _is_builtin_protected gate function
# ============================================================================


class TestIsBuiltinProtected:
    """Tests for _is_builtin_protected(): the combined protection gate."""

    # --- things that MUST be protected ---
    PROTECTED = [
        # short / empty
        "",
        " ",
        "A",
        "a",
        "1",
        # full dates
        "23 Jan 25",
        "24 Aug 2019",
        "15 June 2025",
        "1 February 2024",
        # compact dates
        "11 Dec21",
        "15 June2025",
        # day-month only
        "03 Jan",
        "15 June",
        # month names
        "Jan",
        "January",
        "Dec",
        "December",
        # compact month+year
        "Dec21",
        "June21",
        # numeric amounts
        "1234.56",
        "£1,234.56",
        "1234.56CR",
        "CR",
        "D",
        "0.00",
        # date ranges
        "24 Aug 2019 to 24 Sep 2019",
        "1 Jan to 31 Jan",
        # URLs
        "https://www.hsbc.co.uk",
        "www.natwest.com",
        "tsb.co.uk",
    ]

    # --- things that MUST NOT be protected (i.e. should be scrambled) ---
    NOT_PROTECTED = [
        "Amazon Ltd",
        "Tesco Supermarket",
        "National Rail",
        "Hello World",
        "SALARY PAYMENT",
        "BT Internet",
        "John Smith",
        "Barclays",
        # payment codes alone are NOT builtin-protected (they come from config)
        # but are longer than 1 char so not short-circuit protected
        "Amazon",
        "PayPal",
    ]

    @pytest.mark.unit
    @pytest.mark.parametrize("text", PROTECTED)
    def test_is_protected(self, text):
        """_is_builtin_protected should return True for protected patterns."""
        assert _is_builtin_protected(text), (
            f"Expected True (protected) for: {text!r}"
        )

    @pytest.mark.unit
    @pytest.mark.parametrize("text", NOT_PROTECTED)
    def test_is_not_protected(self, text):
        """_is_builtin_protected should return False for scramblable text."""
        assert not _is_builtin_protected(text), (
            f"Expected False (not protected) for: {text!r}"
        )

    @pytest.mark.unit
    def test_strips_leading_trailing_spaces(self):
        """_is_builtin_protected should strip surrounding whitespace before matching."""
        assert _is_builtin_protected("  23 Jan 25  "), (
            "Should match date even with surrounding spaces"
        )
        assert _is_builtin_protected("  £1,234.56  "), (
            "Should match amount even with surrounding spaces"
        )

    @pytest.mark.unit
    def test_single_char_always_protected(self):
        """Any single character must be protected (len < 2 after strip)."""
        for ch in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
            assert _is_builtin_protected(ch), (
                f"Single char {ch!r} should be protected"
            )

    @pytest.mark.unit
    def test_two_char_letters_not_auto_protected(self):
        """Two-character letter strings should NOT be auto-protected (go through pattern checks)."""
        # "AB" has no pattern match, so should not be protected
        assert not _is_builtin_protected("AB"), (
            "Two-letter string 'AB' should not be auto-protected"
        )

    @pytest.mark.unit
    def test_numeric_re_variants_all_protected(self):
        """Various numeric amount formats should all be protected."""
        amounts = [
            "100",
            "100.00",
            "1,000.00",
            "£500",
            "£0.00",
            "999.99CR",
            "999.99D",
        ]
        for amount in amounts:
            assert _is_builtin_protected(amount), (
                f"Amount {amount!r} should be protected"
            )


# ============================================================================
# Numeric ID regex patterns
# ============================================================================


class TestSortCodeRe:
    """Tests for _SORT_CODE_RE: 6 digits with hyphen or space separators."""

    SHOULD_MATCH = [
        "40-37-28",
        "40 37 28",
        "40-37 28",      # mixed separators
        "00-00-00",
        "99-99-99",
    ]

    SHOULD_NOT_MATCH = [
        "403728",        # no separators — bare 6 digits not matched
        "4-3-2",         # single digits per group
        "400-37-28",     # 3 digits in first group
        "40.37.28",      # dot separators
        "40-37-2",       # only 1 digit in last group
        "hello",
    ]

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_MATCH)
    def test_sort_code_matches(self, text):
        assert _SORT_CODE_RE.search(text), f"Expected match for: {text!r}"

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_NOT_MATCH)
    def test_sort_code_rejects(self, text):
        assert not _SORT_CODE_RE.search(text), f"Expected no match for: {text!r}"

    @pytest.mark.unit
    def test_sort_code_extracts_three_groups(self):
        """_SORT_CODE_RE should capture 3 two-digit groups."""
        m = _SORT_CODE_RE.search("40-37-28")
        assert m is not None
        assert m.group(1) == "40"
        assert m.group(2) == "37"
        assert m.group(3) == "28"


class TestAccountRe:
    """Tests for _ACCOUNT_RE: bare 8-digit account numbers."""

    SHOULD_MATCH = [
        "31243535",
        "00000000",
        "12345678",
        "99999999",
    ]

    SHOULD_NOT_MATCH = [
        "1234567",     # 7 digits
        "123456789",   # 9 digits (word-boundary means this won't match the 8)
        "1234-5678",   # hyphens — not a bare 8-digit run
        "abcdefgh",    # letters
    ]

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_MATCH)
    def test_account_matches(self, text):
        assert _ACCOUNT_RE.search(text), f"Expected match for: {text!r}"

    @pytest.mark.unit
    def test_account_no_match_nine_digits(self):
        """Nine consecutive digits should not produce an 8-digit match (word boundary)."""
        assert not _ACCOUNT_RE.fullmatch("123456789"), (
            "9-digit string should not fullmatch 8-digit pattern"
        )

    @pytest.mark.unit
    def test_account_extracts_group(self):
        """_ACCOUNT_RE should capture the 8-digit group."""
        m = _ACCOUNT_RE.search("31243535")
        assert m is not None
        assert m.group(1) == "31243535"


class TestSortAcctRe:
    """Tests for _SORT_ACCT_RE: compound 6-digit + space + 8-digit token."""

    SHOULD_MATCH = [
        "403728 31243535",
        "000000 00000000",
        "123456 78901234",
    ]

    SHOULD_NOT_MATCH = [
        "40-37-28 31243535",  # sort code with hyphens
        "403728-31243535",    # hyphen separator
        "40372831243535",     # no space
        "403728 3124353",     # account only 7 digits
        "40372 31243535",     # sort code only 5 digits
    ]

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_MATCH)
    def test_sort_acct_matches(self, text):
        assert _SORT_ACCT_RE.search(text), f"Expected match for: {text!r}"

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_NOT_MATCH)
    def test_sort_acct_rejects(self, text):
        assert not _SORT_ACCT_RE.search(text), f"Expected no match for: {text!r}"

    @pytest.mark.unit
    def test_sort_acct_captures_both_groups(self):
        """Should capture sort code (group 1) and account number (group 2) separately."""
        m = _SORT_ACCT_RE.search("403728 31243535")
        assert m is not None
        assert m.group(1) == "403728"
        assert m.group(2) == "31243535"


class TestCardRe:
    """Tests for _CARD_RE: 16 digits in 4 groups of 4 separated by spaces."""

    SHOULD_MATCH = [
        "3333 2222 1111 0000",
        "4532 1234 5678 9012",
        "0000 0000 0000 0000",
        "9999 9999 9999 9999",
    ]

    SHOULD_NOT_MATCH = [
        "3333-2222-1111-0000",   # hyphens
        "3333222211110000",      # no spaces
        "3333 2222 1111 000",    # last group only 3 digits
        "333 2222 1111 0000",    # first group only 3 digits
        "3333 2222 1111",        # only 3 groups
        "hello",
    ]

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_MATCH)
    def test_card_re_matches(self, text):
        assert _CARD_RE.search(text), f"Expected match for: {text!r}"

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_NOT_MATCH)
    def test_card_re_rejects(self, text):
        assert not _CARD_RE.search(text), f"Expected no match for: {text!r}"

    @pytest.mark.unit
    def test_card_re_captures_four_groups(self):
        """_CARD_RE should capture each of the four 4-digit groups."""
        m = _CARD_RE.search("4532 1234 5678 9012")
        assert m is not None
        assert m.group(1) == "4532"
        assert m.group(2) == "1234"
        assert m.group(3) == "5678"
        assert m.group(4) == "9012"


class TestCardMicrRe:
    """Tests for _CARD_MICR_RE: 4 digits + space + 12 digits (giro slip format)."""

    SHOULD_MATCH = [
        "5402 225003072770",
        "1234 567890123456",
        "0000 000000000000",
    ]

    SHOULD_NOT_MATCH = [
        "5402-225003072770",      # hyphen
        "54022250030727700",      # no space
        "5402 22500307277",       # 11-digit second group
        "5402 2250030727700",     # 13-digit second group
        "542 225003072770",       # 3-digit first group
        "3333 2222 1111 0000",    # 4x4 card format instead
    ]

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_MATCH)
    def test_card_micr_matches(self, text):
        assert _CARD_MICR_RE.search(text), f"Expected match for: {text!r}"

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_NOT_MATCH)
    def test_card_micr_rejects(self, text):
        assert not _CARD_MICR_RE.search(text), f"Expected no match for: {text!r}"


class TestMicrLineRe:
    """Tests for _MICR_LINE_RE: <16digits< MICR giro line format."""

    SHOULD_MATCH = [
        "<5402225003072770< 774831+< 73   X",
        "<1234567890123456< 123456+< 00   A",
        "<9999999999999999<anything here   Z",
    ]

    SHOULD_NOT_MATCH = [
        "5402225003072770< 774831+< 73   X",   # missing leading <
        "<540222500307277< 774831+< 73   X",   # only 15 digits
        "<54022250030727700< 774831+< 73   X", # 17 digits
        "hello",
        "",
    ]

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_MATCH)
    def test_micr_line_matches(self, text):
        assert _MICR_LINE_RE.search(text), f"Expected match for: {text!r}"

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_NOT_MATCH)
    def test_micr_line_rejects(self, text):
        assert not _MICR_LINE_RE.search(text), f"Expected no match for: {text!r}"

    @pytest.mark.unit
    def test_micr_line_captures_card_and_tail(self):
        """group(1) = 16-digit card number, group(2) = tail starting with '<'."""
        m = _MICR_LINE_RE.search("<5402225003072770< 774831+< 73   X")
        assert m is not None
        assert m.group(1) == "5402225003072770"
        assert m.group(2).startswith("<")


class TestIbanFullRe:
    """Tests for _IBAN_FULL_RE: letter+digit prefix followed by exactly 14 trailing digits."""

    SHOULD_MATCH = [
        "VN72JNEB40372831243535",
        "GB82WEST12345698765432",
        "A12345678901234",          # minimal: one letter + 14 digits
    ]

    SHOULD_NOT_MATCH = [
        "40372831243535",           # no letter prefix
        "GB82",                     # too short, no 14-digit tail
        "GBXYZ",                    # letters only
        "12345678901234",           # 14 digits but no letter prefix
        "",
    ]

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_MATCH)
    def test_iban_full_matches(self, text):
        assert _IBAN_FULL_RE.search(text), f"Expected match for: {text!r}"

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_NOT_MATCH)
    def test_iban_full_rejects(self, text):
        assert not _IBAN_FULL_RE.search(text), f"Expected no match for: {text!r}"

    @pytest.mark.unit
    def test_iban_full_captures_14_digit_tail(self):
        """group(1) must be exactly the 14 trailing digits."""
        m = _IBAN_FULL_RE.search("VN72JNEB40372831243535")
        assert m is not None
        tail = m.group(1)
        assert len(tail) == 14, f"Expected 14-digit tail, got {tail!r}"
        assert tail.isdigit(), f"Tail should be all digits, got {tail!r}"
        assert tail == "40372831243535"


class TestIbanSpacedRe:
    """Tests for _IBAN_SPACED_RE: "CC## BBBB #### #### #### ##" spaced UK IBAN."""

    SHOULD_MATCH = [
        "GB19 NWBK 6016 2400 3980 04",
        "GB82 WEST 1234 5698 7654 32",
        "gb19 nwbk 6016 2400 3980 04",   # lowercase
    ]

    SHOULD_NOT_MATCH = [
        "GB19NWBK60162400398004",         # no spaces
        "GB19 NWBK 6016 2400 3980",       # missing last group
        "G19 NWBK 6016 2400 3980 04",     # country code too short
        "GB19 NWB 6016 2400 3980 04",     # bank code only 3 letters
        "GB19 NWBK 6016 2400 3980 0",     # last group only 1 digit
        "GB19 NWBK 6016 2400 3980 044",   # last group 3 digits
        "",
    ]

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_MATCH)
    def test_iban_spaced_matches(self, text):
        assert _IBAN_SPACED_RE.search(text), f"Expected match for: {text!r}"

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_NOT_MATCH)
    def test_iban_spaced_rejects(self, text):
        assert not _IBAN_SPACED_RE.search(text), f"Expected no match for: {text!r}"

    @pytest.mark.unit
    def test_iban_spaced_preserves_prefix_group(self):
        """group(1) = country+check+bank prefix; group(2) = 14-digit section."""
        m = _IBAN_SPACED_RE.search("GB19 NWBK 6016 2400 3980 04")
        assert m is not None
        prefix = m.group(1)
        digits = m.group(2)
        assert prefix == "GB19 NWBK ", f"Unexpected prefix: {prefix!r}"
        assert digits == "6016 2400 3980 04", f"Unexpected digit section: {digits!r}"


class TestIbanTailRe:
    """Tests for _IBAN_TAIL_RE: bare 14-digit fallback."""

    SHOULD_MATCH = [
        "40372831243535",
        "00000000000000",
        "12345678901234",
    ]

    SHOULD_NOT_MATCH = [
        "4037283124353",     # 13 digits
        "403728312435350",   # 15 digits
        "4037283124353X",    # letter at end
        "hello",
        "",
    ]

    @pytest.mark.unit
    @pytest.mark.parametrize("text", SHOULD_MATCH)
    def test_iban_tail_matches(self, text):
        assert _IBAN_TAIL_RE.search(text), f"Expected match for: {text!r}"

    @pytest.mark.unit
    def test_iban_tail_no_fullmatch_on_15_digits(self):
        """15 consecutive digits should not fullmatch the 14-digit pattern."""
        assert not _IBAN_TAIL_RE.fullmatch("403728312435350"), (
            "15-digit string should not fullmatch _IBAN_TAIL_RE"
        )

    @pytest.mark.unit
    def test_iban_tail_captures_digits(self):
        """group(1) should be the 14 captured digits."""
        m = _IBAN_TAIL_RE.search("40372831243535")
        assert m is not None
        assert m.group(1) == "40372831243535"
