# Host app

`BrushesQuickLook.app` carries the two extensions and imports the `.abr`,
`.brush` and `.brushset` types. Opening it shows one window with install
instructions. macOS registers the extensions when the app is opened for the
first time.

## Sub-features

- `app-window` shows the title "Brushes Quick Look" and two instruction lines, one about moving the app to Applications and one about the System Settings path.
- `app-registration` means that after install, pluginkit lists exactly one enabled copy of each extension, inside `/Applications`.
- `app-types` means the imported UTTypes route brush files to the extensions, which the thumbnail and preview features confirm.

## How to get to it (user POV)

- Move the app to Applications and open it.
- System Settings > General > Login Items & Extensions > Quick Look lists both extensions.

## Driving it with bql

Preconditions:

- Baseline preconditions from the index.

- **Install and open.** Run `bql install`. The JSON lists the steps
  `build, check-build, unregister N stale paths, replace, register, verify` and
  the app window opens.
- **Registration.** Run `bql doctor`. `pluginkit-preview` and
  `pluginkit-thumbnail` are `ok` with one `+` line each, ending in the
  `/Applications/.../PlugIns/*.appex` path.
- **Window.** With the app open, find its window id with
  `osascript -l JavaScript -e 'ObjC.import("CoreGraphics"); ObjC.deepUnwrap(ObjC.castRefToObject($.CGWindowListCopyWindowInfo($.kCGWindowListOptionOnScreenOnly, $.kCGNullWindowID))).find(w => w.kCGWindowOwnerName === "BrushesQuickLook").kCGWindowNumber'`.
  Then run `screencapture -x -o -l <id> build.noindex/verify/evidence/host-app.png`. The PNG shows
  "Brushes Quick Look" and both instruction lines.
- **Types.** Run the `bql thumb` recipes from [thumbnail.md](./thumbnail.md) and
  the `bql preview` recipes from [preview.md](./preview.md) across `.abr`,
  `.brush` and `.brushset` files. A card with a badge or strip instead of a
  generic icon, and a preview result with `extension.binary`, prove Quick Look
  resolved each type to both extensions.
- **Proof.** The install JSON, the doctor JSON and the window PNG.

## Gotchas

- `bql install --dry-run` changes nothing. Use it to see which stale copies would be unregistered.
- `bql install` replaces the only registered copy on this Mac. Another
  session's verification is lost. Check `bql doctor` first.
- `bql cleanup` quits the app only when `bql install` opened it.
