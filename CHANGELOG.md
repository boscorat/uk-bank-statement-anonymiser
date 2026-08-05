# Changelog

All notable changes to this project will be documented in this file.

This project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.3] - 2026-08-05

## Overview
No breaking changes and one new feature.
You can now pass a flag to prevent the scrambling of text during an anonymise run.
You'll need to provide a user always anonymise file and specify the name and address details you do want to anonymise, but this will then not anonymise the transaction descriptions.
This can be useful for tests and demonstrations, but you should be careful before sharing these documents as the recipient will have certain information that could be used to verify your identity e.g. 'How do you pay your gas bill and what was the last payment?'

## What's Changed
* ci: simplify release workflow by @boscorat in https://github.com/boscorat/uk-bank-statement-anonymiser/pull/41
* 37 feature enable the retention of transaction descriptions by @boscorat in https://github.com/boscorat/uk-bank-statement-anonymiser/pull/43

**Full Changelog**: https://github.com/boscorat/uk-bank-statement-anonymiser/compare/v0.2.2...v0.2.3

## [0.2.2] - 2026-08-04

### Added

- feat: add retain_descriptions flag to preserve transaction descriptions (#38)
- docs: document retain_descriptions flag in README

## [0.2.1] - 2026-07-30

### Added

- docs: update technical diagram and add customisation architecture diagram (#27)
- Clean up CHANGELOG by removing merged PR entries
- docs: update CHANGELOG.md for v0.2.0



## [0.2.0] - 2026-07-29

### Added

- test: remove duplicate scramble map/text tests across 3 files
- Add review request template and step-by-step contributor guide (#24)
- Update checklist format in TEMPLATE.md
- Improve review template with table-based checklist and overall verdict
- fix: correct CHANGELOG.md update step in release.yml
- docs: strengthen PII warnings and split bug report templates
- release.yml formatting and indentation corrected
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
