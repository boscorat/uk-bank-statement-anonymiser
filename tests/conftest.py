"""
Pytest configuration and shared fixtures for bank_statement_anonymiser tests.

This module provides:
- Mocked random number generation for deterministic tests
- Synthetic test PDF generation with realistic bank statement data
- Temporary configuration file fixtures
"""

from __future__ import annotations

import random
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pikepdf
import pytest


@pytest.fixture
def mock_random_source() -> Generator[MagicMock, None, None]:
    """
    Mock secrets.SystemRandom() to use a seeded random.Random for deterministic testing.

    This fixture ensures that the scramble map generation is reproducible across test runs
    by replacing the cryptographically secure random source with a seeded deterministic one.

    Yields:
        MagicMock: A mock that replaces secrets.SystemRandom()

    Example:
        >>> def test_deterministic_anonymisation(mock_random_source, simple_text_pdf):
        ...     # The scramble map will always be the same because seed is fixed
        ...     result1 = anonymise_pdf(simple_text_pdf)
        ...     result2 = anonymise_pdf(simple_text_pdf)
        ...     # Both outputs are identical
    """
    # Create a seeded random source (seed=42 for reproducibility)
    seeded_random = random.Random()
    seeded_random.seed(42)

    # Create a mock that behaves like a SystemRandom instance
    mock = MagicMock()
    mock.choice = seeded_random.choice
    mock.shuffle = seeded_random.shuffle
    mock.sample = seeded_random.sample
    mock.randint = seeded_random.randint

    # Patch secrets.SystemRandom to return our mock
    with patch("secrets.SystemRandom", return_value=mock):
        yield mock


@pytest.fixture
def simple_text_pdf(tmp_path: Path) -> Path:
    """
    Generate a minimal synthetic PDF with realistic bank statement-like content.

    This fixture creates a simple PDF containing:
    - Customer name and address (to be scrambled)
    - Account number (40-37-28-123456 - to be replaced with numeric ID fallback)
    - Sort code (40-37-28 - to be protected/replaced)
    - Transaction amounts (£1,234.56 format - to be protected)
    - Transaction dates (DD/MM/YYYY format - to be protected)
    - Transaction descriptions (various merchants - to be scrambled)
    - IBAN example (GB82 WEST 1234 5698 7654 32 - to be protected)

    Args:
        tmp_path: pytest's built-in temporary directory fixture

    Returns:
        Path: Path to the generated test PDF

    Example:
        >>> def test_with_pdf(simple_text_pdf):
        ...     # simple_text_pdf is a Path object pointing to a valid PDF
        ...     result = anonymise_pdf(simple_text_pdf)
        ...     assert result.exists()
    """
    pdf = pikepdf.Pdf.new()

    # Create a content stream with realistic bank statement text
    content = b"""
    BT
    /F1 12 Tf
    50 750 Td
    (STATEMENT OF ACCOUNT) Tj
    0 -40 Td
    (Customer: John James Smith) Tj
    0 -20 Td
    (Address: 123 High Street, London, UK SW1A 1AA) Tj
    0 -40 Td
    (Account Number: 40-37-28-123456) Tj
    0 -20 Td
    (Sort Code: 40-37-28) Tj
    0 -20 Td
    (IBAN: GB82 WEST 1234 5698 7654 32) Tj
    0 -40 Td
    (TRANSACTION HISTORY) Tj
    0 -30 Td
    (Date) Tj
    100 0 Td
    (Description) Tj
    250 0 Td
    (Amount) Tj
    0 -20 Td
    (01/06/2024) Tj
    100 0 Td
    (Amazon Ltd) Tj
    250 0 Td
    (1,234.56) Tj
    0 -20 Td
    (02/06/2024) Tj
    100 0 Td
    (Tesco Supermarket) Tj
    250 0 Td
    (87.23) Tj
    0 -20 Td
    (03/06/2024) Tj
    100 0 Td
    (National Insurance Payment) Tj
    250 0 Td
    (456.78) Tj
    0 -20 Td
    (04/06/2024) Tj
    100 0 Td
    (Water Utilities Ltd) Tj
    250 0 Td
    (123.45) Tj
    0 -40 Td
    (Card Number: 4532-1234-5678-9012) Tj
    0 -20 Td
    (CVV: 123) Tj
    ET
    """

    # Create a simple font dictionary (minimal, just for testing)
    font_dict = pikepdf.Dictionary(
        Type=pikepdf.Name.Font,
        Subtype=pikepdf.Name.Type1,
        BaseFont=pikepdf.Name.Helvetica,
    )

    # Add a blank page with content
    page = pdf.add_blank_page(page_size=(595, 842))  # A4 size
    page.Contents = pikepdf.Stream(pdf, content)
    page.Resources = pikepdf.Dictionary(
        Font=pikepdf.Dictionary(F1=font_dict),
    )

    # Write to temporary file
    pdf_path = tmp_path / "test_statement.pdf"
    pdf.save(str(pdf_path))

    return pdf_path


@pytest.fixture
def always_anonymise_config(tmp_path: Path) -> Path:
    """
    Create a temporary always_anonymise.toml configuration file for testing.

    This fixture creates a test config file with custom anonymisation rules
    that override the default behavior for specific patterns.

    Args:
        tmp_path: pytest's built-in temporary directory fixture

    Returns:
        Path: Path to the generated always_anonymise.toml file

    Example:
        >>> def test_with_config(always_anonymise_config, simple_text_pdf, tmp_path):
        ...     result = anonymise_pdf(
        ...         simple_text_pdf,
        ...         always_anonymise_path=always_anonymise_config,
        ...         output_path=tmp_path / "output.pdf"
        ...     )
    """
    config_path = tmp_path / "always_anonymise.toml"
    config_content = """# Test configuration for always_anonymise
[numeric_ids]
# Map specific numeric IDs to fixed replacements for testing
"40-37-28" = "00-00-00"

[patterns]
# Additional patterns that should always be anonymised
extra_patterns = [
    "test_merchant_",
    "special_account_",
]
"""
    config_path.write_text(config_content)
    return config_path


@pytest.fixture
def never_anonymise_config(tmp_path: Path) -> Path:
    """
    Create a temporary never_anonymise.toml configuration file for testing.

    This fixture creates a test config file with patterns that should never
    be anonymised (protected phrases, critical information, etc.).

    Args:
        tmp_path: pytest's built-in temporary directory fixture

    Returns:
        Path: Path to the generated never_anonymise.toml file

    Example:
        >>> def test_protected_phrases(never_anonymise_config, simple_text_pdf):
        ...     result = anonymise_pdf(
        ...         simple_text_pdf,
        ...         never_anonymise_path=never_anonymise_config
        ...     )
        ...     # Protected phrases remain in output PDF
    """
    config_path = tmp_path / "never_anonymise.toml"
    config_content = """
# Test configuration for never_anonymise
[protected]
# Phrases that should never be anonymised (preserve structure/meaning)
phrases = [
    "STATEMENT OF ACCOUNT",
    "TRANSACTION HISTORY",
    "Amount",
    "Date",
    "Description",
    "Balance",
]

# Patterns that should be protected (regex)
patterns = [
    "National Insurance.*",
    "Water Utilities.*",
]
"""
    config_path.write_text(config_content)
    return config_path


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    """
    Provide a temporary output directory for anonymised PDFs.

    Args:
        tmp_path: pytest's built-in temporary directory fixture

    Returns:
        Path: Path to an empty temporary directory for output files

    Example:
        >>> def test_output_location(simple_text_pdf, output_dir):
        ...     result = anonymise_pdf(simple_text_pdf, output_path=output_dir / "output.pdf")
        ...     assert result.parent == output_dir
    """
    return tmp_path / "output"


@pytest.fixture(autouse=True)
def reset_random_seed() -> Generator[None, None, None]:
    """
    Auto-used fixture that resets random seed before each test for consistency.

    This ensures that even if a test uses unseeded random, the baseline is consistent
    across test runs for better reproducibility.

    Yields:
        None
    """
    random.seed(42)
    yield
    random.seed(42)
