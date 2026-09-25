# Brushes Quick Look

Brush previews in Finder. A small macOS app that installs two Quick Look
extensions for Photoshop `.abr` and Procreate `.brush` and `.brushset` files:
thumbnails in icon view and a space-bar preview showing every brush tip in the
file, without opening Photoshop or Procreate.

Status: the space-bar preview shows the brush grid. Finder thumbnails show
brush tips with a format badge.

## What the thumbnail shows

A 2×2 grid of the first four available tips with a format badge, blue for
Photoshop and orange for Procreate. Fewer than four tips or icons smaller than
64 points on either side show a single tip. Below 64 points a colour strip
along the bottom edge replaces the badge. Files with no available tips show a
brush glyph, and files that fail to load show a warning glyph.

## What the preview shows

A grid of brush tip shapes that adds columns as the panel widens. A file with
a single brush shows one large tip instead.

- Name, tip bitmap and original raster dimensions when known. Computed tips
  and unreadable raster headers show an unknown size.
- Brushes in file order with a total count, including brushes that have no
  usable preview.
- A "No preview" cell that says why in plain words, never a silently skipped
  brush.
- Small tips are not enlarged past 2 points per source pixel.

Not in scope: converting, editing or simulating strokes. This is a viewer.

## How it is built

- `App/` is the host application. macOS registers Quick Look extensions only
  from an app bundle, so the app exists mainly to carry them and to show
  install instructions.
- `Preview/` is the `QLPreviewingController` extension for the space-bar
  preview.
- `Thumbnail/` is the `QLThumbnailProvider` extension for Finder icons.
- `ffi/` is a thin Rust crate with an `extern "C"` surface that exposes the
  parsing and tip rendering from the [`brushkit`](https://github.com/pmwoz/brushkit)
  crates to Swift. It builds as a universal static library that the two
  extensions link.

Format parsing lives in `brushkit`. Parsing bugs go there.

Known limits inherited from the parser: some Photoshop tip kinds are not yet
supported and show as unavailable, and Procreate brushes without their own
`Shape.png` have no preview.

## Building

Requires Xcode, `rustup` and `xcodegen`. `rustup` from rustup.rs or from
Homebrew both work. With Homebrew, add `$(brew --prefix rustup)/bin` to
`PATH` to run the `cargo` commands below. `rust-toolchain.toml` pins the Rust
version, the `clippy` component and both macOS targets. `rustup` installs them
on the first `cargo` run, so a local build and CI use the same Rust. A Rust
update is a change to that file.

```
xcodegen generate
xcodebuild -project BrushesQuickLook.xcodeproj -scheme BrushesQuickLook -configuration Debug -derivedDataPath build.noindex build
```

The checks CI runs after a Release build live in `scripts/check-build.sh` and
take the built app path. CI runs the same steps on GitHub's `macos-26` image.

Run `scripts/install.sh` to build and check Release, replace
`/Applications/BrushesQuickLook.app`, and register the app and both extensions.
It first unregisters every other copy of the app that LaunchServices knows,
including the one `xcodebuild` registers for its own build product, so System
Settings lists the app once. Build products live in `build.noindex`, which
Spotlight skips, so an unregistered build is not registered again by indexing.

Tests:

`ffi/tests/corpus` mirrors brushkit's fuzz seed corpus and is replayed by `cargo test`.
`scripts/check-corpus.sh` checks the mirror against the pinned brushkit tag.
`scripts/preview-hostile.sh` previews a folder of corrupt files through Finder's
Quick Look and reports which ones the extension handled and whether it crashed.

```
cargo test --manifest-path ffi/Cargo.toml
xcodebuild -project BrushesQuickLook.xcodeproj -scheme BrushesPreviewTests -derivedDataPath build.noindex test
```

## Installing a release

Download the DMG from Releases, move the app to Applications and open it once.
macOS registers the extensions on first launch. If Finder still shows generic
icons, enable them under System Settings > General > Login Items & Extensions
> Quick Look.

## Decisions

- **Native Swift + Rust static library in the extension.** Confirmed by a
  throwaway spike (issue #1). A universal `staticlib` with an `extern "C"`
  surface links into a sandboxed, hardened-runtime `QLPreviewingController`
  extension and renders a 441-brush `.abr` in under 300 ms. Peak memory for
  that file was 577 MB because tips were decoded at full size; the preview
  crate decodes to the cell size instead.
- **The host app imports the UTTypes.** Without it, `.abr`, `.brush` and
  `.brushset` resolve to dynamic UTIs and Quick Look never routes them to the
  extension. The exact declarations are in issue #1.
- **Errors surface as text.** A file that cannot be previewed shows an error
  view inside the preview with a plain message. For a damaged file the
  parser's text is under Details. No blank window, no crash.
- **Previews are limited to 512 MB and 10 seconds.** Files above the size
  ceiling are refused before parsing. Reading into memory instead of mapping
  removes the SIGBUS path when a file shrinks while open. Timed-out work
  finishes in the background and its result is discarded.

## License

MIT. See `LICENSE`.
