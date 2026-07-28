"""
Unit tests for config loading in the bank_statement_anonymiser.

This module tests:
- _normalise_phrase(): lowercase, strip trailing colon, strip whitespace
- _AlwaysAnonymiseConfig / _NeverAnonymiseConfig dataclass construction
- _load_always_anonymise(): TOML read, user-wins-on-clash merge
- _load_never_anonymise(): TOML read, union merge, normalisation
- Bundled system TOML files: load without error and contain expected entries
"""

from __future__ import annotations

import pytest

from bank_statement_anonymiser.anonymise import (
    _AlwaysAnonymiseConfig,
    _NeverAnonymiseConfig,
    _load_always_anonymise,
    _load_never_anonymise,
    _normalise_phrase,
)


# ---------------------------------------------------------------------------
# Module 5: _normalise_phrase
# ---------------------------------------------------------------------------


class TestNormalisePhrase:
    """Tests for _normalise_phrase() — lowercase + strip colon + collapse whitespace."""

    @pytest.mark.unit
    def test_lowercase(self):
        assert _normalise_phrase("BALANCE") == "balance"

    @pytest.mark.unit
    def test_strips_trailing_colon(self):
        assert _normalise_phrase("Account number:") == "accountnumber"

    @pytest.mark.unit
    def test_strips_internal_whitespace(self):
        assert _normalise_phrase("Sort Code") == "sortcode"

    @pytest.mark.unit
    def test_strips_leading_trailing_whitespace(self):
        assert _normalise_phrase("  Balance  ") == "balance"

    @pytest.mark.unit
    def test_strips_colon_then_whitespace(self):
        """Trailing colon stripped after outer strip(); internal spaces also collapsed."""
        assert _normalise_phrase("  Account number:  ") == "accountnumber"

    @pytest.mark.unit
    def test_multiple_words_collapsed(self):
        assert _normalise_phrase("Balance Brought Forward") == "balancebroughtforward"

    @pytest.mark.unit
    def test_empty_string(self):
        assert _normalise_phrase("") == ""

    @pytest.mark.unit
    def test_only_whitespace(self):
        assert _normalise_phrase("   ") == ""

    @pytest.mark.unit
    def test_single_char(self):
        assert _normalise_phrase("A") == "a"

    @pytest.mark.unit
    def test_non_trailing_colon_preserved(self):
        """A colon in the middle of a phrase (not trailing) is kept."""
        result = _normalise_phrase("10:30")
        assert ":" in result

    @pytest.mark.unit
    def test_tabs_and_newlines_stripped(self):
        assert _normalise_phrase("account\tnumber\n") == "accountnumber"


# ---------------------------------------------------------------------------
# Module 5: _AlwaysAnonymiseConfig and _NeverAnonymiseConfig dataclasses
# ---------------------------------------------------------------------------


class TestConfigDataclasses:
    """Direct construction and attribute access for the config dataclasses."""

    @pytest.mark.unit
    def test_always_anonymise_config_stores_replacements(self):
        cfg = _AlwaysAnonymiseConfig(replacements={"John Doe": "Jane Smith"})
        assert cfg.replacements == {"John Doe": "Jane Smith"}

    @pytest.mark.unit
    def test_always_anonymise_config_is_frozen(self):
        cfg = _AlwaysAnonymiseConfig(replacements={})
        with pytest.raises((AttributeError, TypeError)):
            cfg.replacements = {"new": "value"}  # type: ignore[misc]

    @pytest.mark.unit
    def test_never_anonymise_config_stores_phrases(self):
        phrases = frozenset(["balance", "sortcode"])
        cfg = _NeverAnonymiseConfig(phrases=phrases)
        assert cfg.phrases == phrases

    @pytest.mark.unit
    def test_never_anonymise_config_is_frozen(self):
        cfg = _NeverAnonymiseConfig(phrases=frozenset())
        with pytest.raises((AttributeError, TypeError)):
            cfg.phrases = frozenset(["x"])  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Module 5: _load_always_anonymise
# ---------------------------------------------------------------------------


class TestLoadAlwaysAnonymise:
    """Tests for _load_always_anonymise() — flat TOML merge, user wins on clash."""

    @pytest.mark.unit
    def test_returns_always_anonymise_config_instance(self, tmp_path):
        system = tmp_path / "sys.toml"
        system.write_text('', encoding="utf-8")
        result = _load_always_anonymise(system_path=system, user_path=None)
        assert isinstance(result, _AlwaysAnonymiseConfig)

    @pytest.mark.unit
    def test_loads_system_rules(self, tmp_path):
        system = tmp_path / "sys.toml"
        system.write_bytes(b'"John Doe" = "Jane Smith"\n')
        result = _load_always_anonymise(system_path=system, user_path=None)
        assert result.replacements["John Doe"] == "Jane Smith"

    @pytest.mark.unit
    def test_user_path_none_returns_system_only(self, tmp_path):
        system = tmp_path / "sys.toml"
        system.write_bytes(b'"A" = "B"\n')
        result = _load_always_anonymise(system_path=system, user_path=None)
        assert list(result.replacements.keys()) == ["A"]

    @pytest.mark.unit
    def test_user_overrides_system_on_clash(self, tmp_path):
        system = tmp_path / "sys.toml"
        user = tmp_path / "usr.toml"
        system.write_bytes(b'"name" = "system_value"\n')
        user.write_bytes(b'"name" = "user_value"\n')
        result = _load_always_anonymise(system_path=system, user_path=user)
        assert result.replacements["name"] == "user_value"

    @pytest.mark.unit
    def test_user_adds_new_keys(self, tmp_path):
        system = tmp_path / "sys.toml"
        user = tmp_path / "usr.toml"
        system.write_bytes(b'"sys_key" = "sys_val"\n')
        user.write_bytes(b'"usr_key" = "usr_val"\n')
        result = _load_always_anonymise(system_path=system, user_path=user)
        assert "sys_key" in result.replacements
        assert "usr_key" in result.replacements

    @pytest.mark.unit
    def test_missing_system_file_returns_empty(self, tmp_path):
        system = tmp_path / "nonexistent_sys.toml"
        result = _load_always_anonymise(system_path=system, user_path=None)
        assert result.replacements == {}

    @pytest.mark.unit
    def test_missing_user_file_gracefully_skipped(self, tmp_path):
        system = tmp_path / "sys.toml"
        system.write_bytes(b'"k" = "v"\n')
        user = tmp_path / "nonexistent_user.toml"
        result = _load_always_anonymise(system_path=system, user_path=user)
        assert result.replacements == {"k": "v"}

    @pytest.mark.unit
    def test_non_string_values_ignored(self, tmp_path):
        """Only top-level string values are kept; integers/lists are ignored."""
        system = tmp_path / "sys.toml"
        system.write_bytes(b'"valid" = "kept"\nnumeric = 42\n')
        result = _load_always_anonymise(system_path=system, user_path=None)
        assert "valid" in result.replacements
        assert "numeric" not in result.replacements

    @pytest.mark.unit
    def test_empty_system_file_returns_empty(self, tmp_path):
        system = tmp_path / "sys.toml"
        system.write_bytes(b'')
        result = _load_always_anonymise(system_path=system, user_path=None)
        assert result.replacements == {}

    @pytest.mark.unit
    def test_multiple_system_rules_all_loaded(self, tmp_path):
        system = tmp_path / "sys.toml"
        system.write_bytes(b'"A" = "X"\n"B" = "Y"\n"C" = "Z"\n')
        result = _load_always_anonymise(system_path=system, user_path=None)
        assert len(result.replacements) == 3


# ---------------------------------------------------------------------------
# Module 5: _load_never_anonymise
# ---------------------------------------------------------------------------


class TestLoadNeverAnonymise:
    """Tests for _load_never_anonymise() — union merge of exclude lists."""

    @pytest.mark.unit
    def test_returns_never_anonymise_config_instance(self, tmp_path):
        system = tmp_path / "sys.toml"
        system.write_text('exclude = []\n', encoding="utf-8")
        result = _load_never_anonymise(system_path=system, user_path=None)
        assert isinstance(result, _NeverAnonymiseConfig)

    @pytest.mark.unit
    def test_phrases_are_frozenset(self, tmp_path):
        system = tmp_path / "sys.toml"
        system.write_bytes(b'exclude = ["Balance"]\n')
        result = _load_never_anonymise(system_path=system, user_path=None)
        assert isinstance(result.phrases, frozenset)

    @pytest.mark.unit
    def test_phrases_are_normalised(self, tmp_path):
        system = tmp_path / "sys.toml"
        system.write_bytes(b'exclude = ["Account Number:"]\n')
        result = _load_never_anonymise(system_path=system, user_path=None)
        assert "accountnumber" in result.phrases

    @pytest.mark.unit
    def test_user_phrases_added_to_system(self, tmp_path):
        system = tmp_path / "sys.toml"
        user = tmp_path / "usr.toml"
        system.write_bytes(b'exclude = ["Balance"]\n')
        user.write_bytes(b'exclude = ["Reference"]\n')
        result = _load_never_anonymise(system_path=system, user_path=user)
        assert "balance" in result.phrases
        assert "reference" in result.phrases

    @pytest.mark.unit
    def test_duplicate_phrases_deduplicated(self, tmp_path):
        system = tmp_path / "sys.toml"
        user = tmp_path / "usr.toml"
        system.write_bytes(b'exclude = ["Balance"]\n')
        user.write_bytes(b'exclude = ["Balance"]\n')
        result = _load_never_anonymise(system_path=system, user_path=user)
        # frozenset guarantees no duplicates; normalised form appears exactly once
        assert "balance" in result.phrases
        assert len([p for p in result.phrases if p == "balance"]) == 1

    @pytest.mark.unit
    def test_whitespace_only_entries_filtered(self, tmp_path):
        system = tmp_path / "sys.toml"
        system.write_bytes(b'exclude = ["   ", "Balance"]\n')
        result = _load_never_anonymise(system_path=system, user_path=None)
        assert "" not in result.phrases
        assert "balance" in result.phrases

    @pytest.mark.unit
    def test_missing_exclude_key_returns_empty(self, tmp_path):
        system = tmp_path / "sys.toml"
        system.write_bytes(b'# no exclude key\n')
        result = _load_never_anonymise(system_path=system, user_path=None)
        assert len(result.phrases) == 0

    @pytest.mark.unit
    def test_missing_system_file_returns_empty(self, tmp_path):
        system = tmp_path / "nonexistent.toml"
        result = _load_never_anonymise(system_path=system, user_path=None)
        assert len(result.phrases) == 0

    @pytest.mark.unit
    def test_missing_user_file_gracefully_skipped(self, tmp_path):
        system = tmp_path / "sys.toml"
        system.write_bytes(b'exclude = ["Balance"]\n')
        user = tmp_path / "nonexistent_user.toml"
        result = _load_never_anonymise(system_path=system, user_path=user)
        assert "balance" in result.phrases

    @pytest.mark.unit
    def test_user_path_none_returns_system_only(self, tmp_path):
        system = tmp_path / "sys.toml"
        system.write_bytes(b'exclude = ["Balance", "Date"]\n')
        result = _load_never_anonymise(system_path=system, user_path=None)
        assert "balance" in result.phrases
        assert "date" in result.phrases


# ---------------------------------------------------------------------------
# Module 5: Bundled system TOML integration
# ---------------------------------------------------------------------------


class TestBundledSystemToml:
    """Integration smoke-tests: the bundled TOML files load without error."""

    @pytest.mark.unit
    def test_bundled_always_anonymise_loads(self):
        """always_anonymise_system.toml must load cleanly (currently empty)."""
        from bank_statement_anonymiser.anonymise import _bundled_path
        path = _bundled_path("always_anonymise_system.toml")
        result = _load_always_anonymise(system_path=path, user_path=None)
        assert isinstance(result, _AlwaysAnonymiseConfig)

    @pytest.mark.unit
    def test_bundled_never_anonymise_loads(self):
        """never_anonymise_system.toml must load cleanly."""
        from bank_statement_anonymiser.anonymise import _bundled_path
        path = _bundled_path("never_anonymise_system.toml")
        result = _load_never_anonymise(system_path=path, user_path=None)
        assert isinstance(result, _NeverAnonymiseConfig)

    @pytest.mark.unit
    def test_bundled_never_anonymise_contains_dd(self):
        """'DD' (Direct Debit code) must be present in bundled never_anonymise."""
        from bank_statement_anonymiser.anonymise import _bundled_path
        path = _bundled_path("never_anonymise_system.toml")
        result = _load_never_anonymise(system_path=path, user_path=None)
        assert "dd" in result.phrases

    @pytest.mark.unit
    def test_bundled_never_anonymise_contains_balance_brought_forward(self):
        """'Balance Brought Forward' must be present in bundled never_anonymise."""
        from bank_statement_anonymiser.anonymise import _bundled_path
        path = _bundled_path("never_anonymise_system.toml")
        result = _load_never_anonymise(system_path=path, user_path=None)
        assert "balancebroughtforward" in result.phrases

    @pytest.mark.unit
    def test_bundled_never_anonymise_contains_bp(self):
        """'BP' (Bill Payment code) must be in bundled never_anonymise."""
        from bank_statement_anonymiser.anonymise import _bundled_path
        path = _bundled_path("never_anonymise_system.toml")
        result = _load_never_anonymise(system_path=path, user_path=None)
        assert "bp" in result.phrases

    @pytest.mark.unit
    def test_bundled_never_anonymise_has_many_entries(self):
        """Bundled system file should provide a substantial list of protected phrases."""
        from bank_statement_anonymiser.anonymise import _bundled_path
        path = _bundled_path("never_anonymise_system.toml")
        result = _load_never_anonymise(system_path=path, user_path=None)
        assert len(result.phrases) >= 10


class TestNormalisePhrasEdgeCases:
    """Edge case tests for _normalise_phrase robustness."""

    @pytest.mark.unit
    def test_normalise_phrase_empty_string(self):
        """
        Verify that empty string returns empty string.

        Given: Empty string ""
        When: _normalise_phrase is called
        Then: Returns empty string
        """
        result = _normalise_phrase("")
        assert result == "", f"Expected empty string, got {result!r}"

    @pytest.mark.unit
    def test_normalise_phrase_whitespace_only(self):
        """
        Verify that whitespace-only string returns empty string.

        Given: Whitespace-only string "   "
        When: _normalise_phrase is called
        Then: Returns empty string (stripped away)
        """
        result = _normalise_phrase("   ")
        assert result == "", f"Expected empty string, got {result!r}"

    @pytest.mark.unit
    def test_normalise_phrase_none_handled_safely(self):
        """
        Verify that None input is handled safely without crashing.

        Given: None value
        When: _normalise_phrase is called
        Then: Returns empty string (defensive check)
        """
        # The implementation should check for None or non-string
        result = _normalise_phrase(None)  # type: ignore
        assert result == "", f"Expected empty string for None, got {result!r}"

    @pytest.mark.unit
    def test_normalise_phrase_colon_only(self):
        """
        Verify that colon-only string returns empty string.

        Given: Colon-only string ":"
        When: _normalise_phrase is called
        Then: Returns empty string (stripped as trailing colon + all whitespace)
        """
        result = _normalise_phrase(":")
        assert result == "", f"Expected empty string, got {result!r}"

    @pytest.mark.unit
    def test_normalise_phrase_multiple_colons(self):
        """
        Verify that multiple colons are only stripped from end.

        Given: String "Balance::"
        When: _normalise_phrase is called
        Then: Strips all trailing colons correctly
        """
        result = _normalise_phrase("Balance::")
        assert result == "balance", f"Expected 'balance', got {result!r}"

    @pytest.mark.unit
    def test_normalise_phrase_mixed_whitespace(self):
        """
        Verify that tabs and newlines are handled correctly.

        Given: String with tabs and newlines "Balance\t\nForward"
        When: _normalise_phrase is called
        Then: All internal whitespace removed
        """
        result = _normalise_phrase("Balance\t\nForward")
        assert result == "balanceforward", f"Expected 'balanceforward', got {result!r}"

    """Edge case tests for _normalise_phrase robustness."""

    @pytest.mark.unit
    def test_normalise_phrase_empty_string(self):
        """
        Verify that empty string returns empty string.

        Given: Empty string ""
        When: _normalise_phrase is called
        Then: Returns empty string
        """
        result = _normalise_phrase("")
        assert result == "", f"Expected empty string, got {result!r}"

    @pytest.mark.unit
    def test_normalise_phrase_whitespace_only(self):
        """
        Verify that whitespace-only string returns empty string.

        Given: Whitespace-only string "   "
        When: _normalise_phrase is called
        Then: Returns empty string (stripped away)
        """
        result = _normalise_phrase("   ")
        assert result == "", f"Expected empty string, got {result!r}"

    @pytest.mark.unit
    def test_normalise_phrase_none_handled_safely(self):
        """
        Verify that None input is handled safely without crashing.

        Given: None value
        When: _normalise_phrase is called
        Then: Returns empty string (defensive check)
        """
        # The implementation should check for None or non-string
        result = _normalise_phrase(None)  # type: ignore
        assert result == "", f"Expected empty string for None, got {result!r}"

    @pytest.mark.unit
    def test_normalise_phrase_colon_only(self):
        """
        Verify that colon-only string returns empty string.

        Given: Colon-only string ":"
        When: _normalise_phrase is called
        Then: Returns empty string (stripped as trailing colon + all whitespace)
        """
        result = _normalise_phrase(":")
        assert result == "", f"Expected empty string, got {result!r}"

    @pytest.mark.unit
    def test_normalise_phrase_multiple_colons(self):
        """
        Verify that multiple colons are only stripped from end.

        Given: String "Balance::"
        When: _normalise_phrase is called
        Then: Strips all trailing colons correctly
        """
        result = _normalise_phrase("Balance::")
        assert result == "balance", f"Expected 'balance', got {result!r}"

    @pytest.mark.unit
    def test_normalise_phrase_mixed_whitespace(self):
        """
        Verify that tabs and newlines are handled correctly.

        Given: String with tabs and newlines "Balance\t\nForward"
        When: _normalise_phrase is called
        Then: All internal whitespace removed
        """
        result = _normalise_phrase("Balance\t\nForward")
        assert result == "balanceforward", f"Expected 'balanceforward', got {result!r}"

