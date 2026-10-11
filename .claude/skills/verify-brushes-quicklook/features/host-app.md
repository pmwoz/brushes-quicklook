# Host app

`BrushesQuickLook.app` carries the two extensions and imports the `.abr`,
`.brush` and `.brushset` types. Opening it shows a setup window that says what
the app does, explains the one setup step and has a button that opens the Quick
Look extensions in System Settings. The app also opens brush files and shows
the same grid, single-brush layout and error view as the space-bar preview.
macOS registers the extensions when the app is opened for the first time.

## Sub-features

- `app-window` shows the app icon, "Brushes Quick Look", one line on what the app does, one line on turning on BrushesPreview and BrushesThumbnail with the System Settings path (General > Login Items & Extensions > Quick Look, or Privacy & Security > Extensions > Quick Look on macOS 14), the buttons "Open System Settings" and "Open Brush File…", and a line about dropping files on the window.
- `app-settings` means "Open System Settings" opens the Quick Look sheet of General > Login Items & Extensions, which lists BrushesPreview and BrushesThumbnail under BrushesQuickLook. On macOS 14 it opens the Privacy & Security > Extensions list, whose Quick Look row reads "BrushesPreview, BrushesThumbnail".
- `app-open` means a brush file opened in the app shows a 760 × 600 window titled with the file name and the preview's content: the grid, the single-brush layout or "This file can’t be previewed".
- `app-open-ways` covers the entry points: File > Open, "Open Brush File…", a drop on the setup window, and Open With in Finder, which `open -a` stands in for. The app is an Alternate handler: it ranks below any app that claims these types and opens them on double-click only when no other app does.
- `app-file-menu` means the File menu has Open, Open Recent, Close, Close All and Share and no New, Save, Save As, Duplicate, Rename, Move To or Revert To, with or without a brush file open.
- `app-title` means a document window's title shows the file name and offers no rename, move, tags or lock: the title bar has no "document actions" button and a click on the title opens nothing.
- `app-registration` means that after install, pluginkit lists exactly one enabled copy of each extension, inside `/Applications`.
- `app-types` means the imported UTTypes route brush files to the extensions, which the thumbnail and preview features confirm.

## How to get to it (user POV)

- Move the app to Applications and open it. The setup window opens.
- Click "Open System Settings", or go to System Settings > General > Login Items & Extensions > Quick Look. On macOS 14 go to System Settings > Privacy & Security > Extensions > Quick Look.
- Choose File > Open or "Open Brush File…", drop brush files on the setup window, or use Open With > BrushesQuickLook in Finder.

## Driving it with bql

Preconditions:

- Baseline preconditions from the index.
- `A=/Applications/BrushesQuickLook.app` is set in the shell.
- File > Open and the button clicks use System Events, and `bql app` reads the app
  through Accessibility. Both need Accessibility for the terminal.

- **Install and open.** Run `bql install`. The JSON lists the steps
  `build, check-build, unregister N stale paths, quit, replace, register, verify` and
  the setup window opens.
- **Registration.** Run `bql doctor`. It exits 0, and `observed.plugins` holds
  one `+` line for each extension, ending in the
  `/Applications/.../PlugIns/*.appex` path.
- **Window ids.** List the app's windows with
  `osascript -l JavaScript -e 'ObjC.import("CoreGraphics"); JSON.stringify(ObjC.deepUnwrap(ObjC.castRefToObject($.CGWindowListCopyWindowInfo($.kCGWindowListOptionOnScreenOnly, $.kCGNullWindowID))).filter(w => w.kCGWindowOwnerName === "BrushesQuickLook" && w.kCGWindowLayer === 0).map(w => [w.kCGWindowNumber, w.kCGWindowName]))'`.
  The setup window is named "Brushes Quick Look". A document window is named after its file.
- **Setup window.** Run `bql app --case launch`. It passes when a new instance
  shows only the "Brushes Quick Look" window, so no Open panel opens beside it.
  The panel appeared only on macOS 14 (#114), so also run
  `vm run --image sonoma app --case launch`. To look at the window, run
  `open "$A"` and capture its id from the list above with
  `screencapture -x -o -l <id> build.noindex/verify/evidence/host-app.png`. The
  window is 520 × 415 pt (520 × 411 on macOS 14), and the PNG shows every line
  and both buttons from `app-window`, with the path for the guest's macOS
  version.
- **Settings button.** Run `osascript -e 'tell application "System Events" to tell process "BrushesQuickLook" to click button 1 of group 1 of window "Brushes Quick Look"'`.
  System Settings shows the Quick Look sheet over Login Items & Extensions, with
  BrushesPreview and BrushesThumbnail under BrushesQuickLook. This works whether
  or not System Settings was already open. Capture it by the window ids of
  `pgrep -x "System Settings"` from the same CoreGraphics list, filtered by
  `kCGWindowOwnerPID`. The sheet is the id with an empty name. On macOS 14 the
  button opens the Privacy & Security > Extensions list instead, with
  "BrushesPreview, BrushesThumbnail" under Quick Look (#143).
- **Open a file.** Run `open -a "$A" $F/zero_area_tip.abr $F/ordered_set.brushset $F/root_brush.brush $F/v2_rle_overflow.abr`.
  Four 760 × 600 windows open, named after the files. `zero_area_tip` reads
  `2 brushes · 1 without preview`, `ordered_set` shows "Ordered" with
  `2 brushes · Procreate brush set`, `root_brush` shows the single-brush layout
  with "A" and `16 × 8 px`, and `v2_rle_overflow` shows "This file can’t be
  previewed", "The file looks damaged or incomplete." and a collapsed "Details".
  `bql app --case files` passes when a launch with two files shows only their
  windows. The setup window opened beside them only on macOS 14 (#115), so
  also run it with `vm run --image sonoma`.
- **File > Open.** Run
  `osascript -e 'tell application "System Events" to tell process "BrushesQuickLook"' -e 'set frontmost to true' -e 'click menu item "Open…" of menu 1 of menu bar item "File" of menu bar 1' -e 'end tell'`,
  then type the path in the panel with Command-Shift-G and press Return twice.
  A window named after the file opens. `click button 2 of group 1 of window "Brushes Quick Look"`
  ("Open Brush File…") opens the same panel. In a macOS 14 VM, wait 2 s
  between the panel keystrokes. With 1 s the panel stayed open.
- **File menu.** Run `bql app --case menu`. It passes when the File menu reads
  `Open…, Open Recent >, -, Close, Close All, -, Share >` right after launch,
  with `ordered_set.brushset` open and after that window closes. The rest is
  manual. List the menu with
  `osascript -l JavaScript -e 'const p = Application("System Events").processes.byName("BrushesQuickLook"); p.frontmost = true; delay(0.5); JSON.stringify(p.menuBars[0].menuBarItems.byName("File").menus[0].menuItems().map(i => i.title()))'`.
  It reads `Open…, Open Recent, "", Close, Close All, "", Share`. Command-S
  opens no sheet. Click the setup window and then the document window, close
  the document with File > Close, open two more files, then use File > Close
  All. List the menu after each step. It stays the same, because the app
  removes the items again each time SwiftUI rebuilds the menu. A file under
  Open Recent opens again.
- **Title.** Run `bql app --case title`. It opens `ordered_set.brushset` and
  passes when the window's title bar has no `document actions` button. AppKit
  adds that button, and the popover with Name, Tags, Where and a lock checkbox
  that a click on the title opens, only when the document class autosaves in
  place (#136). The click is manual. With `ordered_set.brushset` open, run
  `osascript -e 'tell application "System Events" to tell process "BrushesQuickLook"' -e 'set frontmost to true' -e 'perform action "AXRaise" of window "ordered_set.brushset"' -e 'set frontName to name of window 1' -e 'set {x, y} to position of static text 1 of window "ordered_set.brushset"' -e 'set {w, h} to size of static text 1 of window "ordered_set.brushset"' -e 'click at {x + w div 2, y + h div 2}' -e 'delay 1' -e 'return {frontName} & description of every UI element of window "ordered_set.brushset"' -e 'end tell'`.
  `set frontmost to true` raises the app, not a window, so `AXRaise` puts
  `ordered_set.brushset` in front of the app's other windows before the click.
  The output starts with `ordered_set.brushset`, the window in front when the
  click lands, and a `screencapture -x` right after shows no popover under the
  title. The popover is not a child of the window in System Events, so
  `pop overs of window` reads 0 either way.
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
- **Proof.** The install JSON, the doctor JSON, the `bql app` JSON, and the
  PNGs of the setup window, the System Settings sheet and each document window.

## Gotchas

- `bql install` replaces the only registered copy on this Mac. Another
  session's verification is lost. Check `bql doctor` first.
- `bql cleanup` leaves the app that `bql install` opened running.
- `bql hostile` opens each file in its own new instance with `open -n` and a
  `-BQLLaunch <token>` argument, and ends only that instance, so the setup
  window and other instances stay open, including one started during the run.
  `bql app` launches each case the same way with `open -n -F`, so the launch
  restores no saved windows, and quits only that instance through its Quit
  menu item.
- `open -a BrushesQuickLook` by name can pick a copy other than the one under
  test. Pass the full path.
- The System Settings window owner name is localized, for example "Ustawienia
  systemowe" in Polish. Match its windows by pid, not by name.
- The SwiftUI buttons expose no title to System Events. Address them by index:
  `button 1` is "Open System Settings", `button 2` is "Open Brush File…".
- A drop on the setup window was driven with posted mouse events from a Finder
  icon. `bql` cannot drop, and a drop on the Dock icon was not proven.
- Accessibility also lists alternate items. "Close All" is the Option
  alternate of "Close", so the File menu read shows it without the Option key.
