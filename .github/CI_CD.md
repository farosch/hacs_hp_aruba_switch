# CI/CD Pipeline Documentation

## Overview

The HP/Aruba Switch integration uses GitHub Actions for continuous integration and deployment.

## Workflow Behavior

### On Push to Any Branch
- **Tests run** on Python 3.11 and 3.12
- Validates Python syntax
- Runs parser tests with local test data files
- Checks manifest version

### On Push to Main Branch (After Tests Pass)
- **Automatically creates a GitHub Release**
- Version is read from `manifest.json`
- Tag format: `v{version}` (e.g., `v1.0.8`)
- Creates a ZIP file of the integration
- Includes release notes from `RELEASE_NOTES.md`

## How to Create a New Release

1. Update the version in `custom_components/hp_aruba_switch/manifest.json`
2. Update `RELEASE_NOTES.md` with changes for the new version
3. Commit and push to main branch:
   ```bash
   git add custom_components/hp_aruba_switch/manifest.json RELEASE_NOTES.md
   git commit -m "Release v1.0.X"
   git push origin main
   ```
4. GitHub Actions will:
   - Run all tests
   - Create tag `v1.0.X`
   - Create GitHub Release with ZIP file
   - Extract release notes for the version

## Skipping Duplicate Releases

If a tag already exists for the version in `manifest.json`, the release step will be skipped with a warning. To create a new release, increment the version number.

## Local Testing

Before pushing, you can run tests locally:

```bash
# Run all tests (including local test data)
python tests/run_tests.py

# Run specific test modules
python tests/run_tests.py  # Includes real switch tests

# Validate syntax
python -m compileall custom_components/hp_aruba_switch/
```

## Test Data

- Unit tests use test data files in `tests/test_data/`
- Real switch integration tests require credentials (only run locally)
- CI pipeline only runs parser tests with static test data

## Release Assets

Each release includes:
- Source code (automatic from GitHub)
- `hp_aruba_switch-{version}.zip` - Ready-to-install integration package
- Release notes extracted from `RELEASE_NOTES.md`
