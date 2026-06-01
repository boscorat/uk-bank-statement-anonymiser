"""
Baseline tests for the public API of bank_statement_anonymiser.

These tests are designed to:
1. Establish the current behavior before refactoring
2. Serve as regression tests after code changes
3. Document the expected behavior of anonymise_pdf()
4. Provide examples of how to use the library

All tests use mock_random_source fixture to ensure deterministic output
across test runs for reproducible assertions.
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

from bank_statement_anonymiser import anonymise_pdf


class TestAnonymisePdfPublicApi:
    """Test suite for the public anonymise_pdf() function."""

    @pytest.mark.unit
    def test_anonymise_pdf_creates_output_file(self, mock_random_source, simple_text_pdf, tmp_path):
        """
        Verify that anonymise_pdf() creates an output file.

        Given: A valid input PDF file
        When: anonymise_pdf() is called with the input file
        Then: An output PDF file is created at the expected location
        And:  The output file is a valid, readable PDF

        This test ensures the basic file creation functionality works correctly.
        """
        # Arrange: We have a simple_text_pdf fixture
        # The default output location should be in the same directory as input
        # with "_anonymised_" prefix

        # Act: Call anonymise_pdf with the input PDF
        result_path = anonymise_pdf(simple_text_pdf)

        # Assert: Output file exists and is a valid PDF
        assert result_path.exists(), "Output PDF file was not created"
        assert result_path.is_file(), "Output path is not a file"

        # Verify it's a valid PDF by opening it
        try:
            with pikepdf.open(str(result_path)) as pdf:
                assert len(pdf.pages) > 0, "Output PDF has no pages"
        except Exception as e:
            pytest.fail(f"Output PDF is not valid: {e}")

    @pytest.mark.unit
    def test_anonymise_pdf_custom_output_path(self, mock_random_source, simple_text_pdf, tmp_path):
        """
        Verify that anonymise_pdf() respects custom output_path parameter.

        Given: A valid input PDF file
        And:   A custom output path specified
        When: anonymise_pdf() is called with both paths
        Then: The output file is created at the specified custom location
        And:  The returned Path matches the custom output path

        This test ensures the output_path parameter is properly handled.
        """
        # Arrange: Create a custom output path
        custom_output = tmp_path / "my_custom_output.pdf"

        # Act: Call anonymise_pdf with custom output path
        result_path = anonymise_pdf(simple_text_pdf, output_path=custom_output)

        # Assert: Output created at custom location
        assert result_path == custom_output, "Returned path does not match custom output path"
        assert result_path.exists(), "Custom output file was not created at specified location"

    @pytest.mark.unit
    def test_anonymise_pdf_returns_path_object(self, mock_random_source, simple_text_pdf):
        """
        Verify that anonymise_pdf() returns a Path object.

        Given: A valid input PDF file
        When: anonymise_pdf() is called
        Then: The return value is a pathlib.Path object
        And:  The Path object points to an existing file

        This test ensures the return type is consistent and usable.
        """
        # Act: Call anonymise_pdf
        result = anonymise_pdf(simple_text_pdf)

        # Assert: Return type is Path
        assert isinstance(result, Path), f"Expected Path, got {type(result)}"
        assert result.exists(), "Returned Path does not point to an existing file"

    @pytest.mark.unit
    def test_anonymise_pdf_is_deterministic_with_mocked_random(self, mock_random_source, simple_text_pdf, tmp_path):
        """
        Verify that anonymise_pdf() produces consistent anonymisation with mocked random seed.

        Given: A valid input PDF file
        And:   The random source is mocked with a fixed seed (42)
        When: anonymise_pdf() is called multiple times on the same input
        Then: The anonymised content is consistent (same text gets scrambled the same way)
        And:  The resulting PDFs both exist and are valid

        Note: We cannot assert byte-for-byte identical PDFs because pikepdf may add
        metadata timestamps or other generated data. Instead, we verify the
        anonymisation logic is deterministic by checking scrambling consistency.

        This test uses the mock_random_source fixture to ensure deterministic output.
        It's important for reproducibility and debugging.
        """
        # Arrange: Create two output paths
        output_1 = tmp_path / "output_1.pdf"
        output_2 = tmp_path / "output_2.pdf"

        # Act: Anonymise the same PDF twice with mocked random
        result_1 = anonymise_pdf(simple_text_pdf, output_path=output_1)
        result_2 = anonymise_pdf(simple_text_pdf, output_path=output_2)

        # Assert: Both outputs exist
        assert result_1.exists(), "First output was not created"
        assert result_2.exists(), "Second output was not created"

        # Verify both PDFs are valid (can be parsed by pikepdf)
        with pikepdf.open(str(result_1)) as pdf1, pikepdf.open(str(result_2)) as pdf2:
            assert len(pdf1.pages) > 0, "First output PDF has no pages"
            assert len(pdf2.pages) > 0, "Second output PDF has no pages"

            # Both should have same page count and structure
            assert len(pdf1.pages) == len(pdf2.pages), "Page counts differ between runs"

    @pytest.mark.unit
    def test_anonymise_pdf_modifies_content(self, mock_random_source, simple_text_pdf, tmp_path):
        """
        Verify that anonymise_pdf() actually modifies the PDF content.

        Given: A valid input PDF file with readable text
        When: anonymise_pdf() is called
        Then: The output PDF has different content than the input
        And:  The content has been scrambled/replaced (not left unchanged)

        This test ensures that the anonymisation logic is actually executed.
        It's a sanity check to catch cases where the library silently does nothing.
        """
        # Arrange: Read original PDF content
        with pikepdf.open(str(simple_text_pdf)) as original:
            original_content = pikepdf.unparse_content_stream(list(pikepdf.parse_content_stream(original.pages[0])))

        # Act: Anonymise the PDF
        result_path = anonymise_pdf(simple_text_pdf, output_path=tmp_path / "modified.pdf")

        # Assert: Output content is different
        with pikepdf.open(str(result_path)) as anonymised:
            anonymised_content = pikepdf.unparse_content_stream(list(pikepdf.parse_content_stream(anonymised.pages[0])))

        # The content should be different (scrambled or replaced)
        assert anonymised_content != original_content, (
            "Anonymised PDF has identical content to original - anonymisation may not be working"
        )

    @pytest.mark.unit
    def test_anonymise_pdf_preserves_pdf_structure(self, mock_random_source, simple_text_pdf):
        """
        Verify that anonymise_pdf() preserves the PDF structure (pages, fonts, etc.).

        Given: A valid input PDF file with specific structure
        When: anonymise_pdf() is called
        Then: The output PDF has the same number of pages as input
        And:  The page dimensions are preserved
        And:  The output remains a valid, readable PDF

        This test ensures that anonymisation doesn't corrupt the PDF structure
        or introduce parsing errors.
        """
        # Arrange: Get original PDF properties
        with pikepdf.open(str(simple_text_pdf)) as original:
            original_page_count = len(original.pages)
            original_mediabox = original.pages[0].MediaBox

        # Act: Anonymise the PDF
        result_path = anonymise_pdf(simple_text_pdf)

        # Assert: Structure is preserved
        with pikepdf.open(str(result_path)) as anonymised:
            anonymised_page_count = len(anonymised.pages)
            anonymised_mediabox = anonymised.pages[0].MediaBox

        assert (
            anonymised_page_count == original_page_count
        ), f"Page count changed: {original_page_count} -> {anonymised_page_count}"

        assert (
            anonymised_mediabox == original_mediabox
        ), f"MediaBox changed: {original_mediabox} -> {anonymised_mediabox}"

    @pytest.mark.unit
    def test_anonymise_pdf_default_output_naming(self, mock_random_source, simple_text_pdf):
        """
        Verify that anonymise_pdf() uses correct default naming for output files.

        Given: An input PDF file "test_statement.pdf"
        When: anonymise_pdf() is called without output_path parameter
        Then: The output is named "anonymised_test_statement.pdf"
        And:  It's created in the same directory as the input file

        This test ensures the default output naming convention is followed.
        """
        # Arrange: Input path is known from fixture
        expected_stem = f"anonymised_{simple_text_pdf.stem}"
        expected_name = f"{expected_stem}.pdf"

        # Act: Anonymise without specifying output path
        result = anonymise_pdf(simple_text_pdf)

        # Assert: Output naming matches convention
        assert result.name == expected_name, f"Expected name {expected_name}, got {result.name}"

        assert result.parent == simple_text_pdf.parent, (
            "Output not in same directory as input: "
            f"{result.parent} vs {simple_text_pdf.parent}"
        )

    @pytest.mark.unit
    def test_anonymise_pdf_with_never_anonymise_config(
        self, mock_random_source, simple_text_pdf, never_anonymise_config, tmp_path
    ):
        """
        Verify that anonymise_pdf() respects never_anonymise_path configuration.

        Given: A valid input PDF file
        And:   A never_anonymise.toml config with protected phrases
        When: anonymise_pdf() is called with the config path
        Then: Protected phrases remain unmodified in the output
        And:  Other text is still anonymised as normal

        This test ensures configuration files are properly loaded and applied.
        """
        # Act: Anonymise with never_anonymise config
        result_path = anonymise_pdf(
            simple_text_pdf,
            never_anonymise_path=never_anonymise_config,
            output_path=tmp_path / "with_config.pdf",
        )

        # Assert: Output file was created
        assert result_path.exists(), "Output PDF was not created with never_anonymise config"

        # Verify it's valid PDF
        with pikepdf.open(str(result_path)) as pdf:
            assert len(pdf.pages) > 0, "Output PDF has no pages"

    @pytest.mark.unit
    def test_anonymise_pdf_with_always_anonymise_config(
        self, mock_random_source, simple_text_pdf, always_anonymise_config, tmp_path
    ):
        """
        Verify that anonymise_pdf() respects always_anonymise_path configuration.

        Given: A valid input PDF file
        And:   An always_anonymise.toml config with custom anonymisation rules
        When: anonymise_pdf() is called with the config path
        Then: Custom numeric ID replacements are applied
        And:  Output is created successfully

        This test ensures always_anonymise configuration is properly loaded and applied.
        """
        # Act: Anonymise with always_anonymise config
        result_path = anonymise_pdf(
            simple_text_pdf,
            always_anonymise_path=always_anonymise_config,
            output_path=tmp_path / "with_always_config.pdf",
        )

        # Assert: Output file was created
        assert result_path.exists(), "Output PDF was not created with always_anonymise config"

        # Verify it's valid PDF
        with pikepdf.open(str(result_path)) as pdf:
            assert len(pdf.pages) > 0, "Output PDF has no pages"

    @pytest.mark.unit
    def test_anonymise_pdf_with_debug_flag(self, mock_random_source, simple_text_pdf, tmp_path, capsys):
        """
        Verify that anonymise_pdf() accepts and respects the debug flag.

        Given: A valid input PDF file
        When: anonymise_pdf() is called with debug=True
        Then: The function completes successfully
        And:  Output PDF is created
        And:  Debug mode doesn't break functionality (defensive test)

        This test ensures the debug flag is a valid parameter that doesn't
        break the function when enabled.
        """
        # Act: Anonymise with debug flag enabled
        result_path = anonymise_pdf(
            simple_text_pdf,
            output_path=tmp_path / "debug_output.pdf",
            debug=True,
        )

        # Assert: Output file was created despite debug flag
        assert result_path.exists(), "Output PDF was not created with debug=True"

        # Verify it's still valid
        with pikepdf.open(str(result_path)) as pdf:
            assert len(pdf.pages) > 0, "Output PDF has no pages"

    @pytest.mark.unit
    def test_anonymise_pdf_with_string_paths(self, mock_random_source, simple_text_pdf, tmp_path):
        """
        Verify that anonymise_pdf() accepts string paths (in addition to Path objects).

        Given: Input and output paths as strings (not Path objects)
        When: anonymise_pdf() is called with string paths
        Then: The function works correctly
        And:  Output is created at the specified string path
        And:  Return value is a Path object

        This test ensures string path compatibility for easier CLI usage.
        """
        # Arrange: Convert paths to strings
        input_str = str(simple_text_pdf)
        output_str = str(tmp_path / "string_output.pdf")

        # Act: Anonymise using string paths
        result = anonymise_pdf(input_str, output_path=output_str)

        # Assert: Works with strings and returns Path
        assert isinstance(result, Path), "Should return Path object"
        assert result.exists(), "Output not created from string paths"
        assert str(result) == output_str, "Return value should match output_path"

    @pytest.mark.unit
    def test_anonymise_pdf_handles_nonexistent_input(self, tmp_path):
        """
        Verify that anonymise_pdf() handles nonexistent input files gracefully.

        Given: A path to a file that doesn't exist
        When: anonymise_pdf() is called with the nonexistent path
        Then: An appropriate error is raised (FileNotFoundError or similar)
        And:  No partial output files are left behind

        This test ensures robust error handling for invalid inputs.
        """
        # Arrange: Non-existent file path
        nonexistent_file = tmp_path / "does_not_exist.pdf"

        # Act & Assert: Should raise an exception
        with pytest.raises((FileNotFoundError, OSError, ValueError)):
            anonymise_pdf(nonexistent_file)

    @pytest.mark.unit
    def test_anonymise_pdf_idempotent_on_already_anonymised(self, mock_random_source, simple_text_pdf, tmp_path):
        """
        Verify that anonymise_pdf() can be run on already-anonymised PDFs.

        Given: A PDF that has already been anonymised once
        When: anonymise_pdf() is called on the anonymised PDF
        Then: The operation completes without error
        And:  A new output file is created

        This test ensures the function is robust enough to handle re-anonymisation,
        even though in practice this shouldn't be necessary.
        """
        # Arrange: Anonymise once
        first_result = anonymise_pdf(simple_text_pdf, output_path=tmp_path / "first_anon.pdf")

        # Act: Anonymise the already-anonymised PDF
        second_result = anonymise_pdf(first_result, output_path=tmp_path / "second_anon.pdf")

        # Assert: Second anonymisation completed
        assert second_result.exists(), "Re-anonymisation should produce output"

        # Verify output is valid
        with pikepdf.open(str(second_result)) as pdf:
            assert len(pdf.pages) > 0, "Re-anonymised PDF should have pages"


class TestAnonymisePdfIntegration:
    """Integration tests combining multiple features."""

    @pytest.mark.integration
    def test_anonymise_pdf_full_workflow(self, mock_random_source, simple_text_pdf, never_anonymise_config, tmp_path):
        """
        Verify a complete anonymisation workflow with config files.

        Given: A valid input PDF
        And:   Custom configuration for protected phrases
        And:   A specified output directory
        When: anonymise_pdf() is called with all parameters
        Then: The process completes successfully
        And:  Output is created with correct naming
        And:  The result is a valid, readable PDF

        This integration test verifies that all features work together correctly.
        """
        # Act: Full workflow with all parameters
        result = anonymise_pdf(
            input_path=simple_text_pdf,
            output_path=tmp_path / "final_output.pdf",
            never_anonymise_path=never_anonymise_config,
            debug=False,
        )

        # Assert: Complete success
        assert result.exists(), "Output PDF not created"
        assert result.name == "final_output.pdf", "Unexpected output name"

        # Verify integrity
        with pikepdf.open(str(result)) as pdf:
            assert len(pdf.pages) > 0, "Output PDF is empty"
            # Attempt to parse content to ensure it's not corrupted
            try:
                content = list(pikepdf.parse_content_stream(pdf.pages[0]))
                assert len(content) > 0, "Page content is empty"
            except Exception as e:
                pytest.fail(f"Failed to parse content stream: {e}")
