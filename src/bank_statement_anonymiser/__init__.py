"""
bank_statement_anonymiser — exclusion-based full-page PDF anonymisation library.

Public API
----------
    anonymise_pdf(input_path, output_path=None, always_anonymise_path=None,
                  never_anonymise_path=None, debug=False) -> Path
"""

from importlib.metadata import version

from bank_statement_anonymiser.anonymise import anonymise_pdf

__version__ = version("uk-bank-statement-anonymiser")
__all__ = ["anonymise_pdf", "__version__"]
