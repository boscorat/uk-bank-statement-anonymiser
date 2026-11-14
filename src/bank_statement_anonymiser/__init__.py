"""
bank_statement_anonymiser — exclusion-based full-page PDF anonymisation library.

Public API
----------
    anonymise_pdf(input_path, output_path=None, always_anonymise_path=None,
                  never_anonymise_path=None, retain_descriptions=False,
                  debug=False) -> Path

    phrase_replace_pdf(input_path, output_path=None, phrase_replace_path=None) -> Path

    get_logger(name: str) -> logging.Logger
    set_verbosity(verbosity: "normal" | "verbose") -> None
    get_verbosity() -> "normal" | "verbose"
"""

from importlib.metadata import version

from bank_statement_anonymiser.anonymise import anonymise_pdf
from bank_statement_anonymiser.anonymise_phrase import phrase_replace_pdf
from bank_statement_anonymiser.logging_config import get_logger, get_verbosity, set_verbosity

__version__ = version("uk-bank-statement-anonymiser")
__all__ = ["__version__", "anonymise_pdf", "phrase_replace_pdf", "get_logger", "get_verbosity", "set_verbosity"]
