# Release Process

Step-by-step guide for releasing a new version to PyPI.

## Prerequisites

- PyPI Trusted Publisher configured for `publish.yml` with environment `pypi`
- GitHub environment `pypi` configured in repo Settings > Environments
- Write access to the repository

## Steps

### 1. Prepare the release branch

```bash
git checkout release
git fetch origin
git rebase origin/master
```

Cherry-pick specific commits if needed:

```bash
git cherry-pick <commit-hash>
```

### 2. Bump the version

Edit `pyproject.toml` and update the version:

```toml
[project]
version = "0.2.3"
```

### 3. Update CHANGELOG.md

Add a new entry under `[Unreleased]`:

```markdown
## [0.2.3] - 2026-08-05

### Added

- Description of new feature

### Fixed

- Description of bug fix
```

### 4. Push and create PR

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "release: v0.2.3"
git push origin release
```

Create a PR: `release` → `master`. Tests will run automatically.

### 5. Merge the PR

Merge the PR once tests pass.

### 6. Create and push the tag

```bash
git checkout master
git pull origin master
git tag v0.2.3
git push origin v0.2.3
```

### 7. Create the GitHub Release

1. Go to GitHub > Releases > "Create a new release"
2. Select the tag `v0.2.3`
3. Set the title to `v0.2.3`
4. Write the release notes (what changed since the last release)
5. Click "Publish release"

### 8. Verify PyPI

The `publish.yml` workflow will trigger automatically:
- Builds sdist and wheel
- Publishes to PyPI

Verify at: https://pypi.org/project/uk-bank-statement-anonymiser/

### 9. Reset the release branch

```bash
git checkout release
git rebase origin/master
```

The release branch is now ready for the next cycle.

## Troubleshooting

### PyPI publish fails with "Trusted publishing failed"

The Trusted Publisher on PyPI must match exactly:
- **Owner:** `boscorat`
- **Repository:** `uk-bank-statement-anonymiser`
- **Workflow:** `publish.yml`
- **Environment:** `pypi`

### Tag already exists

```bash
git tag -d v0.2.3
git push --delete origin v0.2.3
```

Then re-run step 6.

### Release notes need editing

Go to GitHub > Releases > select the release > "Edit release". You can update the notes at any time.
