# How to Submit a Review

This guide explains how to test the anonymiser against your bank statement and submit a review. We provide two workflow options — choose whichever you're most comfortable with.

> **Privacy:** Your bank statement PDFs must stay on your machine — never attach them to issues, PRs, or discussions. Only submit the review file describing what you observed.

## Quick Overview

1. Anonymise your statement using `uv run anonymise-pdf statement.pdf`
2. Visually inspect the anonymised PDF
3. Fill in the review template
4. Submit a PR with your review file

For detailed step-by-step instructions, choose a workflow below.

---

## Option A: Web-only workflow (no git required)

This option uses only the GitHub web interface — no git knowledge or installation needed.

### Step 1: Fork the repository

1. Go to [github.com/boscorat/uk-bank-statement-anonymiser](https://github.com/boscorat/uk-bank-statement-anonymiser)
2. Click the **Fork** button (top right)
3. Click **Create fork** to create a copy in your GitHub account

### Step 2: Anonymise your statement

Run this command on your machine (you need Python installed):

```bash
uv run anonymise-pdf statement.pdf
```

This creates `anonymised_statement.pdf` alongside the original. The original is untouched.

### Step 3: Open and inspect the anonymised PDF

Check that:
- Personal data (account numbers, names, addresses) is scrambled
- Layout and formatting are preserved
- Transaction values and types are correct

### Step 4: Create your review file

1. In your forked repository on GitHub, navigate to the `reviews` folder
2. Click **Add file** → **Create new file**
3. In the filename field, type: `reviews/` followed by the filename using this format:
   ```
   <bank>-<account-type>-<YYYY-MM>-<your-username>.md
   ```
   Examples:
   - `hsbc-advance-current-2024-01-janedoe.md`
   - `hsbc-rewards-credit-card-2024-02-johnsmith.md`

4. Copy the contents of [TEMPLATE.md](https://github.com/boscorat/uk-bank-statement-anonymiser/blob/master/reviews/TEMPLATE.md) into the file
5. Fill in the template with your findings
6. Click **Commit changes** (use the default commit message)

### Step 5: Create a Pull Request

1. Go to your forked repository on GitHub
2. Click **Contribute** → **Open pull request**
3. Ensure the base repository is `boscorat/uk-bank-statement-anonymiser` and the head repository is your fork
4. Add a descriptive title (e.g., "Review: HSBC Advance Current Account - January 2024")
5. Click **Create pull request**

A maintainer will review your PR and may ask for follow-up.

---

## Option B: Git CLI workflow

This option uses git commands on the command line. You should have git installed on your machine.

### Step 1: Fork and clone

1. Fork the repository on GitHub (click **Fork** button)
2. Clone your fork:
   ```bash
   git clone https://github.com/<your-username>/uk-bank-statement-anonymiser.git
   cd uk-bank-statement-anonymiser
   ```

### Step 2: Create a branch

```bash
git checkout -b review/<bank>-<account-type>
```

Example:
```bash
git checkout -b review/hsbc-advance-current
```

### Step 3: Anonymise your statement

```bash
uv run anonymise-pdf statement.pdf
```

### Step 4: Create your review file

1. Copy the template:
   ```bash
   cp reviews/TEMPLATE.md "reviews/<bank>-<account-type>-<YYYY-MM>-<your-username>.md"
   ```
   Example:
   ```bash
   cp reviews/TEMPLATE.md "reviews/hsbc-advance-current-2024-01-janedoe.md"
   ```

2. Open the new file in your editor and fill in the template

### Step 5: Commit and push

```bash
git add "reviews/<your-filename>.md"
git commit -m "Add review: <Bank> <Account Type>"
git push -u origin review/<bank>-<account-type>
```

### Step 6: Create a Pull Request

1. Go to your fork on GitHub
2. Click **Compare & pull request**
3. Ensure the base repository is `boscorat/uk-bank-statement-anonymiser`
4. Add a descriptive title and click **Create pull request**

---

## File Naming Convention

Use this format for your review filename:
```
<bank>-<account-type>-<YYYY-MM>-<your-username>.md
```

Examples:
- `hsbc-advance-current-2024-01-janedoe.md`
- `hsbc-rewards-credit-card-2024-02-johnsmith.md`
- `hsbc-online-bonus-saver-2024-03-bobwilson.md`

Use lowercase, replace spaces with hyphens, and omit special characters.

## What to Check

The review template includes a full checklist. Key items:

- ✅ Account numbers, sort codes, IBANs, and card numbers are anonymised
- ✅ Names and addresses are anonymised
- ✅ Transaction values and types are **not** anonymised
- ✅ No personally identifiable information remains visible

## Privacy Reminders

- **Do not** attach your bank statement PDF (original or anonymised) to the issue or PR
- **Do not** paste log output, debug output, or console transcripts without checking for PII
- **Do** describe any issues generically without including sensitive data

## Questions?

If you get stuck or have questions, comment on the issue or start a [GitHub Discussion](https://github.com/boscorat/uk-bank-statement-anonymiser/discussions).