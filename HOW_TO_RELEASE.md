# Quick Start: Creating a New Release

## Step-by-Step Guide

### 1. Update Version

Edit `custom_components/hp_aruba_switch/manifest.json`:

```json
{
  "domain": "hp_aruba_switch",
  "name": "HP/Aruba Switch",
  "version": "1.0.9"  ← Change this
}
```

### 2. Update Release Notes

Edit `RELEASE_NOTES.md` with your changes:

```markdown
# Release v1.0.9 - Bug Fixes and Improvements

## 🐛 Bug Fixes
- Fixed issue with port detection
- Improved error handling

## 🚀 Improvements
- Better performance for large switches
- Enhanced logging
```

### 3. Commit and Push

```bash
git add custom_components/hp_aruba_switch/manifest.json
git add RELEASE_NOTES.md
git commit -m "Release v1.0.9"
git push origin main
```

### 4. Watch the Magic Happen! ✨

The pipeline will automatically:

1. ✅ Run tests on Python 3.11 and 3.12
2. ✅ Compile all Python files
3. ✅ Validate manifest.json
4. 🏷️ Extract version (1.0.9)
5. 🔍 Check if tag v1.0.9 exists
6. 🎉 Create release v1.0.9 with your release notes
7. 📦 Tag the commit as v1.0.9

### 5. Verify Release

Go to: https://github.com/farosch/hp_aruba_switch/releases

You should see your new release! 🎊

---

## Working on Feature Branches

When working on feature branches:

```bash
# Create feature branch
git checkout -b feature/awesome-feature

# Make changes, commit
git add .
git commit -m "Add awesome feature"

# Push to feature branch
git push origin feature/awesome-feature
```

✅ **Tests will run automatically!**  
❌ **No release will be created** (not main branch)

When ready, create a Pull Request to merge into main.

---

## Testing Locally Before Release

Always test before pushing to main:

```bash
# Run unit tests with test data
python tests/run_tests.py

# Test specific parsers
python tests/test_password_escape.py

# Validate manifest
python -c "import json; json.load(open('custom_components/hp_aruba_switch/manifest.json'))"
```

---

## Troubleshooting

### "Release already exists"

If you push to main but forgot to bump the version:

```bash
# Option 1: Delete the tag and release (if needed)
git tag -d v1.0.8
git push origin :refs/tags/v1.0.8
# Then delete the release on GitHub manually

# Option 2: Bump the version and push again
# Edit manifest.json → version: "1.0.9"
git commit -am "Bump version to 1.0.9"
git push origin main
```

### Tests Failing

Check the Actions tab on GitHub:
https://github.com/farosch/hp_aruba_switch/actions

Common issues:
- Missing test data files
- Python syntax errors
- Import errors

Fix the issues and push again - tests will re-run automatically!

---

## Current Configuration

**Current Version:** 1.0.8  
**Next Release Tag:** v1.0.9 (when you bump the version)

**Workflow File:** `.github/workflows/test.yml`  
**Version File:** `custom_components/hp_aruba_switch/manifest.json`  
**Release Notes:** `RELEASE_NOTES.md`

**Pipeline Status:** ✅ Active and ready!

---

## Advanced: Manual Release Creation

If you need to create a release manually:

```bash
# Create and push a tag
git tag -a v1.0.9 -m "Release v1.0.9"
git push origin v1.0.9

# Then create release on GitHub:
# Go to: Releases → Draft a new release
# Choose tag: v1.0.9
# Copy content from RELEASE_NOTES.md
# Publish release
```

But the automated pipeline is much easier! 🚀
