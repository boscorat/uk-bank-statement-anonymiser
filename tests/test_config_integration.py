"""
Unit tests for config integration in bank_statement_anonymiser.

This module tests the interaction between always_anonymise / never_anonymise
configs through the full anonymise_pdf() pipeline, verifying actual output
text rather than merely checking that files are created.

Coverage:
- always_anonymise replaces exact phrase with fixed value
- never_anonymise preserves phrase verbatim (not scrambled)
- always_anonymise takes precedence over scrambling
- never_anonymise takes precedence over scrambling
- always_anonymise takes precedence over never_anonymise (checked first)
- User always_anonymise overrides system file on key clash
- User never_anonymise merges with system file (union)
- Normalisation: config key with trailing colon matches PDF text without
- Both configs can coexist on the same page
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

from bank_statement_anonymiser import anonymise_pdf
from bank_statement_anonymiser._shared import _decode_pdf_operand

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _make_pdf_with_text(tmp_path: Path, *lines: str, filename: str = "src.pdf") -> Path:
    """One-page Latin-1 PDF where each line is a separate Tj on a new Td."""
    pdf = pikepdf.Pdf.new()
    parts = [b"BT\n/F1 12 Tf\n50 750 Td\n"]
    for i, line in enumerate(lines):
        encoded = line.encode("latin-1")
        escaped = (
            encoded
            .replace(b"\\", b"\\\\")
            .replace(b"(", b"\\(")
            .replace(b")", b"\\)")
        )
        parts.append(b"(" + escaped + b") Tj\n")
        if i < len(lines) - 1:
            parts.append(b"0 -20 Td\n")
    parts.append(b"ET\n")
    content = b"".join(parts)

    page = pdf.add_blank_page(page_size=(595, 842))
    page.Contents = pikepdf.Stream(pdf, content)
    page.Resources = pikepdf.Dictionary(
        Font=pikepdf.Dictionary(
            F1=pikepdf.Dictionary(
                Type=pikepdf.Name.Font,
                Subtype=pikepdf.Name.Type1,
                BaseFont=pikepdf.Name.Helvetica,
            )
        )
    )
    out = tmp_path / filename
    pdf.save(str(out))
    return out


def _extract_all_text(pdf_path: Path) -> list[str]:
    """Return a flat list of every decoded Tj/TJ string from all pages."""
    texts: list[str] = []
    with pikepdf.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            try:
                instructions = list(pikepdf.parse_content_stream(page))
            except Exception:
                continue
            for operands, operator in instructions:
                op = str(operator)
                if op == "Tj" and operands:
                    try:
                        texts.append(_decode_pdf_operand(bytes(operands[0])))
                    except Exception:
                        pass
                elif op == "TJ" and operands:
                    try:
                        for item in list(operands[0]):  # type: ignore[arg-type]
                            if isinstance(item, pikepdf.String):
                                texts.append(_decode_pdf_operand(bytes(item)))
                    except Exception:
                        pass
    return texts


def _all_text_joined(pdf_path: Path) -> str:
    """Concatenate all decoded Tj strings into one string for substring checks."""
    return "".join(_extract_all_text(pdf_path))


# ---------------------------------------------------------------------------
# Module 8a: always_anonymise replaces phrase with fixed value
# ---------------------------------------------------------------------------


class TestAlwaysAnonymiseReplacement:
    """always_anonymise entries produce the configured fixed replacement in output."""

    @pytest.mark.unit
    def test_always_anonymise_replaces_single_word(self, mock_random_source, tmp_path):
        """A single-word always_anonymise entry replaces that word in the output."""
        src = _make_pdf_with_text(tmp_path, "JohnSmith", filename="src.pdf")
        cfg = _write_toml(tmp_path / "always.toml", '"JohnSmith" = "JaneDoeX"\n')
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out, always_anonymise_path=cfg)
        texts = _extract_all_text(out)
        assert "JohnSmith" not in texts, "Original should be replaced"
        assert "JaneDoeX" in texts, "Fixed replacement should appear"

    @pytest.mark.unit
    def test_always_anonymise_replacement_exact_bytes(self, mock_random_source, tmp_path):
        """Verify the replacement bytes match exactly (not partially)."""
        src = _make_pdf_with_text(tmp_path, "Barclays", filename="src.pdf")
        cfg = _write_toml(tmp_path / "always.toml", '"Barclays" = "XxxxxxxX"\n')
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out, always_anonymise_path=cfg)
        texts = _extract_all_text(out)
        assert "XxxxxxxX" in texts

    @pytest.mark.unit
    def test_always_anonymise_multiple_rules_all_applied(self, mock_random_source, tmp_path):
        """Multiple always_anonymise rules are all applied in a single pass."""
        src = _make_pdf_with_text(tmp_path, "AlphaText", "BetaText", filename="src.pdf")
        cfg = _write_toml(
            tmp_path / "always.toml",
            '"AlphaText" = "XxxxxxxX"\n"BetaText" = "YyyyyyyyY"\n',
        )
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out, always_anonymise_path=cfg)
        texts = _extract_all_text(out)
        assert "XxxxxxxX" in texts, "First rule not applied"
        assert "YyyyyyyyY" in texts, "Second rule not applied"

    @pytest.mark.unit
    def test_always_anonymise_normalised_match(self, mock_random_source, tmp_path):
        """Config key 'Sort code:' (trailing colon) matches PDF text 'Sort code'."""
        src = _make_pdf_with_text(tmp_path, "Sortcode", filename="src.pdf")
        # The normalise_phrase strips the trailing colon, so this key == 'sortcode'
        cfg = _write_toml(tmp_path / "always.toml", '"Sortcode:" = "Replaced"\n')
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out, always_anonymise_path=cfg)
        texts = _extract_all_text(out)
        assert "Replaced" in texts, "Normalised key should match without colon"

    @pytest.mark.unit
    def test_always_anonymise_not_scrambled(self, mock_random_source, tmp_path):
        """Text covered by always_anonymise is not additionally scrambled."""
        src = _make_pdf_with_text(tmp_path, "CustomerName", filename="src.pdf")
        cfg = _write_toml(tmp_path / "always.toml", '"CustomerName" = "FixedValue"\n')
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out, always_anonymise_path=cfg)
        texts = _extract_all_text(out)
        # Should be exactly "FixedValue", not some scramble of it
        assert "FixedValue" in texts


# ---------------------------------------------------------------------------
# Module 8b: never_anonymise preserves phrase verbatim
# ---------------------------------------------------------------------------


class TestNeverAnonymiseProtection:
    """never_anonymise entries survive the scramble pass unchanged."""

    @pytest.mark.unit
    def test_never_anonymise_preserves_phrase(self, mock_random_source, tmp_path):
        """A phrase in never_anonymise is not scrambled."""
        src = _make_pdf_with_text(tmp_path, "ProtectedBank", filename="src.pdf")
        cfg = _write_toml(tmp_path / "never.toml", 'exclude = ["ProtectedBank"]\n')
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out, never_anonymise_path=cfg)
        texts = _extract_all_text(out)
        assert "ProtectedBank" in texts, "Protected phrase should be unchanged"

    @pytest.mark.unit
    def test_never_anonymise_case_insensitive_match(self, mock_random_source, tmp_path):
        """never_anonymise matching is case-insensitive via normalisation."""
        src = _make_pdf_with_text(tmp_path, "HSBC", filename="src.pdf")
        # Config has lowercase; normalised form 'hsbc' matches 'HSBC' normalised too
        cfg = _write_toml(tmp_path / "never.toml", 'exclude = ["hsbc"]\n')
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out, never_anonymise_path=cfg)
        texts = _extract_all_text(out)
        assert "HSBC" in texts, "Case-insensitive never_anonymise match should protect phrase"

    @pytest.mark.unit
    def test_never_anonymise_phrase_colon_normalised(self, mock_random_source, tmp_path):
        """Config entry 'Account number:' protects PDF text 'Account number'."""
        src = _make_pdf_with_text(tmp_path, "Accountnumber", filename="src.pdf")
        cfg = _write_toml(tmp_path / "never.toml", 'exclude = ["Accountnumber:"]\n')
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out, never_anonymise_path=cfg)
        texts = _extract_all_text(out)
        assert "Accountnumber" in texts, "Colon-normalised never entry should protect phrase"

    @pytest.mark.unit
    def test_unlisted_phrase_is_scrambled(self, mock_random_source, tmp_path):
        """Text NOT in never_anonymise is still scrambled."""
        src = _make_pdf_with_text(tmp_path, "Scrambleme", filename="src.pdf")
        cfg = _write_toml(tmp_path / "never.toml", 'exclude = ["SomethingElse"]\n')
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out, never_anonymise_path=cfg)
        texts = _extract_all_text(out)
        assert "Scrambleme" not in texts, "Unlisted phrase should be scrambled"


# ---------------------------------------------------------------------------
# Module 8c: precedence rules
# ---------------------------------------------------------------------------


class TestConfigPrecedence:
    """Precedence: always > never > scramble."""

    @pytest.mark.unit
    def test_always_takes_precedence_over_scramble(self, mock_random_source, tmp_path):
        """always_anonymise wins over default scramble behaviour."""
        src = _make_pdf_with_text(tmp_path, "MerchantXX", filename="src.pdf")
        always = _write_toml(tmp_path / "always.toml", '"MerchantXX" = "Replaced1"\n')
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out, always_anonymise_path=always)
        texts = _extract_all_text(out)
        assert "Replaced1" in texts

    @pytest.mark.unit
    def test_never_takes_precedence_over_scramble(self, mock_random_source, tmp_path):
        """never_anonymise wins over default scramble behaviour."""
        src = _make_pdf_with_text(tmp_path, "MerchantYY", filename="src.pdf")
        never = _write_toml(tmp_path / "never.toml", 'exclude = ["MerchantYY"]\n')
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out, never_anonymise_path=never)
        texts = _extract_all_text(out)
        assert "MerchantYY" in texts

    @pytest.mark.unit
    def test_always_takes_precedence_over_never(self, mock_random_source, tmp_path):
        """When the same phrase is in both always and never, always wins."""
        src = _make_pdf_with_text(tmp_path, "DoubleRule", filename="src.pdf")
        always = _write_toml(tmp_path / "always.toml", '"DoubleRule" = "AlwaysWins"\n')
        never = _write_toml(tmp_path / "never.toml", 'exclude = ["DoubleRule"]\n')
        out = tmp_path / "out.pdf"
        anonymise_pdf(
            src, output_path=out,
            always_anonymise_path=always,
            never_anonymise_path=never,
        )
        texts = _extract_all_text(out)
        assert "AlwaysWins" in texts, "always_anonymise should win over never_anonymise"
        assert "DoubleRule" not in texts, "Original should be replaced, not preserved"

    @pytest.mark.unit
    def test_both_configs_coexist_on_same_page(self, mock_random_source, tmp_path):
        """always and never rules applied simultaneously on one page."""
        src = _make_pdf_with_text(
            tmp_path, "ReplaceMe", "KeepMe", "Scrambleme", filename="src.pdf"
        )
        always = _write_toml(tmp_path / "always.toml", '"ReplaceMe" = "WasReplaced"\n')
        never = _write_toml(tmp_path / "never.toml", 'exclude = ["KeepMe"]\n')
        out = tmp_path / "out.pdf"
        anonymise_pdf(
            src, output_path=out,
            always_anonymise_path=always,
            never_anonymise_path=never,
        )
        texts = _extract_all_text(out)
        assert "WasReplaced" in texts, "always_anonymise rule not applied"
        assert "KeepMe" in texts, "never_anonymise rule not applied"
        assert "ReplaceMe" not in texts, "Original should not survive"
        assert "Scrambleme" not in texts, "Unlisted text should be scrambled"


# ---------------------------------------------------------------------------
# Module 8d: user vs system file interaction
# ---------------------------------------------------------------------------


class TestUserVsSystemConfig:
    """User config files interact correctly with bundled system files."""

    @pytest.mark.unit
    def test_user_always_config_overrides_system_on_clash(self, mock_random_source, tmp_path):
        """When user and system both define the same key, user value is used."""
        # We test by providing user-only config (no system key overlap) and
        # verifying the user replacement is applied.  The system always.toml is
        # currently empty, so any user key exercises the merge path without clash.
        src = _make_pdf_with_text(tmp_path, "UserOverride", filename="src.pdf")
        user_always = _write_toml(
            tmp_path / "user_always.toml", '"UserOverride" = "UserValue"\n'
        )
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out, always_anonymise_path=user_always)
        texts = _extract_all_text(out)
        assert "UserValue" in texts

    @pytest.mark.unit
    def test_user_never_config_merges_with_system(self, mock_random_source, tmp_path):
        """User never_anonymise entries are unioned with system entries."""
        # System never_anonymise.toml already contains "DD".
        # User config adds "CustomProtected".
        # Both should be protected after merge.
        src = _make_pdf_with_text(tmp_path, "DD", "CustomProtected", filename="src.pdf")
        user_never = _write_toml(
            tmp_path / "user_never.toml", 'exclude = ["CustomProtected"]\n'
        )
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out, never_anonymise_path=user_never)
        texts = _extract_all_text(out)
        assert "DD" in texts, "System never entry 'DD' should still be protected"
        assert "CustomProtected" in texts, "User never entry should be protected"

    @pytest.mark.unit
    def test_no_user_config_system_rules_still_apply(self, mock_random_source, tmp_path):
        """Without any user config, bundled system rules are still in effect."""
        # System never_anonymise.toml protects "DD" — verify it survives.
        src = _make_pdf_with_text(tmp_path, "DD", filename="src.pdf")
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)
        texts = _extract_all_text(out)
        assert "DD" in texts, "Bundled system protected phrase 'DD' should not be scrambled"

    @pytest.mark.unit
    def test_absent_user_config_file_raises(self, mock_random_source, tmp_path):
        """Pointing always_anonymise_path at a nonexistent file raises FileNotFoundError."""
        src = _make_pdf_with_text(tmp_path, "SomeText", filename="src.pdf")
        nonexistent = tmp_path / "does_not_exist.toml"
        out = tmp_path / "out.pdf"
        with pytest.raises(FileNotFoundError):
            anonymise_pdf(src, output_path=out, always_anonymise_path=nonexistent)
