# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-07-29

### Added

- Merge pull request #25 from boscorat/dedup-test-suite
- test: remove duplicate scramble map/text tests across 3 files
- Add review request template and step-by-step contributor guide (#24)
- Merge pull request #19 from boscorat/boscorat-patch-1
- Update checklist format in TEMPLATE.md
- Merge pull request #18 from boscorat/17-feature-improve-template-for-bank-account-review
- Improve review template with table-based checklist and overall verdict
- Merge pull request #15 from boscorat/fix/pii-warnings
- fix: correct CHANGELOG.md update step in release.yml
- docs: strengthen PII warnings and split bug report templates
- release.yml formatting and indentation corrected
- Merge pull request #14 from boscorat/9-conduct-launch-suitability-review
- FIX: repo with only one tag breaks detection
- chore: bump development status to Production/Stable
- ci: add issue templates, PR template, CODEOWNERS, and dependabot config
- ci: add pytest-cov to dev dependencies
- docs: add Related projects section with cross-references to openstan and bank_statement_parser
- docs: add CHANGELOG.md and automate release notes from git log
- feat: contributor local testing system (#12) (#13)
- Fix CI to run on PRs targeting master; fix lint errors (#11)
- bank statement anonymiser tests (#10)
- Code Review - Fix/high medium priority issues (#7)



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
