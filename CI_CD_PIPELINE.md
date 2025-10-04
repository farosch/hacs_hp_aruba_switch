# CI/CD Pipeline Documentation

## Overview

The HP/Aruba Switch integration uses GitHub Actions for automated testing, validation, and releasing. The pipeline consists of three independent workflows that work together to ensure code quality and proper Home Assistant/HACS compliance.

## Workflow Architecture

### 1. Test and Release (`.github/workflows/test.yml`)

**Triggers:** 
- Push to any branch
- Pull requests to main

**Jobs:**

#### test
Runs unit tests on Python 3.11 and 3.12 (matrix strategy = 2 test runs)

**Steps:**
1. Checkout code
2. Set up Python environment
3. Install dependencies (paramiko)
4. Run unit tests with test data files
5. Compile all Python files
6. Validate manifest.json format

**Purpose:** Ensure code quality and compatibility across Python versions.

#### release
Creates GitHub release (only on main branch after tests pass)

**Runs ONLY when:**
- Tests pass successfully (`needs: test`)
- Push is to the `main` branch
- Event is a push (not a pull request)
- Tag for current version doesn't exist yet

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

### 2. Validate with hassfest (`.github/workflows/hassfest.yaml`)

**Triggers:** 
- Push to any branch
- Pull requests
- Daily schedule (cron: "0 0 * * *")

**Jobs:**

#### validate
Validates integration against Home Assistant standards
- Uses official Home Assistant hassfest action
- Checks manifest structure, dependencies, and integration requirements
- Ensures compatibility with Home Assistant core

### 3. Validate (`.github/workflows/validate.yaml`)

**Triggers:** 
- Push to any branch
- Pull requests
- Daily schedule (cron: "0 0 * * *")
- Manual trigger (workflow_dispatch)

**Jobs:**

#### validate-hacs
Validates integration against HACS requirements
- Checks HACS compatibility
- Validates integration structure for HACS store
- Ensures proper HACS integration format

## Expected Check Results

### On Any Branch Push

You should see **4 checks**:
1. ✅ `Test and Release / test (3.11)` - Unit tests with Python 3.11
2. ✅ `Test and Release / test (3.12)` - Unit tests with Python 3.12
3. ✅ `Validate with hassfest / validate` - Home Assistant validation
4. ✅ `Validate / validate-hacs` - HACS validation

### On Main Branch Push

You should see **5 checks**:
1. ✅ `Test and Release / test (3.11)` - Unit tests with Python 3.11
2. ✅ `Test and Release / test (3.12)` - Unit tests with Python 3.12
3. ✅ `Validate with hassfest / validate` - Home Assistant validation
4. ✅ `Validate / validate-hacs` - HACS validation
5. ✅ `Test and Release / release` - Release creation (if all conditions met)

## Workflow Independence

The three workflows run **independently** and in parallel:
- They all trigger on the same events (push, pull_request)
- The release job only depends on the test job from the same workflow
- This separation keeps the workflows simple and maintainable

**Important:** The release job doesn't explicitly depend on hassfest and HACS validation, but in practice:
- If those validations fail, you should not merge/push to main
- Use GitHub branch protection rules to enforce all checks pass before merge
- The release won't work properly if HACS/Home Assistant validations fail

## Version Management

The version is defined in **one place only**:
- File: `custom_components/hp_aruba_switch/manifest.json`
- Field: `"version": "1.0.8"`

The pipeline automatically:
- Extracts the version from manifest.json
- Creates a tag with "v" prefix (e.g., `v1.0.8`)
- Uses this tag for the GitHub release

## Release Process

### Automatic Release Creation

To create a new release:
1. Update version in `manifest.json` (e.g., from `1.0.8` to `1.0.9`)
2. Update `RELEASE_NOTES.md` with changes
3. Commit and push to `main` branch
4. Pipeline automatically creates the release

### Preventing Duplicate Releases

The release job includes duplicate prevention:
```yaml
- name: Check if tag exists
  # Checks if tag already exists in repository
  # If exists: skips release creation
  # If not exists: creates new release
```

### Pushing to Main Without Creating a Release

To push to main **without creating a release**, create the tag first:
```bash
git tag v1.0.8
git push origin v1.0.8
git push origin main
```

This way, when the workflow runs, it finds the tag already exists and skips release creation.

## Release Notes

The release description is automatically populated from `RELEASE_NOTES.md`.

### Current Release Notes Structure

```markdown
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
- `show_interface_all.txt` - Interface configuration output
- `show_interface_brief.txt` - Brief interface status output
- `show_power_over_ethernet_all.txt` - PoE port information
- `show_version.txt` - Switch version information

These files contain real output from HP/Aruba switches for parser validation.

### CI Testing

The CI pipeline:
- Runs tests on Python 3.11 and 3.12
- Uses test data files (not real switch)
- Validates Python syntax and compilation
- Checks manifest.json structure

## Permissions

The workflow requires `contents: write` permission to create releases and tags.

## Complete Workflow Example

1. Developer updates `manifest.json` version from `1.0.8` to `1.0.9`
2. Developer updates `RELEASE_NOTES.md` with new features
3. Developer commits and pushes to `main`
4. GitHub Actions triggers:
   - ✅ Tests run on Python 3.11 and 3.12
   - ✅ All files compile successfully
   - ✅ manifest.json is valid
   - ✅ Hassfest validates Home Assistant compatibility
   - ✅ HACS validation passes
   - 🏷️ Extracts version `1.0.9`
   - 🔍 Checks if tag `v1.0.9` exists (it doesn't)
   - 🎉 Creates release `v1.0.9` with contents from `RELEASE_NOTES.md`
5. Users can now install version `v1.0.9` from GitHub

## Branch Protection Rules (Recommended)

To ensure all validations pass before merging to main:

1. Go to Repository Settings → Branches
2. Add branch protection rule for `main`
3. Enable "Require status checks to pass before merging"
4. Select all 4 checks:
   - `Test and Release / test (3.11)`
   - `Test and Release / test (3.12)`
   - `Validate with hassfest / validate`
   - `Validate / validate-hacs`

This prevents merging code that fails any validation.

## Troubleshooting

### Release Not Created

**Symptom:** Push to main doesn't create a release.

**Possible causes:**
- Tests failed
- Tag already exists for that version
- Insufficient GitHub permissions
- Not pushing to main branch

**Solution:** 
- Check test job logs for failures
- Verify you're on the main branch: `git branch`
- Check if tag exists: `git tag -l "v1.0.8"`
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
- Check dependency installation step in workflow
- Run tests locally with same Python version as CI

### Validation Failures

**Symptom:** Hassfest or HACS validation fails.

**Possible causes:**
- Invalid manifest.json structure
- Missing required fields
- Incompatible dependencies
- Wrong integration structure

**Solution:**
- Check workflow logs for specific errors
- Validate manifest.json locally: `python -c "import json; json.load(open('custom_components/hp_aruba_switch/manifest.json'))"`
- Review Home Assistant integration requirements
- Review HACS integration requirements

### Too Many Checks Running

**Symptom:** More than 4-5 checks running on push.

**Possible causes:**
- Duplicate workflow files
- Old workflows not deleted

**Solution:**
- Check `.github/workflows/` directory for duplicate files
- Ensure only 3 workflow files exist: `test.yml`, `hassfest.yaml`, `validate.yaml`

## Current Version

**Version:** 1.0.7  
**Tag:** v1.0.7  
**Last Updated:** October 5, 2025
