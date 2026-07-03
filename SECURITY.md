# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do NOT open a public GitHub issue**
2. Email: farrar.jason1@gmail.com or use [GitHub's private vulnerability reporting](https://github.com/boscorat/uk-bank-statement-anonymiser/security/advisories/new)
3. Include: description, steps to reproduce, potential impact

## Response Timeline

- Acknowledgement: within 48 hours
- Assessment: within 1 week
- Fix or mitigation: depends on severity

## Scope

This tool processes bank statement PDFs locally. It does not:

- Send data to any external service
- Store data persistently
- Make network requests

The primary security concern is that the tool handles sensitive financial documents. All processing happens on the user's machine with no network access.
