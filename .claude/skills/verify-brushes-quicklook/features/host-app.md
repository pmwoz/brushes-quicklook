# Host app

`BrushesQuickLook.app` carries the two extensions and imports the `.abr`,
`.brush` and `.brushset` types. Opening it shows a setup window that says what
the app does, explains the one setup step and has a button that opens the Quick
Look extensions in System Settings. The app also opens brush files and shows
the same grid, single-brush layout and error view as the space-bar preview.
macOS registers the extensions when the app is opened for the first time.

## Sub-features

- `app-window` shows the app icon, "Brushes Quick Look", one line on what the app does, one line on turning on BrushesPreview and BrushesThumbnail with the System Settings path, the buttons "Open System Settings" and "Open Brush File…", and a line about dropping files on the window.
- `app-settings` means "Open System Settings" opens the Quick Look sheet of General > Login Items & Extensions, which lists BrushesPreview and BrushesThumbnail under BrushesQuickLook.
- `app-open` means a brush file opened in the app shows a 760 × 600 window titled with the file name and the preview's content: the grid, the single-brush layout or "This file can’t be previewed".
- `app-open-ways` covers the entry points: File > Open, "Open Brush File…", a drop on the setup window, and Open With in Finder, which `open -a` stands in for. The app is an Alternate handler: it ranks below any app that claims these types and opens them on double-click only when no other app does.
- `app-file-menu` means the File menu has Open, Open Recent, Close and Close All and no Save, Save As, Duplicate, Rename, Move To or Revert To, with or without a brush file open.
- `app-registration` means that after install, pluginkit lists exactly one enabled copy of each extension, inside `/Applications`.
- `app-types` means the imported UTTypes route brush files to the extensions, which the thumbnail and preview features confirm.

## How to get to it (user POV)

- Move the app to Applications and open it. The setup window opens.
- Click "Open System Settings", or go to System Settings > General > Login Items & Extensions > Quick Look.
- Choose File > Open or "Open Brush File…", drop brush files on the setup window, or use Open With > BrushesQuickLook in Finder.

## Driving it with bql

Preconditions:

- Baseline preconditions from the index.
- `A=/Applications/BrushesQuickLook.app` is set in the shell.
- File > Open and the button clicks use System Events, which needs Accessibility for the terminal.

- **Install and open.** Run `bql install`. The JSON lists the steps
  `build, check-build, unregister N stale paths, quit, replace, register, verify` and
  the setup window opens.
- **Registration.** Run `bql doctor`. `pluginkit-preview` and
  `pluginkit-thumbnail` are `ok` with one `+` line each, ending in the
  `/Applications/.../PlugIns/*.appex` path.
- **Window ids.** List the app's windows with
  `osascript -l JavaScript -e 'ObjC.import("CoreGraphics"); JSON.stringify(ObjC.deepUnwrap(ObjC.castRefToObject($.CGWindowListCopyWindowInfo($.kCGWindowListOptionOnScreenOnly, $.kCGNullWindowID))).filter(w => w.kCGWindowOwnerName === "BrushesQuickLook" && w.kCGWindowLayer === 0).map(w => [w.kCGWindowNumber, w.kCGWindowName]))'`.
  The setup window is named "Brushes Quick Look". A document window is named after its file.
- **Setup window.** Quit the app, then run `open "$A"`. The window list holds only
  "Brushes Quick Look", 520 × 415 pt, and no Open panel appears. Run
  `screencapture -x -o -l <id> build.noindex/verify/evidence/host-app.png`. The
  PNG shows every line and both buttons from `app-window`.
  The Open panel appeared only on macOS 14 (#114), so only a macOS 14 Mac or
  VM proves the "no Open panel" check. Launching with
  `open "$A" --args -NSShowAppCentricOpenPanelInsteadOfUntitledFile YES` there
  brings the panel back.
- **Settings button.** Run `osascript -e 'tell application "System Events" to tell process "BrushesQuickLook" to click button 1 of group 1 of window "Brushes Quick Look"'`.
  System Settings shows the Quick Look sheet over Login Items & Extensions, with
  BrushesPreview and BrushesThumbnail under BrushesQuickLook. This works whether
  or not System Settings was already open. Capture it by the window ids of
  `pgrep -x "System Settings"` from the same CoreGraphics list, filtered by
  `kCGWindowOwnerPID`. The sheet is the id with an empty name.
- **Open a file.** Run `open -a "$A" $F/zero_area_tip.abr $F/ordered_set.brushset $F/root_brush.brush $F/v2_rle_overflow.abr`.
  Four 760 × 600 windows open, named after the files. `zero_area_tip` reads
  `2 brushes · 1 without preview`, `ordered_set` shows "Ordered" with
  `2 brushes · Procreate brush set`, `root_brush` shows the single-brush layout
  with "A" and `16 × 8 px`, and `v2_rle_overflow` shows "This file can’t be
  previewed", "The file looks damaged or incomplete." and a collapsed "Details".
  With the app not running, the same command opens only the document windows.
  The setup window opened next to them only on macOS 14 (#115), so only a
  macOS 14 Mac or VM proves this check.
- **File > Open.** Run
  `osascript -e 'tell application "System Events" to tell process "BrushesQuickLook"' -e 'set frontmost to true' -e 'click menu item "Open…" of menu 1 of menu bar item "File" of menu bar 1' -e 'end tell'`,
  then type the path in the panel with Command-Shift-G and press Return twice.
  A window named after the file opens. `click button 2 of group 1 of window "Brushes Quick Look"`
  ("Open Brush File…") opens the same panel.
- **File menu.** With `ordered_set.brushset` open, list the menu with
  `osascript -l JavaScript -e 'const p = Application("System Events").processes.byName("BrushesQuickLook"); p.frontmost = true; delay(0.5); JSON.stringify(p.menuBars[0].menuBarItems.byName("File").menus[0].menuItems().map(i => i.title()))'`.
  It reads `New, Open…, Open Recent, "", Close, Close All, "", Share`. Command-S
  opens no sheet. Click the setup window and then the document window, close
  the document with File > Close, open two more files, then use File > Close
  All. List the menu after each step. It stays the same, because the app
  removes the items again each time SwiftUI rebuilds the menu. A file under
  Open Recent opens again.
- **Too large.** Run `mkfile -n 600m build.noindex/verify/fixtures/too_large.abr`,
  note `ps -o rss= -p $(pgrep -x BrushesQuickLook)`, then run
  `open -a "$A" build.noindex/verify/fixtures/too_large.abr`. The window shows
  "This file is 600 MB. Files above 512 MB are not previewed." and RSS grows by
  a few MB, not 600 MB, because the document reads nothing itself. `bql cleanup`
  deletes the file.
- **Types.** Run the `bql thumb` recipes from [thumbnail.md](./thumbnail.md) and
  the `bql preview` recipes from [preview.md](./preview.md) across `.abr`,
  `.brush` and `.brushset` files. A card with a badge or strip instead of a
  generic icon, and a preview result with `extension.binary`, prove Quick Look
  resolved each type to both extensions.
- **Proof.** The install JSON, the doctor JSON, and the PNGs of the setup
  window, the System Settings sheet and each document window.

## Gotchas

- `bql install --dry-run` changes nothing. Use it to see which stale copies would be unregistered.
- `bql install` replaces the only registered copy on this Mac. Another
  session's verification is lost. Check `bql doctor` first.
- `bql cleanup` quits the app only when `bql install` opened it.
- `bql hostile` opens each file in its own new instance with `open -n` and a
  `-BQLLaunch <token>` argument, and ends only the PID that `pgrep -f` finds
  for that token, so the setup window and other instances stay open, including
  one started during the run.
- `open -a BrushesQuickLook` by name can pick a copy other than the one under
  test. Pass the full path.
- The System Settings window owner name is localized, for example "Ustawienia
  systemowe" in Polish. Match its windows by pid, not by name.
- The SwiftUI buttons expose no title to System Events. Address them by index:
  `button 1` is "Open System Settings", `button 2` is "Open Brush File…".
- A drop on the setup window was driven with posted mouse events from a Finder
  icon. `bql` cannot drop, and a drop on the Dock icon was not proven.
- System Events also lists alternate items. "Close All" is the Option
  alternate of "Close", so it shows in the list without the Option key.
