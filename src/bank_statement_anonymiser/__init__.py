"""
bank_statement_anonymiser — exclusion-based full-page PDF anonymisation library.

Public API
----------
    anonymise_pdf(input_path, output_path=None, config_path=None) -> Path
"""

from bank_statement_anonymiser.anonymise import anonymise_pdf

__all__ = ["anonymise_pdf"]
