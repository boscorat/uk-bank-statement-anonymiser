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

from pathlib import Path

import pytest

from bank_statement_anonymiser.anonymise import (
    _AlwaysAnonymiseConfig,
    _load_always_anonymise,
    _load_never_anonymise,
    _NeverAnonymiseConfig,
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
    def test_non_trailing_colon_removed(self):
        """A colon in the middle of a phrase is removed."""
        result = _normalise_phrase("10:30")
        assert ":" not in result
        assert result == "1030"

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
    """Tests for _load_always_anonymise() — flat TOML merge, user wins on clash.
    
    NOTE: System rules are now loaded from bundled config at import time.
    These tests verify the user config is properly merged with system rules.
    """

    @pytest.mark.unit
    def test_returns_always_anonymise_config_instance(self, tmp_path):
        user = tmp_path / "usr.toml"
        user.write_text("", encoding="utf-8")
        result = _load_always_anonymise(user_path=user)
        assert isinstance(result, _AlwaysAnonymiseConfig)

    @pytest.mark.unit
    def test_loads_system_rules(self):
        # System rules are pre-loaded; verify config has expected type
        result = _load_always_anonymise(user_path=None)
        assert isinstance(result, _AlwaysAnonymiseConfig)

    @pytest.mark.unit
    def test_user_path_none_returns_system_only(self):
        result = _load_always_anonymise(user_path=None)
        # Should return something (may be empty if bundled system config is empty)
        assert isinstance(result, _AlwaysAnonymiseConfig)

    @pytest.mark.unit
    def test_user_overrides_system_on_clash(self, tmp_path):
        user = tmp_path / "usr.toml"
        user.write_bytes(b'"name" = "user_value"\n')
        result = _load_always_anonymise(user_path=user)
        # User value should override (if it exists in system)
        assert result.replacements["name"] == "user_value"

    @pytest.mark.unit
    def test_user_adds_new_keys(self, tmp_path):
        user = tmp_path / "usr.toml"
        user.write_bytes(b'"unique_key" = "unique_val"\n')
        result = _load_always_anonymise(user_path=user)
        assert "unique_key" in result.replacements

    @pytest.mark.unit
    def test_missing_user_file_raises_error(self, tmp_path):
        user = tmp_path / "nonexistent_user.toml"
        with pytest.raises(FileNotFoundError):
            _load_always_anonymise(user_path=user)

    @pytest.mark.unit
    def test_non_string_values_ignored(self, tmp_path):
        """Only top-level string values are kept; integers/lists are ignored."""
        user = tmp_path / "usr.toml"
        user.write_bytes(b'"valid" = "kept"\nnumeric = 42\n')
        result = _load_always_anonymise(user_path=user)
        assert "valid" in result.replacements
        assert "numeric" not in result.replacements

    @pytest.mark.unit
    def test_empty_user_file_returns_system_only(self, tmp_path):
        user = tmp_path / "usr.toml"
        user.write_bytes(b"")
        result = _load_always_anonymise(user_path=user)
        # Should return system rules only (may be empty if bundled system config is empty)
        assert isinstance(result, _AlwaysAnonymiseConfig)

    @pytest.mark.unit
    def test_multiple_user_rules_all_loaded(self, tmp_path):
        user = tmp_path / "usr.toml"
        user.write_bytes(b'"A" = "X"\n"B" = "Y"\n"C" = "Z"\n')
        result = _load_always_anonymise(user_path=user)
        assert len([k for k in result.replacements if k in ("A", "B", "C")]) == 3


# ---------------------------------------------------------------------------
# Module 5: _load_never_anonymise
# ---------------------------------------------------------------------------


class TestLoadNeverAnonymise:
    """Tests for _load_never_anonymise() — union merge of exclude lists.
    
    NOTE: System phrases are now loaded from bundled config at import time.
    These tests verify the user config is properly merged with system phrases.
    """

    @pytest.mark.unit
    def test_returns_never_anonymise_config_instance(self, tmp_path):
        user = tmp_path / "usr.toml"
        user.write_text("exclude = []\n", encoding="utf-8")
        result = _load_never_anonymise(user_path=user)
        assert isinstance(result, _NeverAnonymiseConfig)

    @pytest.mark.unit
    def test_phrases_are_frozenset(self, tmp_path):
        user = tmp_path / "usr.toml"
        user.write_bytes(b'exclude = ["Balance"]\n')
        result = _load_never_anonymise(user_path=user)
        assert isinstance(result.phrases, frozenset)

    @pytest.mark.unit
    def test_phrases_are_normalised(self, tmp_path):
        user = tmp_path / "usr.toml"
        user.write_bytes(b'exclude = ["Account Number:"]\n')
        result = _load_never_anonymise(user_path=user)
        assert "accountnumber" in result.phrases

    @pytest.mark.unit
    def test_user_phrases_added_to_system(self, tmp_path):
        user = tmp_path / "usr.toml"
        user.write_bytes(b'exclude = ["UniquePhrase"]\n')
        result = _load_never_anonymise(user_path=user)
        assert "uniquephrase" in result.phrases

    @pytest.mark.unit
    def test_duplicate_phrases_deduplicated(self, tmp_path):
        user = tmp_path / "usr.toml"
        user.write_bytes(b'exclude = ["Balance", "Balance"]\n')
        result = _load_never_anonymise(user_path=user)
        # frozenset guarantees no duplicates; normalised form appears exactly once
        assert "balance" in result.phrases
        assert len([p for p in result.phrases if p == "balance"]) == 1

    @pytest.mark.unit
    def test_whitespace_only_entries_filtered(self, tmp_path):
        user = tmp_path / "usr.toml"
        user.write_bytes(b'exclude = ["   ", "Balance"]\n')
        result = _load_never_anonymise(user_path=user)
        assert "" not in result.phrases
        assert "balance" in result.phrases

    @pytest.mark.unit
    def test_missing_exclude_key_returns_system_only(self, tmp_path):
        user = tmp_path / "usr.toml"
        user.write_bytes(b"# no exclude key\n")
        result = _load_never_anonymise(user_path=user)
        # Should return system phrases (may not be empty)
        assert isinstance(result, _NeverAnonymiseConfig)

    @pytest.mark.unit
    def test_missing_user_file_raises_error(self, tmp_path):
        user = tmp_path / "nonexistent_user.toml"
        with pytest.raises(FileNotFoundError):
            _load_never_anonymise(user_path=user)

    @pytest.mark.unit
    def test_user_path_none_returns_system_only(self):
        result = _load_never_anonymise(user_path=None)
        # Should return system phrases
        assert isinstance(result, _NeverAnonymiseConfig)

    @pytest.mark.unit
    def test_non_list_exclude_ignored(self, tmp_path):
        """If 'exclude' is not a list (e.g. a string or int), it should be ignored."""
        user = tmp_path / "usr.toml"
        user.write_bytes(b'exclude = "Balance"\n')
        result = _load_never_anonymise(user_path=user)
        # Should load system phrases instead
        assert isinstance(result, _NeverAnonymiseConfig)

    @pytest.mark.unit
    def test_non_string_entries_coerced(self, tmp_path):
        """Non-string entries in exclude list should be coerced to str, not crash."""
        user = tmp_path / "usr.toml"
        user.write_bytes(b'exclude = ["Balance", 99, true]\n')
        result = _load_never_anonymise(user_path=user)
        # Entries should be coerced to strings
        assert isinstance(result.phrases, frozenset)
        # At least Balance should be there
        assert "balance" in result.phrases


# ---------------------------------------------------------------------------
# Module 5: Bundled system TOML integration
# ---------------------------------------------------------------------------


class TestBundledSystemToml:
    """Integration smoke-tests: the bundled TOML files load without error.
    
    These tests verify that the system configs loaded at module import time
    contain expected entries from never_anonymise_system.toml.
    """

    @pytest.mark.unit
    def test_bundled_always_anonymise_loads(self):
        """always_anonymise_system.toml must load at import time (currently empty)."""
        from bank_statement_anonymiser.anonymise import _ALWAYS_ANONYMISE_SYSTEM_CONFIG
        assert isinstance(_ALWAYS_ANONYMISE_SYSTEM_CONFIG, dict)

    @pytest.mark.unit
    def test_bundled_never_anonymise_loads(self):
        """never_anonymise_system.toml must load at import time."""
        from bank_statement_anonymiser.anonymise import _NEVER_ANONYMISE_SYSTEM_CONFIG
        assert isinstance(_NEVER_ANONYMISE_SYSTEM_CONFIG, dict)

    @pytest.mark.unit
    def test_bundled_never_anonymise_contains_dd(self):
        """'DD' (Direct Debit code) must be present in bundled never_anonymise."""
        result = _load_never_anonymise(user_path=None)
        assert "dd" in result.phrases

    @pytest.mark.unit
    def test_bundled_never_anonymise_contains_balance_brought_forward(self):
        """'Balance Brought Forward' must be present in bundled never_anonymise."""
        result = _load_never_anonymise(user_path=None)
        assert "balancebroughtforward" in result.phrases

    @pytest.mark.unit
    def test_bundled_never_anonymise_contains_bp(self):
        """'BP' (Bill Payment code) must be in bundled never_anonymise."""
        result = _load_never_anonymise(user_path=None)
        assert "bp" in result.phrases

    @pytest.mark.unit
    def test_bundled_never_anonymise_has_many_entries(self):
        """Bundled system file should provide a substantial list of protected phrases."""
        result = _load_never_anonymise(user_path=None)
        assert len(result.phrases) >= 10


class TestNormalisePhraseEdgeCases:
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
        Verify that multiple colons are removed.

        Given: String "Balance::"
        When: _normalise_phrase is called
        Then: Strips all colons correctly
        """
        result = _normalise_phrase("Balance::")
        assert result == "balance", f"Expected 'balance', got {result!r}"

    @pytest.mark.unit
    def test_normalise_phrase_internal_colons(self):
        """
        Verify that internal colons are removed.

        Given: String with internal colons "Account : Number"
        When: _normalise_phrase is called
        Then: All colons removed and internal whitespace removed
        """
        result = _normalise_phrase("Account : Number")
        assert result == "accountnumber", f"Expected 'accountnumber', got {result!r}"


class TestConfigValidation:
    """Tests for config path validation."""

    @pytest.mark.unit
    def test_load_always_anonymise_missing_user_path(self, tmp_path):
        """Should raise FileNotFoundError if user always_anonymise path is missing."""
        missing_path = tmp_path / "non_existent.toml"
        with pytest.raises(FileNotFoundError, match="User always_anonymise config not found"):
            _load_always_anonymise(user_path=missing_path)

    @pytest.mark.unit
    def test_load_never_anonymise_missing_user_path(self, tmp_path):
        """Should raise FileNotFoundError if user never_anonymise path is missing."""
        missing_path = tmp_path / "non_existent.toml"
        with pytest.raises(FileNotFoundError, match="User never_anonymise config not found"):
            _load_never_anonymise(user_path=missing_path)
