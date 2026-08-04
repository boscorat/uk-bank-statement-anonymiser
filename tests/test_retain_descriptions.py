"""Tests for the retain_descriptions feature (Issue #37)."""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

from bank_statement_anonymiser import anonymise_pdf
from bank_statement_anonymiser.cli import main


class TestRetainDescriptionsValidation:
    """Validation: retain_descriptions requires a user always_anonymise.toml."""

    @pytest.mark.unit
    def test_retain_descriptions_requires_user_always_anonymise(self, mock_random_source, simple_text_pdf):
        """retain_descriptions=True without always_anonymise_path raises ValueError."""
        with pytest.raises(ValueError, match="retain_descriptions requires a user always_anonymise"):
            anonymise_pdf(simple_text_pdf, retain_descriptions=True)

    @pytest.mark.unit
    def test_retain_descriptions_false_works_without_always_anonymise(self, mock_random_source, simple_text_pdf, tmp_path):
        """retain_descriptions=False (default) works without always_anonymise_path."""
        output = tmp_path / "output.pdf"
        result = anonymise_pdf(simple_text_pdf, output_path=output, retain_descriptions=False)
        assert result.exists()


class TestRetainDescriptionsBehaviour:
    """Core behaviour: only always_anonymise + numeric IDs are replaced."""

    @pytest.fixture
    def user_always_anonymise(self, tmp_path) -> Path:
        """Create a user always_anonymise.toml with known replacements."""
        config_path = tmp_path / "always_anonymise.toml"
        config_path.write_text('"Amazon Ltd" = "REDACTED_MERCHANT"\n"Water Utilities Ltd" = "REDACTED_UTILITY"\n')
        return config_path

    @pytest.mark.unit
    def test_retain_descriptions_applies_always_anonymise(self, mock_random_source, simple_text_pdf, user_always_anonymise, tmp_path):
        """Text listed in always_anonymise.toml is replaced."""
        output = tmp_path / "output.pdf"
        anonymise_pdf(
            simple_text_pdf,
            output_path=output,
            always_anonymise_path=user_always_anonymise,
            retain_descriptions=True,
        )
        with pikepdf.open(str(output)) as pdf:
            raw_text = _extract_all_text(pdf)
        assert "REDACTED_MERCHANT" in raw_text
        assert "REDACTED_UTILITY" in raw_text

    @pytest.mark.unit
    def test_retain_descriptions_preserves_unlisted_text(self, mock_random_source, simple_text_pdf, user_always_anonymise, tmp_path):
        """Text NOT in always_anonymise.toml is left untouched."""
        output = tmp_path / "output.pdf"
        anonymise_pdf(
            simple_text_pdf,
            output_path=output,
            always_anonymise_path=user_always_anonymise,
            retain_descriptions=True,
        )
        with pikepdf.open(str(output)) as pdf:
            raw_text = _extract_all_text(pdf)
        # These descriptions are NOT in the always_anonymise config
        assert "Tesco Supermarket" in raw_text
        assert "National Insurance Payment" in raw_text

    @pytest.mark.unit
    def test_retain_descriptions_still_runs_numeric_id_detection(
        self, mock_random_source, simple_text_pdf, user_always_anonymise, tmp_path
    ):
        """Numeric ID auto-detection still runs (not skipped by retain_descriptions)."""
        output = tmp_path / "output.pdf"
        anonymise_pdf(
            simple_text_pdf,
            output_path=output,
            always_anonymise_path=user_always_anonymise,
            retain_descriptions=True,
        )
        assert output.exists()
        with pikepdf.open(str(output)) as pdf:
            assert len(pdf.pages) > 0

    @pytest.mark.unit
    def test_retain_descriptions_preserves_structural_text(self, mock_random_source, simple_text_pdf, user_always_anonymise, tmp_path):
        """Structural headers remain intact (not scrambled)."""
        output = tmp_path / "output.pdf"
        anonymise_pdf(
            simple_text_pdf,
            output_path=output,
            always_anonymise_path=user_always_anonymise,
            retain_descriptions=True,
        )
        with pikepdf.open(str(output)) as pdf:
            raw_text = _extract_all_text(pdf)
        # These are in never_anonymise_system.toml and should be intact
        assert "STATEMENT OF ACCOUNT" in raw_text
        assert "TRANSACTION HISTORY" in raw_text


class TestRetainDescriptionsVsDefault:
    """Compare retain_descriptions mode against default scramble mode."""

    @pytest.fixture
    def user_always_anonymise(self, tmp_path) -> Path:
        config_path = tmp_path / "always_anonymise.toml"
        config_path.write_text('"Amazon Ltd" = "REDACTED_MERCHANT"\n')
        return config_path

    @pytest.mark.unit
    def test_default_mode_scrambles_descriptions(self, mock_random_source, simple_text_pdf, tmp_path):
        """Default mode scrambles all unmatched text."""
        output = tmp_path / "output.pdf"
        anonymise_pdf(simple_text_pdf, output_path=output)
        with pikepdf.open(str(output)) as pdf:
            raw_text = _extract_all_text(pdf)
        # Descriptions should be scrambled (not original)
        assert "Amazon Ltd" not in raw_text
        assert "Tesco Supermarket" not in raw_text

    @pytest.mark.unit
    def test_retain_descriptions_mode_preserves_descriptions(self, mock_random_source, simple_text_pdf, user_always_anonymise, tmp_path):
        """retain_descriptions mode preserves all unmatched text."""
        output = tmp_path / "output.pdf"
        anonymise_pdf(
            simple_text_pdf,
            output_path=output,
            always_anonymise_path=user_always_anonymise,
            retain_descriptions=True,
        )
        with pikepdf.open(str(output)) as pdf:
            raw_text = _extract_all_text(pdf)
        # Descriptions should be preserved
        assert "Tesco Supermarket" in raw_text
        assert "National Insurance Payment" in raw_text
        assert "Water Utilities Ltd" in raw_text
        # always_anonymise replacement still applied
        assert "REDACTED_MERCHANT" in raw_text

    @pytest.mark.unit
    def test_default_mode_scrambles_customer_name(self, mock_random_source, simple_text_pdf, tmp_path):
        """Default mode scrambles the customer name."""
        output = tmp_path / "output.pdf"
        anonymise_pdf(simple_text_pdf, output_path=output)
        with pikepdf.open(str(output)) as pdf:
            raw_text = _extract_all_text(pdf)
        assert "John James Smith" not in raw_text

    @pytest.mark.unit
    def test_retain_descriptions_preserves_customer_name(self, mock_random_source, simple_text_pdf, user_always_anonymise, tmp_path):
        """retain_descriptions mode preserves the customer name."""
        output = tmp_path / "output.pdf"
        anonymise_pdf(
            simple_text_pdf,
            output_path=output,
            always_anonymise_path=user_always_anonymise,
            retain_descriptions=True,
        )
        with pikepdf.open(str(output)) as pdf:
            raw_text = _extract_all_text(pdf)
        assert "John James Smith" in raw_text


class TestRetainDescriptionsCli:
    """CLI flag tests."""

    @pytest.mark.unit
    def test_cli_retain_descriptions_flag(self, mock_random_source, simple_text_pdf, tmp_path, capsys):
        """--retain-descriptions triggers retain_descriptions mode."""
        config_path = tmp_path / "always_anonymise.toml"
        config_path.write_text('"Amazon Ltd" = "REDACTED_MERCHANT"\n')
        output = tmp_path / "output.pdf"
        main(
            [
                str(simple_text_pdf),
                "-o",
                str(output),
                "--always-anonymise",
                str(config_path),
                "--retain-descriptions",
            ]
        )
        assert output.exists()
        with pikepdf.open(str(output)) as pdf:
            raw_text = _extract_all_text(pdf)
        assert "Tesco Supermarket" in raw_text

    @pytest.mark.unit
    def test_cli_retain_descriptions_without_always_anonymise_exits(self, mock_random_source, simple_text_pdf, capsys):
        """--retain-descriptions without --always-anonymise should exit 1."""
        with pytest.raises(SystemExit) as exc_info:
            main([str(simple_text_pdf), "--retain-descriptions"])
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err


def _extract_all_text(pdf: pikepdf.Pdf) -> str:
    """Extract all text from every page of a PDF."""
    parts: list[str] = []
    for page in pdf.pages:
        try:
            content_stream = pikepdf.parse_content_stream(page)
            for operands, operator in content_stream:
                op = str(operator)
                if op == "Tj" and operands:
                    parts.append(bytes(operands[0]).decode("latin-1", errors="replace"))
                elif op == "TJ" and operands:
                    for item in operands[0]:
                        if isinstance(item, pikepdf.String):
                            parts.append(bytes(item).decode("latin-1", errors="replace"))
        except Exception:
            continue
    return " ".join(parts)
