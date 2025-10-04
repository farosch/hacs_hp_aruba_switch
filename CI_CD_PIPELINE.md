# CI/CD Pipeline Documentation

## Overview

The HP/Aruba Switch integration uses GitHub Actions for automated testing and releasing.

## Pipeline Workflow

### Trigger Events

- **On Push**: Runs on ALL branches (`branches: ['**']`)
- **On Pull Request**: Runs for PRs targeting the `main` branch

### Jobs

#### 1. Test Job

Runs on every push to any branch and on pull requests.

**Matrix Strategy:**
- Python 3.11
- Python 3.12

**Steps:**
1. Checkout code
2. Set up Python environment
3. Install dependencies (paramiko)
4. Run unit tests with test data files
5. Compile all Python files
6. Validate manifest.json format

**Purpose:** Ensure code quality and compatibility across Python versions.

#### 2. Release Job

Runs ONLY when:
- Tests pass successfully (`needs: test`)
- Push is to the `main` branch (`if: github.ref == 'refs/heads/main'`)
- Event is a push (not a pull request)

**Steps:**
1. Extract version from `manifest.json`
2. Create tag with "v" prefix (e.g., version `1.0.8` → tag `v1.0.8`)
3. Check if tag already exists
4. Create GitHub Release (if tag doesn't exist):
   - Tag name: `v{version}`
   - Release name: `Release v{version}`
   - Release body: Contents of `RELEASE_NOTES.md`
   - Not a draft
   - Not a prerelease
5. Skip release creation if tag already exists

## Version Management

The version is defined in **one place only**:
- File: `custom_components/hp_aruba_switch/manifest.json`
- Field: `"version": "1.0.8"`

To create a new release:
1. Update version in `manifest.json`
2. Update `RELEASE_NOTES.md` with changes
3. Commit and push to `main` branch
4. Pipeline automatically creates the release

## Release Notes

The release description is automatically populated from `RELEASE_NOTES.md`.

### Current Release Notes Structure

```
# Release v1.0.8 - Architecture Refactoring

## ⚠️ BREAKING CHANGES

**IMPORTANT: This version requires uninstalling and reinstalling the integration.**

...
```

## Testing

### Local Testing

Run tests locally before pushing:

```bash
# Unit tests with test data files
python tests/run_tests.py
```

### Test Data

Test data files are located in `tests/test_data/`:
- `show_interface_all.txt`
- `show_interface_brief.txt`
- `show_power_over_ethernet_all.txt`
- `show_version.txt`

These files contain real output from HP/Aruba switches for parser validation.

## Permissions

The workflow requires `contents: write` permission to create releases and tags.

## Example Workflow

1. Developer updates `manifest.json` version from `1.0.8` to `1.0.9`
2. Developer updates `RELEASE_NOTES.md` with new features
3. Developer commits and pushes to `main`
4. GitHub Actions triggers:
   - ✅ Tests run on Python 3.11 and 3.12
   - ✅ All files compile successfully
   - ✅ manifest.json is valid
   - 🏷️ Extracts version `1.0.9`
   - 🔍 Checks if tag `v1.0.9` exists (it doesn't)
   - 🎉 Creates release `v1.0.9` with contents from `RELEASE_NOTES.md`
5. Users can now install version `v1.0.9` from GitHub

## Troubleshooting

### Release Not Created

**Symptom:** Push to main doesn't create a release.

**Possible causes:**
- Tests failed
- Tag already exists for that version
- Insufficient GitHub permissions

**Solution:** 
- Check test job logs
- Delete existing tag if needed: `git tag -d v1.0.8 && git push origin :refs/tags/v1.0.8`
- Verify repository settings → Actions → General → Workflow permissions

### Test Failures

**Symptom:** Tests fail in CI but pass locally.

**Possible causes:**
- Missing dependencies in workflow
- Python version differences
- Test data files not committed

**Solution:**
- Ensure all test data files are committed
- Check dependency installation step
- Run tests locally with same Python version

## Current Version

**Version:** 1.0.8  
**Tag:** v1.0.8  
**Last Updated:** October 4, 2025
