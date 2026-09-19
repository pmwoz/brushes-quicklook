# Brushes Quick Look

Brush previews in Finder. A small macOS app that installs two Quick Look
extensions for Photoshop `.abr` and Procreate `.brush` and `.brushset` files:
thumbnails in icon view and a space-bar preview showing every brush tip in the
file, without opening Photoshop or Procreate.

Status: architecture proven by a spike, no Swift code committed yet. See the
open issues for the build order.

## What the preview shows

A grid of brush tip shapes.

- Name, tip bitmap and pixel dimensions of every brush.
- Brushes in file order with a total count, including brushes that have no
  usable preview.
- An explicit "preview unavailable" cell with the reason, never a silently
  skipped brush.

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

Requires Xcode, a Rust toolchain with the `aarch64-apple-darwin` and
`x86_64-apple-darwin` targets, and `xcodegen`.

```
xcodegen generate
xcodebuild -scheme BrushesQuickLook -configuration Debug build
```

Tests:

```
cargo test --manifest-path ffi/Cargo.toml
xcodebuild -scheme BrushesQuickLook test
```

The exact commands are filled in once the scaffold lands.

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
- **Errors surface as text.** When parsing fails, the extension hands the
  library's message to Quick Look, which shows it above the generic file card.
  No blank window, no crash.

## License

MIT. See `LICENSE`.
