# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.7] - 2026-07-03

### Added

- Core text transformation unit tests (Module 1)
- Pattern detection unit tests (Module 2)
- Font encoding unit tests (Module 3)
- Content stream processing tests (Module 4)
- Config loading tests (Module 5)
- PDF structure preservation tests (Module 6)

### Changed

- Pre-launch improvements across codebase

## [0.1.6] - 2026-06-27

### Changed

- Minimum Python version lowered from 3.14 to 3.11
- NatWest never-anonymise tweaks
- Halifax bank identifier added to never-anonymise

## [0.1.5] - 2026-06-10

### Changed

- Consolidated font decoder routing into `_decode_raw_bytes_safe()`
- Never-anonymise config tweaks

### Documentation

- Enhanced README with encoding strategies, error handling, and examples

## [0.1.4] - 2026-06-08

### Added

- Identity-H CID font support for NatWest 2025 statements
- Multi-byte CID code support in ToUnicode CMap parser

## [0.1.3] - 2026-06-08

### Added

- Halifax transaction types and structural text to never-anonymise

### Fixed

- Handle UTF-16-BE encoded ToUnicode CMaps in NatWest statements

## [0.1.2] - 2026-06-07

### Documentation

- Improved README and docstring clarity for developer audience

## [0.1.1] - 2026-06-02

### Changed

- Consolidated duplicate functions and added comprehensive test suite

## [0.1.0] - 2026-06-01

### Added

- Initial release of uk-bank-statement-anonymiser
- Anonymisation of sort codes, account numbers, IBANs, and card numbers
- Merchant name scrambling
- Layout and font preservation
- CLI entry point (`anonymise-pdf`)
- Support for HSBC, NatWest, TSB, and Halifax statements
- Custom rules via TOML config files
- Deterministic scrambling with seeded random source
