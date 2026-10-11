# Working in this repository

Brushes Quick Look is a macOS app that ships two Quick Look extensions for
brush files: Finder thumbnails and the space-bar preview for Photoshop `.abr`
and Procreate `.brush` and `.brushset`. Read `README.md` first for scope,
architecture and build steps.

## Process

Work is tracked in GitHub Issues and pull requests. A pull request is judged
on the diff, the tests and the description. Everything written down is
English: code, comments, commits, issues, pull requests and docs.

## Build and test

A contributor needs Xcode, `rustup` and `xcodegen`. `README.md` lists
the commands. Nothing in the build or the tests reaches a private repository,
a token or a secret. If a change would require one, it is the wrong change.

## Engine

Parsing and tip rendering come from the `brushkit` crates, pulled in through
Cargo. This repository holds only the Swift app, the two extensions and a thin
C ABI crate that exposes `brushkit` to Swift. Format parsing fixes go to
`brushkit`, not here.

## Rules and what enforces them

`bql` and `vm` live in `.claude/skills/verify-brushes-quicklook`. Quoted names
are steps in `.github/workflows/ci.yml`. An enforcer fails when its rule is
broken. "Judgment" means nothing checks the rule, so you and the reviewer do.
A pull request that adds, moves or removes an enforcer updates its row.

| Rule | Enforced by |
|---|---|
| Swift 6 with complete strict concurrency on every target. | Judgment. `SWIFT_VERSION` and `SWIFT_STRICT_CONCURRENCY` sit under `settings.base` in `project.yml`, and no target overrides them. |
| Hardened runtime and App Sandbox on every target. The Release bundle and its privacy manifests are valid. | `bql check-build` in "Check Release app", tested by `CheckBuildTest` and `PrivacyManifestTest`. |
| The extensions never crash on a hostile file. | `bql hostile` in "Hostile sweep". |
| A parse error becomes a visible error state in the preview and a warning glyph in the thumbnail. | `PreviewTests` and `ThumbnailTests` in "Test preview". |
| The app is a viewer. No conversion, editing or stroke simulation. | Judgment. |
| The File menu holds only Open…, Open Recent, Close, Close All and Share. | `FileMenuTests` in "Test preview". The `menu` case of `bql app` in "Check host app". |
| The host app shows the right windows on launch, on macOS 26 and on macOS 14. | `bql app` in "Check host app" on macOS 26. Judgment on macOS 14. A change to `App/` or `project.yml` runs `vm run --image sonoma app` before review, because GitHub retires its hosted macOS 14 runners on 2026-11-02. |
| One readiness check decides whether the Mac can verify, for `bql doctor` and `bql install` alike. | `ReadinessTest`, `DoctorTest` and `InstallTest` in "Test bql". |
| `/Applications` holds `origin/main` between sessions. | Judgment. Run `bql install --main` after a merge. |
| Unit tests never touch the checkout's real VM state. | The `tearDownModule` guard in `test_vm.py`, in "Test bql". |
| Evidence waits poll and never sleep. | `SleepLintTest` in "Test bql". A needed sleep carries `# sleep-ok: <reason>` on its line. |

These rules are judgment only:

- Every verification claim in a pull request names the command, the build and
  the OS it ran on, or says it was not run.
- A defect you find in your own pull request is fixed in that pull request,
  unless the operator approves deferring it.
