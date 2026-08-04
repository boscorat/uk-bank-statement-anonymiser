"""Tests for the CLI entry point."""

from __future__ import annotations

import pytest

from bank_statement_anonymiser import __version__
from bank_statement_anonymiser.cli import main


class TestCliHelpAndVersion:
    """Test --help and --version flags."""

    @pytest.mark.unit
    def test_help_exits_zero(self):
        """--help should print usage and exit 0."""
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    @pytest.mark.unit
    def test_version_exits_zero(self, capsys):
        """--version should print version string and exit 0."""
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert __version__ in captured.out


class TestCliAnonymise:
    """Test successful anonymisation via CLI."""

    @pytest.mark.unit
    def test_anonymise_creates_output(self, mock_random_source, simple_text_pdf, tmp_path, capsys):
        """Running main() with a valid PDF should create the output file and print path."""
        output = tmp_path / "output.pdf"
        main([str(simple_text_pdf), "-o", str(output)])
        assert output.exists()
        captured = capsys.readouterr()
        assert str(output) in captured.out

    @pytest.mark.unit
    def test_anonymise_default_output_location(self, mock_random_source, simple_text_pdf, capsys):
        """Running main() without -o should create anonymised_<stem>.pdf alongside input."""
        main([str(simple_text_pdf)])
        expected = simple_text_pdf.parent / f"anonymised_{simple_text_pdf.name}"
        assert expected.exists()
        captured = capsys.readouterr()
        assert str(expected) in captured.out

    @pytest.mark.unit
    def test_anonymise_with_config_files(
        self, mock_random_source, simple_text_pdf, always_anonymise_config, never_anonymise_config, tmp_path, capsys
    ):
        """Running main() with config flags should pass them through."""
        output = tmp_path / "output.pdf"
        main(
            [
                str(simple_text_pdf),
                "-o",
                str(output),
                "--always-anonymise",
                str(always_anonymise_config),
                "--never-anonymise",
                str(never_anonymise_config),
            ]
        )
        assert output.exists()

    @pytest.mark.unit
    def test_anonymise_with_debug(self, mock_random_source, simple_text_pdf, tmp_path, capsys):
        """Running main() with --debug should print debug output."""
        output = tmp_path / "output.pdf"
        main([str(simple_text_pdf), "-o", str(output), "--debug"])
        assert output.exists()


class TestCliErrors:
    """Test error handling."""

    @pytest.mark.unit
    def test_missing_input_exits_nonzero(self, capsys):
        """Missing input file should print error and exit 1."""
        with pytest.raises(SystemExit) as exc_info:
            main(["nonexistent.pdf"])
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err

    @pytest.mark.unit
    def test_invalid_pdf_exits_nonzero(self, tmp_path, capsys):
        """A non-PDF file should print error and exit 1."""
        bad_file = tmp_path / "bad.pdf"
        bad_file.write_text("not a pdf")
        with pytest.raises(SystemExit) as exc_info:
            main([str(bad_file)])
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err
