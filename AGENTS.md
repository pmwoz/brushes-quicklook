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

## Code rules

- Swift 6, strict concurrency, hardened runtime and App Sandbox on every
  target.
- The extensions must never crash on a hostile file. Parse errors become a
  visible error state in the preview and a badge-only thumbnail.
- No conversion, editing or stroke simulation. This is a viewer.
