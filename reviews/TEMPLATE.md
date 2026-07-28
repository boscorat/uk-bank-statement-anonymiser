# Anonymisation Review: [Bank Name] — [Account Type]

| Field | Value |
|-------|-------|
| **Contributor** | @your-github-username |
| **Bank Name** | e.g. HSBC |
| **Account Type** | e.g. Advance Current Account |
| **Statement Date** | e.g. January 2024 |
| **Date Reviewed** | YYYY-MM-DD |
| **anonymise-pdf version** | e.g. 0.1.7 |

## Configuration Used

<!-- Which config files did you use? Leave blank if none. -->

- **always_anonymise.toml:** Yes / No — <!-- brief description of what you configured, e.g. "added my name as a forced replacement" -->
- **never_anonymise.toml:** Yes / No — <!-- brief description, e.g. "protected my employer name" -->

## Checklist

Mark each item as pass or fail.

- [ ] All account numbers are anonymised
- [ ] All sort codes are anonymised (if applicable)
- [ ] All names are anonymised
- [ ] All addresses are anonymised
- [ ] No transaction values are anonymised
- [ ] No transaction types are anonymised
- [ ] No personally identifiable information is left
- [ ] All `always_anonymise` instances are replaced by the specified value
- [ ] None of the `never_anonymise` exclusions are anonymised

## Failure Details

<!-- For any items you marked as fail, describe what went wrong. -->
<!-- If all items passed, you can delete this section or leave it blank. -->

## Additional Notes

<!-- Any other observations about the anonymisation quality, layout preservation, etc. -->
