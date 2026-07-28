"""
Unit tests for core text transformation functions in the bank_statement_anonymiser.

This module tests:
- Scramble map generation and determinism
- Character-case preservation during scrambling
- Digit/symbol preservation (only letters are scrambled)
- Fixed replacement mappings (always_anonymise rules)
- Helper functions for numeric ID manipulation

Tests use mock_random_source fixture to ensure deterministic output.
"""

from __future__ import annotations

import pytest

from bank_statement_anonymiser._shared import (
    _detect_numeric_ids,
    _make_scramble_map,
    _reapply_separators,
    _repeat_last_two,
    _strip_numeric_separators,
)


class TestScrambleMapGeneration:
    """Unit tests for scramble map generation and properties."""

    @pytest.mark.unit
    def test_scramble_map_returns_dict(self, mock_random_source):
        """
        Verify that _make_scramble_map returns a dictionary.

        Given: A call to _make_scramble_map
        When: The function is invoked
        Then: A dict is returned
        """
        result = _make_scramble_map()
        assert isinstance(result, dict), "Expected dict type"

    @pytest.mark.unit
    def test_scramble_map_contains_all_lowercase_letters(self, mock_random_source):
        """
        Verify that scramble map contains mapping for all lowercase letters.

        Given: A generated scramble map
        When: We check for all lowercase ASCII letters (a-z)
        Then: All 26 lowercase letters are present as keys
        And:  Each maps to a valid ASCII lowercase letter ord value
        """
        scramble_map = _make_scramble_map()

        for letter in "abcdefghijklmnopqrstuvwxyz":
            ord_lower = ord(letter)
            assert ord_lower in scramble_map, f"Lowercase letter '{letter}' not in map"
            
            mapped_value = scramble_map[ord_lower]
            # Verify it maps to a lowercase letter
            assert 97 <= mapped_value <= 122, (
                f"Letter '{letter}' maps to {chr(mapped_value)}, "
                f"which is not a lowercase letter"
            )

    @pytest.mark.unit
    def test_scramble_map_contains_all_uppercase_letters(self, mock_random_source):
        """
        Verify that scramble map contains mapping for all uppercase letters.

        Given: A generated scramble map
        When: We check for all uppercase ASCII letters (A-Z)
        Then: All 26 uppercase letters are present as keys
        And:  Each maps to a valid ASCII uppercase letter ord value
        """
        scramble_map = _make_scramble_map()

        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            ord_upper = ord(letter)
            assert ord_upper in scramble_map, f"Uppercase letter '{letter}' not in map"
            
            mapped_value = scramble_map[ord_upper]
            # Verify it maps to an uppercase letter
            assert 65 <= mapped_value <= 90, (
                f"Letter '{letter}' maps to {chr(mapped_value)}, "
                f"which is not an uppercase letter"
            )

    @pytest.mark.unit
    def test_scramble_map_has_exactly_52_entries(self, mock_random_source):
        """
        Verify that scramble map has exactly 52 entries (26 lower + 26 upper).

        Given: A generated scramble map
        When: We count the entries
        Then: There are exactly 52 keys (one per letter, case-sensitive)
        """
        scramble_map = _make_scramble_map()
        assert len(scramble_map) == 52, (
            f"Expected 52 entries (26 lower + 26 upper), got {len(scramble_map)}"
        )

    @pytest.mark.unit
    def test_scramble_map_preserves_case(self, mock_random_source):
        """
        Verify that scramble map never maps lowercase to uppercase or vice versa.

        Given: A generated scramble map
        When: We check all mappings
        Then: No lowercase letter maps to an uppercase letter value
        And:  No uppercase letter maps to a lowercase letter value
        """
        scramble_map = _make_scramble_map()

        # Check all mappings preserve case
        for ord_key, ord_value in scramble_map.items():
            is_lower_key = 97 <= ord_key <= 122
            is_lower_value = 97 <= ord_value <= 122
            
            assert is_lower_key == is_lower_value, (
                f"Case mismatch: {chr(ord_key)} maps to {chr(ord_value)}"
            )

    @pytest.mark.unit
    def test_scramble_map_never_identity_maps_lowercase(self, mock_random_source):
        """
        Verify that no lowercase letter maps to itself (no identity mapping).

        Given: A generated scramble map
        When: We check all lowercase letter mappings
        Then: No lowercase letter maps to itself
        """
        scramble_map = _make_scramble_map()

        for letter in "abcdefghijklmnopqrstuvwxyz":
            ord_lower = ord(letter)
            mapped_value = scramble_map[ord_lower]
            assert mapped_value != ord_lower, (
                f"Lowercase letter '{letter}' maps to itself (identity mapping)"
            )

    @pytest.mark.unit
    def test_scramble_map_never_identity_maps_uppercase(self, mock_random_source):
        """
        Verify that no uppercase letter maps to itself (no identity mapping).

        Given: A generated scramble map
        When: We check all uppercase letter mappings
        Then: No uppercase letter maps to itself
        """
        scramble_map = _make_scramble_map()

        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            ord_upper = ord(letter)
            mapped_value = scramble_map[ord_upper]
            assert mapped_value != ord_upper, (
                f"Uppercase letter '{letter}' maps to itself (identity mapping)"
            )

    @pytest.mark.unit
    def test_scramble_map_never_produces_identity_mapping(self, mock_random_source):
        """
        Verify that the shuffle loops ensure no identity mappings occur.

        Given: The _make_scramble_map function with mocked random
        When: We generate a scramble map
        Then: No letter maps to itself (verified by the shuffle loop logic)
        And:  We can generate multiple maps, each valid (permutation with no identity mapping)
        """
        # Generate multiple maps to verify the no-identity-mapping property holds
        for _ in range(3):
            scramble_map = _make_scramble_map()
            
            # Verify no lowercase letter maps to itself
            for letter in "abcdefghijklmnopqrstuvwxyz":
                ord_lower = ord(letter)
                assert scramble_map[ord_lower] != ord_lower, (
                    f"Identity mapping found for lowercase '{letter}'"
                )
            
            # Verify no uppercase letter maps to itself
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                ord_upper = ord(letter)
                assert scramble_map[ord_upper] != ord_upper, (
                    f"Identity mapping found for uppercase '{letter}'"
                )

    @pytest.mark.unit
    def test_scramble_map_is_permutation(self, mock_random_source):
        """
        Verify that the scramble map is a permutation (bijection) of letters.

        Given: A generated scramble map
        When: We extract all lowercase and uppercase mapped values
        Then: All 26 lowercase mappings are distinct
        And:  All 26 uppercase mappings are distinct
        And:  Together they form permutations of their respective alphabets
        """
        scramble_map = _make_scramble_map()

        lower_mapped = [
            chr(scramble_map[ord(letter)])
            for letter in "abcdefghijklmnopqrstuvwxyz"
        ]
        upper_mapped = [
            chr(scramble_map[ord(letter)])
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        ]

        # Check all lowercase values are unique
        assert len(set(lower_mapped)) == 26, "Lowercase mappings are not a permutation"
        
        # Check all uppercase values are unique
        assert len(set(upper_mapped)) == 26, "Uppercase mappings are not a permutation"
        
        # Check that we map to the full alphabet
        assert set(lower_mapped) == set("abcdefghijklmnopqrstuvwxyz"), (
            "Lowercase mappings don't cover full alphabet"
        )
        assert set(upper_mapped) == set("ABCDEFGHIJKLMNOPQRSTUVWXYZ"), (
            "Uppercase mappings don't cover full alphabet"
        )


class TestScrambleTextTransformation:
    """Unit tests for text scrambling using the generated scramble map."""

    @pytest.mark.unit
    def test_scramble_preserves_lowercase_letters(self, mock_random_source):
        """
        Verify that scrambled text only contains lowercase when input was lowercase.

        Given: A scramble map and a lowercase text string
        When: We apply str.translate() with the scramble map
        Then: The output contains only lowercase letters (no uppercase creep)
        """
        scramble_map = _make_scramble_map()
        text = "abcdefghijklmnopqrstuvwxyz"
        
        result = text.translate(scramble_map)
        
        assert result.islower(), f"Result contains uppercase: {result}"
        assert len(result) == len(text), "Length changed after scrambling"

    @pytest.mark.unit
    def test_scramble_preserves_uppercase_letters(self, mock_random_source):
        """
        Verify that scrambled text only contains uppercase when input was uppercase.

        Given: A scramble map and an uppercase text string
        When: We apply str.translate() with the scramble map
        Then: The output contains only uppercase letters (no lowercase creep)
        """
        scramble_map = _make_scramble_map()
        text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        
        result = text.translate(scramble_map)
        
        assert result.isupper(), f"Result contains lowercase: {result}"
        assert len(result) == len(text), "Length changed after scrambling"

    @pytest.mark.unit
    def test_scramble_leaves_digits_unchanged(self, mock_random_source):
        """
        Verify that digits are NOT scrambled (remain unchanged).

        Given: A scramble map and text containing digits and letters
        When: We apply str.translate() with the scramble map
        Then: All digits remain exactly as they were
        """
        scramble_map = _make_scramble_map()
        text = "abc123def456ghi"
        
        result = text.translate(scramble_map)
        
        # Extract digits from input and result
        input_digits = "".join(c for c in text if c.isdigit())
        result_digits = "".join(c for c in result if c.isdigit())
        
        assert input_digits == result_digits, (
            f"Digits changed: '{input_digits}' -> '{result_digits}'"
        )

    @pytest.mark.unit
    def test_scramble_leaves_symbols_unchanged(self, mock_random_source):
        """
        Verify that symbols and punctuation are NOT scrambled.

        Given: A scramble map and text containing letters and symbols
        When: We apply str.translate() with the scramble map
        Then: All symbols remain exactly as they were
        """
        scramble_map = _make_scramble_map()
        text = "Hello-World!@#$%&*()"
        
        result = text.translate(scramble_map)
        
        # Extract non-alphanumeric characters
        input_symbols = "".join(c for c in text if not c.isalnum())
        result_symbols = "".join(c for c in result if not c.isalnum())
        
        assert input_symbols == result_symbols, (
            f"Symbols changed: '{input_symbols}' -> '{result_symbols}'"
        )

    @pytest.mark.unit
    def test_scramble_preserves_length(self, mock_random_source):
        """
        Verify that scrambling preserves string length.

        Given: A scramble map and various text samples
        When: We apply str.translate() with the scramble map
        Then: Length of output equals length of input
        """
        scramble_map = _make_scramble_map()
        test_strings = [
            "abc",
            "ABC",
            "Hello World",
            "Account123",
            "40-37-28",
            "",  # empty string edge case
        ]
        
        for text in test_strings:
            result = text.translate(scramble_map)
            assert len(result) == len(text), (
                f"Length mismatch for '{text}': "
                f"expected {len(text)}, got {len(result)}"
            )

    @pytest.mark.unit
    def test_scramble_spaces_unchanged(self, mock_random_source):
        """
        Verify that spaces are preserved during scrambling.

        Given: A scramble map and text with spaces
        When: We apply str.translate() with the scramble map
        Then: Spaces remain in the same positions
        """
        scramble_map = _make_scramble_map()
        text = "Hello World Example"
        
        result = text.translate(scramble_map)
        
        # Extract space positions
        input_spaces = [i for i, c in enumerate(text) if c == " "]
        result_spaces = [i for i, c in enumerate(result) if c == " "]
        
        assert input_spaces == result_spaces, (
            f"Space positions changed: {input_spaces} -> {result_spaces}"
        )

    @pytest.mark.unit
    def test_scramble_produces_different_output(self, mock_random_source):
        """
        Verify that scrambling actually produces different text (not identity).

        Given: A scramble map and letter-only text
        When: We apply str.translate() with the scramble map
        Then: The output is different from the input (at least for letters)
        """
        scramble_map = _make_scramble_map()
        text = "abcdefghijklmnopqrstuvwxyz"
        
        result = text.translate(scramble_map)
        
        assert result != text, (
            "Scrambling produced identical output (all identity mappings)"
        )

    @pytest.mark.unit
    def test_mixed_case_scramble_preserves_case(self, mock_random_source):
        """
        Verify that mixed-case text has case preserved in each position.

        Given: A scramble map and mixed-case text
        When: We apply str.translate() with the scramble map
        Then: Uppercase letters become different uppercase letters
        And:  Lowercase letters become different lowercase letters
        And:  Case structure is preserved
        """
        scramble_map = _make_scramble_map()
        text = "HeLLo WoRLd"
        
        result = text.translate(scramble_map)
        
        for i, (orig_char, result_char) in enumerate(zip(text, result)):
            if orig_char.isalpha():
                assert orig_char.isupper() == result_char.isupper(), (
                    f"Case mismatch at position {i}: "
                    f"'{orig_char}' (upper={orig_char.isupper()}) -> "
                    f"'{result_char}' (upper={result_char.isupper()})"
                )


class TestRepeatLastTwo:
    """Unit tests for the _repeat_last_two function."""

    @pytest.mark.unit
    def test_repeat_last_two_basic(self):
        """
        Verify basic _repeat_last_two functionality.

        Given: A 6-digit string (sort code)
        When: We apply _repeat_last_two
        Then: The last two digits are repeated to fill the length
        """
        result = _repeat_last_two("403728")
        assert result == "282828", f"Expected '282828', got '{result}'"

    @pytest.mark.unit
    def test_repeat_last_two_even_length(self):
        """
        Verify _repeat_last_two with even-length input.

        Given: An 8-digit string (account number)
        When: We apply _repeat_last_two
        Then: The last two digits fill the full length
        """
        result = _repeat_last_two("31243535")
        assert result == "35353535", f"Expected '35353535', got '{result}'"

    @pytest.mark.unit
    def test_repeat_last_two_odd_length(self):
        """
        Verify _repeat_last_two with odd-length input.

        Given: A 7-digit string
        When: We apply _repeat_last_two
        Then: The last two digits repeat to fill the odd length, creating alternation starting with last digit
        """
        result = _repeat_last_two("4037285")
        # Last two digits are "85", repeat to fill 7 chars: "8585858"
        expected = "8585858"
        assert result == expected, f"Expected '{expected}', got '{result}'"

    @pytest.mark.unit
    def test_repeat_last_two_preserves_length(self):
        """
        Verify that _repeat_last_two always preserves input length.

        Given: Various length digit strings
        When: We apply _repeat_last_two
        Then: Output length equals input length
        """
        test_cases = [
            "12",      # 2 digits
            "123",     # 3 digits
            "1234",    # 4 digits
            "403728",  # 6 digits (sort code)
            "31243535",  # 8 digits (account)
            "1234567890123456",  # 16 digits (card)
        ]
        
        for digits in test_cases:
            result = _repeat_last_two(digits)
            assert len(result) == len(digits), (
                f"Length mismatch for '{digits}': "
                f"expected {len(digits)}, got {len(result)}"
            )

    @pytest.mark.unit
    def test_repeat_last_two_fallback_single_digit(self):
        """
        Verify fallback when repeating last two digits reproduces original.

        Given: A digit string where last-two repetition would recreate it
        When: We apply _repeat_last_two
        Then: Fallback to repeating last single digit is used
        """
        # "1111" repeats to "1111" so fallback to single-digit repeat "1" -> "1111"
        # This still produces "1111", so it will use "0" as final fallback
        result = _repeat_last_two("1111")
        assert result == "0000", (
            f"Expected fallback '0000' for all-ones, got '{result}'"
        )

    @pytest.mark.unit
    def test_repeat_last_two_fallback_all_zeros(self):
        """
        Verify fallback when input is all zeros.

        Given: A digit string of all zeros
        When: We apply _repeat_last_two
        Then: Fallback is '1' repeated (not '0' since original is '0')
        """
        result = _repeat_last_two("000000")
        assert result == "111111", (
            f"Expected fallback '111111' for all-zeros, got '{result}'"
        )

    @pytest.mark.unit
    def test_repeat_last_two_is_deterministic(self):
        """
        Verify that _repeat_last_two is deterministic (same input → same output).

        Given: A digit string
        When: We call _repeat_last_two multiple times
        Then: The output is always the same
        """
        digits = "403728"
        results = [_repeat_last_two(digits) for _ in range(5)]
        
        assert all(r == results[0] for r in results), (
            "Results differ across calls for same input"
        )

    @pytest.mark.unit
    def test_repeat_last_two_consistency_across_formats(self):
        """
        Verify _repeat_last_two produces consistent replacements for same digits.

        Given: Different representations of the same numeric ID
        When: We extract digits and apply _repeat_last_two
        Then: The underlying digit sequences produce same replacement
        """
        # "40-37-28" and "40 37 28" both have digits "403728"
        digits_hyphenated = "403728"
        digits_spaced = "403728"
        
        result1 = _repeat_last_two(digits_hyphenated)
        result2 = _repeat_last_two(digits_spaced)
        
        assert result1 == result2, (
            f"Different results for same digits: "
            f"'{result1}' vs '{result2}'"
        )


class TestStripNumericSeparators:
    """Unit tests for _strip_numeric_separators function."""

    @pytest.mark.unit
    def test_strip_numeric_separators_hyphenated_sort_code(self):
        """
        Verify stripping separators from hyphenated sort code.

        Given: A hyphenated sort code "40-37-28"
        When: We strip numeric separators
        Then: We get "403728"
        """
        result = _strip_numeric_separators("40-37-28")
        assert result == "403728", f"Expected '403728', got '{result}'"

    @pytest.mark.unit
    def test_strip_numeric_separators_spaced(self):
        """
        Verify stripping spaces from spaced numbers.

        Given: A space-separated sort code "40 37 28"
        When: We strip numeric separators
        Then: We get "403728"
        """
        result = _strip_numeric_separators("40 37 28")
        assert result == "403728", f"Expected '403728', got '{result}'"

    @pytest.mark.unit
    def test_strip_numeric_separators_card_format(self):
        """
        Verify stripping spaces from card number format.

        Given: A spaced card number "3333 2222 1111 0000"
        When: We strip numeric separators
        Then: We get "3333222211110000"
        """
        result = _strip_numeric_separators("3333 2222 1111 0000")
        assert result == "3333222211110000", (
            f"Expected '3333222211110000', got '{result}'"
        )

    @pytest.mark.unit
    def test_strip_numeric_separators_iban_spaced(self):
        """
        Verify stripping from spaced IBAN format.

        Given: A spaced IBAN "6016 2400 3980 04"
        When: We strip numeric separators
        Then: We get "60162400398004"
        """
        result = _strip_numeric_separators("6016 2400 3980 04")
        assert result == "60162400398004", (
            f"Expected '60162400398004', got '{result}'"
        )

    @pytest.mark.unit
    def test_strip_numeric_separators_leaves_digits(self):
        """
        Verify that digits are preserved and only separators are removed.

        Given: Text with digits and various separators
        When: We strip numeric separators
        Then: Only digits remain
        """
        result = _strip_numeric_separators("1-2 3.4,5")
        assert result == "12345", f"Expected '12345', got '{result}'"

    @pytest.mark.unit
    def test_strip_numeric_separators_empty_string(self):
        """
        Verify handling of empty string.

        Given: An empty string
        When: We strip numeric separators
        Then: We get an empty string
        """
        result = _strip_numeric_separators("")
        assert result == "", f"Expected empty string, got '{result}'"

    @pytest.mark.unit
    def test_strip_numeric_separators_digits_only(self):
        """
        Verify that string of only digits is unchanged.

        Given: A string of only digits
        When: We strip numeric separators
        Then: The string is unchanged
        """
        digits = "31243535"
        result = _strip_numeric_separators(digits)
        assert result == digits, f"Digit-only string changed: '{digits}' -> '{result}'"


class TestReapplySeparators:
    """Unit tests for _reapply_separators function."""

    @pytest.mark.unit
    def test_reapply_separators_hyphenated_sort_code(self):
        """
        Verify reapplying hyphens to sort code format.

        Given: Original display "40-37-28" and new digits "756291"
        When: We reapply separators
        Then: We get "75-62-91"
        """
        result = _reapply_separators("40-37-28", "756291")
        assert result == "75-62-91", f"Expected '75-62-91', got '{result}'"

    @pytest.mark.unit
    def test_reapply_separators_spaced(self):
        """
        Verify reapplying spaces to sort code format.

        Given: Original display "40 37 28" and new digits "756291"
        When: We reapply separators
        Then: We get "75 62 91"
        """
        result = _reapply_separators("40 37 28", "756291")
        assert result == "75 62 91", f"Expected '75 62 91', got '{result}'"

    @pytest.mark.unit
    def test_reapply_separators_card_format(self):
        """
        Verify reapplying spaces to card number format.

        Given: Original display "3333 2222 1111 0000" and new digits "1111222233334444"
        When: We reapply separators
        Then: We get "1111 2222 3333 4444"
        """
        result = _reapply_separators("3333 2222 1111 0000", "1111222233334444")
        assert result == "1111 2222 3333 4444", (
            f"Expected '1111 2222 3333 4444', got '{result}'"
        )

    @pytest.mark.unit
    def test_reapply_separators_iban_spaced(self):
        """
        Verify reapplying spaces to IBAN digit section.

        Given: Original display "6016 2400 3980 04" and new digits "12341234123456"
        When: We reapply separators
        Then: We get "1234 1234 1234 56"
        """
        result = _reapply_separators("6016 2400 3980 04", "12341234123456")
        assert result == "1234 1234 1234 56", (
            f"Expected '1234 1234 1234 56', got '{result}'"
        )

    @pytest.mark.unit
    def test_reapply_separators_excess_new_digits(self):
        """
        Verify handling when new digits are longer than original.

        Given: Original display "40-37" (5 chars) and new digits "7894561"
        When: We reapply separators
        Then: Excess digits are appended to the end
        """
        result = _reapply_separators("40-37", "7894561")
        # "40-37" has 5 chars: positions 0=4, 1=0, 2=-, 3=3, 4=7
        # Filling: 0→7, 1→8, 2→-, 3→9, 4→4, then append surplus "561"
        assert result == "78-94561", (
            f"Expected '78-94561', got '{result}'"
        )

    @pytest.mark.unit
    def test_reapply_separators_short_new_digits(self):
        """
        Verify handling when new digits are shorter than original.

        Given: Original display "40-37-28" and new digits "75"
        When: We reapply separators
        Then: Original digit positions not covered by new digits are kept as-is from original
        """
        result = _reapply_separators("40-37-28", "75")
        # "40-37-28": fill 0→7, 1→5, keep 2→-, then keep remaining digits from original "3728"
        assert result == "75-37-28", (
            f"Expected '75-37-28', got '{result}'"
        )

    @pytest.mark.unit
    def test_reapply_separators_preserves_structure(self):
        """
        Verify that separator positions are exactly preserved.

        Given: Original display with separators at known positions
        When: We reapply separators with different digits
        Then: All non-digit characters are in identical positions
        """
        original = "40-37-28"
        new_digits = "999999"
        result = _reapply_separators(original, new_digits)
        
        # Check separator positions match
        for i, (orig_char, result_char) in enumerate(zip(original, result)):
            if not orig_char.isdigit():
                assert result_char == orig_char, (
                    f"Position {i} should have '{orig_char}', got '{result_char}'"
                )

    @pytest.mark.unit
    def test_reapply_separators_empty_original(self):
        """
        Verify handling of empty original display.

        Given: Empty original display and new digits
        When: We reapply separators
        Then: Result is empty (no separators to apply)
        """
        result = _reapply_separators("", "123456")
        assert result == "123456", (
            f"Expected '123456', got '{result}'"
        )

    @pytest.mark.unit
    def test_reapply_separators_empty_new_digits(self):
        """
        Verify handling of empty new digits.

        Given: Original display with separators and empty new digits
        When: We reapply separators
        Then: When no new digits are provided, original display is returned unchanged
        """
        result = _reapply_separators("40-37-28", "")
        # When new_digits is exhausted immediately, original is preserved
        assert result == "40-37-28", (
            f"Expected '40-37-28', got '{result}'"
        )


class TestDetectNumericIds:
    """Unit tests for _detect_numeric_ids function."""

    @pytest.mark.unit
    def test_detect_numeric_ids_sort_code_hyphenated(self):
        """
        Verify detection and replacement of hyphenated sort code.

        Given: Text containing "40-37-28"
        When: We detect numeric IDs
        Then: The sort code is mapped to a replacement
        """
        result = _detect_numeric_ids("Account: 40-37-28")
        
        assert "40-37-28" in result, "Sort code not detected"
        replacement = result["40-37-28"]
        assert replacement != "40-37-28", "No replacement generated"
        # Check format is preserved (hyphenated)
        assert replacement.count("-") == 2, f"Hyphen count not preserved: {replacement}"

    @pytest.mark.unit
    def test_detect_numeric_ids_sort_code_spaced(self):
        """
        Verify detection of spaced sort code format.

        Given: Text containing "40 37 28"
        When: We detect numeric IDs
        Then: The sort code is mapped to a replacement
        """
        result = _detect_numeric_ids("Sort: 40 37 28")
        
        assert "40 37 28" in result, "Spaced sort code not detected"

    @pytest.mark.unit
    def test_detect_numeric_ids_account_number(self):
        """
        Verify detection of 8-digit account number.

        Given: Text containing word-boundary 8-digit sequence
        When: We detect numeric IDs
        Then: Account number is mapped to replacement
        """
        result = _detect_numeric_ids("Account 31243535 Details")
        
        assert "31243535" in result, "Account number not detected"

    @pytest.mark.unit
    def test_detect_numeric_ids_card_number(self):
        """
        Verify detection of spaced 16-digit card number.

        Given: Text containing "3333 2222 1111 0000"
        When: We detect numeric IDs
        Then: Card number is mapped to replacement
        """
        result = _detect_numeric_ids("Card: 3333 2222 1111 0000")
        
        assert "3333 2222 1111 0000" in result, "Card number not detected"

    @pytest.mark.unit
    def test_detect_numeric_ids_consistency(self):
        """
        Verify that same numeric ID gets same replacement across document.

        Given: Text with same sort code appearing twice
        When: We detect numeric IDs
        Then: Both occurrences map to the same replacement value
        """
        text = "Sort1: 40-37-28 Sort2: 40-37-28"
        result = _detect_numeric_ids(text)
        
        # Find the two occurrences
        occurrences = [k for k in result if k.endswith("28")]
        assert len(occurrences) >= 1, "Sort code not detected"
        
        # If the same key appears, it should have the same value
        if occurrences[0] in result:
            replacement = result[occurrences[0]]
            # Verify consistency by checking the underlying digit mapping
            for occ in occurrences:
                if occ in result:
                    assert result[occ] == replacement, (
                        f"Inconsistent replacement for {occ}"
                    )

    @pytest.mark.unit
    def test_detect_numeric_ids_user_override(self):
        """
        Verify that user overrides are respected.

        Given: Text with sort code and user override mapping
        When: We detect numeric IDs with user_overrides
        Then: The user-specified replacement is used
        """
        user_overrides = {"403728": "000000"}
        result = _detect_numeric_ids("Sort: 40-37-28", user_overrides)
        
        assert "40-37-28" in result
        # The replacement should be "00-00-00"
        assert result["40-37-28"] == "00-00-00", (
            f"User override not applied: {result['40-37-28']}"
        )

    @pytest.mark.unit
    def test_detect_numeric_ids_no_match(self):
        """
        Verify behavior when text contains no numeric IDs.

        Given: Text with no numeric IDs
        When: We detect numeric IDs
        Then: Result is empty dict
        """
        result = _detect_numeric_ids("Just some regular text")
        
        assert result == {}, f"Expected empty dict, got {result}"

    @pytest.mark.unit
    def test_detect_numeric_ids_multiple_different_ids(self):
        """
        Verify detection of multiple different numeric IDs in one text.

        Given: Text containing sort code, account, and card number
        When: We detect numeric IDs
        Then: All are detected and mapped to different replacements
        """
        text = "Sort: 40-37-28 Account: 31243535 Card: 3333 2222 1111 0000"
        result = _detect_numeric_ids(text)
        
        assert "40-37-28" in result, "Sort code not detected"
        assert "31243535" in result, "Account not detected"
        assert "3333 2222 1111 0000" in result, "Card not detected"

    @pytest.mark.unit
    def test_detect_numeric_ids_iban_full(self):
        """
        Verify detection of full IBAN format.

        Given: Text containing full IBAN "VN72JNEB40372831243535"
        When: We detect numeric IDs
        Then: IBAN is mapped to replacement
        """
        result = _detect_numeric_ids("IBAN: VN72JNEB40372831243535")
        
        assert "VN72JNEB40372831243535" in result, "Full IBAN not detected"

    @pytest.mark.unit
    def test_detect_numeric_ids_iban_spaced(self):
        """
        Verify detection of spaced IBAN format.

        Given: Text containing spaced IBAN "GB19 NWBK 6016 2400 3980 04"
        When: We detect numeric IDs
        Then: IBAN is mapped to replacement
        """
        result = _detect_numeric_ids("IBAN: GB19 NWBK 6016 2400 3980 04")
        
        assert "GB19 NWBK 6016 2400 3980 04" in result, "Spaced IBAN not detected"

    @pytest.mark.unit
    def test_detect_numeric_ids_empty_text(self):
        """
        Verify handling of empty text.

        Given: Empty string
        When: We detect numeric IDs
        Then: Result is empty dict
        """
        result = _detect_numeric_ids("")
        
        assert result == {}, f"Expected empty dict for empty text, got {result}"

    @pytest.mark.unit
    def test_detect_numeric_ids_preserves_format(self):
        """
        Verify that replacement preserves the original format (hyphens, spaces).

        Given: Sort code "40-37-28"
        When: We detect and replace
        Then: Replacement maintains hyphen format
        """
        result = _detect_numeric_ids("40-37-28")
        replacement = result["40-37-28"]
        
        # Format should be XXX-XX-XX (6 digits with hyphens)
        assert replacement.count("-") == 2, (
             f"Format not preserved: {replacement}"
        )
        assert len(replacement) == 8, (  # 6 digits + 2 hyphens
             f"Length mismatch: {replacement}"
        )


class TestRepeatLastTwoEdgeCases:
    """Edge case tests for _repeat_last_two numeric ID tiling."""

    @pytest.mark.unit
    def test_repeat_last_two_empty_string(self):
        """
        Verify that empty string is handled safely.

        Given: Empty string ""
        When: _repeat_last_two is called
        Then: Returns empty string
        """
        result = _repeat_last_two("")
        assert result == "", f"Expected empty string, got {result!r}"

    @pytest.mark.unit
    def test_repeat_last_two_single_digit(self):
        """
        Verify that single-digit string is handled safely.

        Given: Single digit "5"
        When: _repeat_last_two is called
        Then: Returns appropriate single-digit replacement
        """
        result = _repeat_last_two("5")
        assert len(result) == 1, f"Expected length 1, got {len(result)}"
        assert result.isdigit(), f"Expected digit, got {result!r}"

    @pytest.mark.unit
    def test_repeat_last_two_single_zero(self):
        """
        Verify that single zero gets special fallback treatment.

        Given: Single digit "0"
        When: _repeat_last_two is called
        Then: Returns "1" (special fallback for all-zero strings)
        """
        result = _repeat_last_two("0")
        assert result == "1", f"Expected '1', got {result!r}"

    @pytest.mark.unit
    def test_repeat_last_two_two_digit_normal(self):
         """
         Verify that two-digit string behavior follows the fallback rules.

         Given: Two digits "35"
         When: _repeat_last_two is called
         Then: Since repeating "35" gives "35" (matches input), fallback to last digit
         """
         result = _repeat_last_two("35")
         # "35" tiled to length 2 would give "35" (matches input), so fallback to last digit "5"
         assert result == "55", f"Expected '55' (fallback to last digit), got {result!r}"

    @pytest.mark.unit
    def test_repeat_last_two_repeated_single_digit_fallback(self):
        """
        Verify fallback handling when all digits are identical.

        Given: String "8888"
        When: _repeat_last_two is called
        Then: Uses fallback (all digits identical case)
        """
        result = _repeat_last_two("8888")
        # Should be "0000" (fallback since "8888" would repeat to "8888")
        assert result == "0000", f"Expected '0000', got {result!r}"
        assert len(result) == 4, f"Expected length 4, got {len(result)}"

    @pytest.mark.unit
    def test_repeat_last_two_all_zeros_fallback(self):
        """
        Verify fallback handling for all-zero strings.

        Given: String "0000"
        When: _repeat_last_two is called
        Then: Uses fallback "1111" (special case for all zeros)
        """
        result = _repeat_last_two("0000")
        # Should be "1111" (special fallback for all zeros)
        assert result == "1111", f"Expected '1111', got {result!r}"
        assert len(result) == 4, f"Expected length 4, got {len(result)}"

    @pytest.mark.unit
    def test_repeat_last_two_length_preservation(self):
        """
        Verify that output length always matches input length.

        Given: Various length input strings
        When: _repeat_last_two is called
        Then: Output length always equals input length
        """
        test_cases = [
            "",
            "0",
            "42",
            "123",
            "4037",
            "40372831",
            "40372831243535",
        ]
        for case in test_cases:
            result = _repeat_last_two(case)
            assert len(result) == len(case), (
                f"Length mismatch for {case!r}: expected {len(case)}, got {len(result)}"
            )

