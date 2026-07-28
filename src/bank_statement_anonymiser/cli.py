"""CLI entry point for uk-bank-statement-anonymiser."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bank_statement_anonymiser import __version__, anonymise_pdf


def main(argv: list[str] | None = None) -> None:
    """Run the anonymiser from the command line."""
    parser = argparse.ArgumentParser(
        prog="anonymise-pdf",
        description="Anonymise a UK bank statement PDF.",
    )
    parser.add_argument("input", type=Path, help="Path to the input PDF")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output path (default: anonymised_<stem><suffix> alongside input)",
    )
    parser.add_argument(
        "--always-anonymise",
        type=Path,
        default=None,
        help="Path to a user always_anonymise.toml",
    )
    parser.add_argument(
        "--never-anonymise",
        type=Path,
        default=None,
        help="Path to a user never_anonymise.toml",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print diagnostic information to stdout",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    args = parser.parse_args(argv)

    try:
        output = anonymise_pdf(
            input_path=args.input,
            output_path=args.output,
            always_anonymise_path=args.always_anonymise,
            never_anonymise_path=args.never_anonymise,
            debug=args.debug,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Anonymised: {output}")


if __name__ == "__main__":
    main()
