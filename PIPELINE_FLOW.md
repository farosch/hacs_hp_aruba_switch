# CI/CD Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      TRIGGER: Push to ANY branch                │
│                   OR Pull Request to main branch                │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         TEST JOB (Always)                       │
├─────────────────────────────────────────────────────────────────┤
│  Matrix: Python 3.11 & 3.12                                     │
│                                                                  │
│  Steps:                                                          │
│  1. ✓ Checkout code                                             │
│  2. ✓ Setup Python                                              │
│  3. ✓ Install dependencies (paramiko)                           │
│  4. ✓ Run unit tests (tests/run_tests.py)                       │
│  5. ✓ Compile Python files                                      │
│  6. ✓ Validate manifest.json                                    │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │   Tests Pass?     │
                    └─────────┬─────────┘
                              │
                 ┌────────────┴────────────┐
                 │                         │
              ❌ NO                     ✅ YES
                 │                         │
                 ▼                         ▼
          ┌──────────┐          ┌──────────────────┐
          │   FAIL   │          │ Is main branch?  │
          │   STOP   │          └────────┬─────────┘
          └──────────┘                   │
                                ┌────────┴────────┐
                                │                 │
                             ❌ NO             ✅ YES
                                │                 │
                                ▼                 ▼
                         ┌──────────┐   ┌──────────────────┐
                         │   DONE   │   │  RELEASE JOB     │
                         └──────────┘   └────────┬─────────┘
                                                  │
        ┌─────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                    RELEASE JOB (Main Branch Only)               │
├─────────────────────────────────────────────────────────────────┤
│  Condition: Tests passed AND push to main                       │
│                                                                  │
│  Steps:                                                          │
│  1. 📦 Extract version from manifest.json                        │
│     └─> version: "1.0.8"                                        │
│                                                                  │
│  2. 🏷️  Generate tag name                                        │
│     └─> tag: "v1.0.8"                                           │
│                                                                  │
│  3. 🔍 Check if tag v1.0.8 already exists                        │
│     └─┬─> YES: Skip release (tag exists)                        │
│       └─> NO: Continue to step 4                                │
│                                                                  │
│  4. 🎉 Create GitHub Release                                     │
│     ├─> Tag: v1.0.8                                             │
│     ├─> Name: Release v1.0.8                                    │
│     ├─> Body: Content from RELEASE_NOTES.md                     │
│     ├─> Draft: false                                            │
│     └─> Prerelease: false                                       │
│                                                                  │
│  5. ✅ Release published!                                        │
└─────────────────────────────────────────────────────────────────┘


═══════════════════════════════════════════════════════════════════
                         VERSION CONTROL
═══════════════════════════════════════════════════════════════════

  Single Source of Truth:
  📄 custom_components/hp_aruba_switch/manifest.json
  
  {
    "version": "1.0.8"  ← Change this to trigger new release
  }
  
  To Create New Release:
  1. Edit manifest.json → bump version
  2. Edit RELEASE_NOTES.md → describe changes
  3. Commit & push to main
  4. Pipeline auto-creates release!


═══════════════════════════════════════════════════════════════════
                         EXAMPLE SCENARIOS
═══════════════════════════════════════════════════════════════════

Scenario 1: Feature Branch Development
  ├─> Developer pushes to branch "feature/new-sensor"
  ├─> ✅ Tests run
  ├─> ✅ All checks pass
  └─> ❌ NO release (not main branch)

Scenario 2: Push to Main (New Version)
  ├─> Developer pushes to main with version 1.0.9
  ├─> ✅ Tests run
  ├─> ✅ All checks pass
  ├─> 🔍 Check tag v1.0.9 → doesn't exist
  ├─> 🎉 Create release v1.0.9
  └─> ✅ Release published!

Scenario 3: Push to Main (Same Version)
  ├─> Developer pushes to main (version still 1.0.8)
  ├─> ✅ Tests run
  ├─> ✅ All checks pass
  ├─> 🔍 Check tag v1.0.8 → already exists
  └─> ⏭️  Skip release (tag exists)

Scenario 4: Pull Request
  ├─> Developer opens PR to main
  ├─> ✅ Tests run
  ├─> ✅ All checks pass
  └─> ❌ NO release (PR, not push)


═══════════════════════════════════════════════════════════════════
                      RELEASE NOTES FORMAT
═══════════════════════════════════════════════════════════════════

  📄 RELEASE_NOTES.md becomes the release body
  
  Current format:
  ┌───────────────────────────────────────────────────────────┐
  │ # Release v1.0.8 - Architecture Refactoring               │
  │                                                            │
  │ ## ⚠️ BREAKING CHANGES                                     │
  │ **IMPORTANT: Requires uninstalling and reinstalling**     │
  │                                                            │
  │ ## 🚀 New Features                                         │
  │ - Dynamic port detection...                               │
  │                                                            │
  │ ## 🐛 Bug Fixes                                            │
  │ - Fixed platform unloading...                             │
  └───────────────────────────────────────────────────────────┘

```
