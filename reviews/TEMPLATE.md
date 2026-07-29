# Anonymisation Review: [Bank Name] — [Account Type]

> **Privacy:** Do not include any real personal data (names, account numbers, addresses). Describe issues generically.

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

- **always_anonymise.toml:** <!-- e.g. "added my name as a forced replacement" -->
- **never_anonymise.toml:** <!-- e.g. "protected my employer name" -->

## Checklist

<!-- Mark each item as PASS or FAIL and add a comment if needed. -->

| Status | Check | Comment |
|--------|-------|---------|
| ✅ PASS | All account numbers are anonymised | |
| ✅ PASS | All sort codes are anonymised (if applicable) | |
| ✅ PASS | All names are anonymised | |
| ✅ PASS | All addresses are anonymised | |
| ✅ PASS | No transaction values are anonymised | |
| ✅ PASS | No transaction types are anonymised | |
| ✅ PASS | No personally identifiable information is left | |
| ✅ PASS | All `always_anonymise` instances are replaced by the specified value | |
| ✅ PASS | None of the `never_anonymise` exclusions are anonymised | |

## Overall Verdict

> If **ALL** checklist items are PASS, choose **PASS**.
> If **ANY** item is FAIL, choose **FAIL**.

**Verdict:** [ ] PASS  [ ] FAIL

## Additional Notes

<!-- Any other observations about the anonymisation quality, layout preservation, etc. -->
