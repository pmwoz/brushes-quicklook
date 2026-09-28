---
name: verify-brushes-quicklook
description: Drive Brushes Quick Look on this Mac the way a user does. Renders Finder thumbnails, opens the space-bar preview through qlmanage or Finder, captures PNG evidence and checks for new crash reports. Use it to prove a change to the thumbnail, the preview, the error states or the host app in the installed extensions, or to sweep hostile brush files for crashes.
---

# Verify Brushes Quick Look

The product is two Quick Look extensions inside `BrushesQuickLook.app`. Quick Look
runs only the registered copy of the app, so every drive goes through
`/Applications/BrushesQuickLook.app`, not through the build folder. Unit tests
do not reach the extensions. This skill does.

All commands go through one CLI. Run it from the repo root:

```
.claude/skills/verify-brushes-quicklook/bql --help
```

The examples below call it `bql`. Each subcommand prints one JSON object on
stdout. Exit 0 is ok, 1 is a failed check, 2 means the command could not run.
On 1 and 2 the JSON has `error` and `fix` or per-item `problem` fields that say
what to do. Progress lines go to stderr.

## Launch

There is no server. Launching means installing this checkout's Release build:

```
bql install --dry-run   # lists the stale registrations and what would be replaced; changes nothing
bql install             # wraps scripts/install.sh: build, check, replace, register (a few minutes)
```

`install` quits the running app, replaces `/Applications/BrushesQuickLook.app`,
unregisters every other registered copy, registers the app and both
extensions, and opens the host app window. The dry run only reads
`lsregister -dump`. It was checked to leave the app's mtime, the pluginkit
registration and the running processes unchanged.

Ready means `bql doctor` exits 0.

Isolation: a Mac has one registered copy. Two checkouts or worktrees cannot
verify different builds at the same time. If `doctor` shows a CDHash mismatch
you did not cause, another session may have installed its build. Ask before
you install over it.

## Doctor

Run `bql doctor` first and whenever a result looks wrong. It changes nothing and checks:

- `cdhash-app`, `cdhash-preview`, `cdhash-thumbnail`: the installed bundles
  match `build.noindex/Build/Products/Release` of this checkout.
- `build-fresh` (warn): no tracked source file is newer than that build.
- `pluginkit-preview`, `pluginkit-thumbnail`: exactly one enabled registration,
  at the `/Applications` path.
- `launchservices` (warn): no other copy of the app is registered.
- `running-preview`, `running-thumbnail` (warn): a live extension process runs
  an older binary. Finder keeps its extension processes after an install and
  they keep serving old code. The check gives the exact `kill <pid>`.

## Drive

```
bql fixtures                        # copy ffi/tests/corpus to build.noindex/verify/fixtures/corpus/<name>.<ext>
bql thumb <file|dir>...             # Finder thumbnail, headless: qlmanage -x -t, sizes 256 and 48 pt by default
bql thumb <file> --size 64 --scale 2
bql preview <file|dir>...           # space-bar preview in a qlmanage window, captured by window id
bql finder <file|dir>...            # the real Finder path: new Finder window, select, space, capture panel, Escape
bql hostile [dir|file...]           # thumbnail and preview every file, exit 1 on any new crash report
bql hostile --via finder            # the same sweep through Finder
bql logs [--last SECONDS]           # load intervals and log messages from the extensions (default 300 s)
```

`bql logs` reads the unified log for `pl.esdesign.brushesquicklook`. It lists
each load with its `load`, `read`, `parse` and `tips` interval times in ms
(`null` while an interval has not ended), plus log messages such as timeouts and
the `Glyph <reason>:` line that says why a thumbnail drew a glyph instead of
tips. Loads in the output prove the installed build is one that logs.

- Quick Look routes files by extension. The corpus files have none, so drive
  the copies from `bql fixtures`, never `ffi/tests/corpus` directly.
- Real-world files come only from the `BQL_REAL_FILES` environment variable,
  which names a folder. `bql fixtures` lists them, and `bql hostile` with no
  arguments includes them. Never commit their paths or names.
- `bql preview` needs Screen Recording for the app that runs the shell.
  `bql finder` also needs Accessibility (key presses) and Automation for
  Finder. It takes focus and sends keys. Do not run it while the user is typing.
- `bql finder` refuses to start while a Quick Look panel is open, because the
  space bar would close it. It opens its own Finder window and closes only
  that window by id. It never touches the user's windows.
- `--settle` (default 2 s) is the wait between the window appearing and the
  capture. The extension shows "Loading brushes…" until parsing finishes. Raise
  it for large real-world files. The preview gives up at 10 s.

The feature map in [`features/README.md`](features/README.md) lists every
user-facing behavior, the fixture that shows it and the observable proof.

## Evidence

Each drive writes to `build.noindex/verify/evidence/<YYYYMMDD-HHMMSS>-<command>/`:
PNGs under `thumb/<size>pt@<scale>x/` and `preview/`, plus `result.json`, a
copy of the stdout JSON. The folder is in `build.noindex`, which git and
Spotlight ignore.

Proof standards:

- Run `bql doctor` in the same session and record its CDHashes. A screenshot of
  an old build proves nothing about the change.
- A preview proof is the PNG plus `extension.binary` under
  `/Applications/BrushesQuickLook.app`. The CLI matches it from the
  extension's own `beginning extension request` activity in the file's time
  window. A `log stream` started before the drive records it to
  `preview-requests.ndjson`, because `log show` loses it on a hosted runner. A
  window that opened without that activity is reported as a problem. When
  qlmanage shows no window within 20 s, the CLI starts one new qlmanage and
  notes the retry on stderr. The proof then names the last request in the
  window, which is the one that drew it.
- A thumbnail proof is the PNG. It must show the extension's drawing: the white
  card with the format badge or strip. A generic document icon means Quick
  Look did not use the extension.
- Look at the PNG. `ok: true` means the drive ran, not that the picture is
  right.
- `new_crash_reports` must be empty. Reports are `Brushes*` files in
  `~/Library/Logs/DiagnosticReports`, and `hostile` names the likely file
  for each one.
- `qlmanage -p` hosts the same extension as Finder, with a `[DEBUG]` window
  title. When the change is about Finder behavior (panel size, the space-bar
  toggle, file switching), prove it with `bql finder`.

## Cleanup

```
bql cleanup
```

Cleanup stops only what `bql` started, as listed in
`build.noindex/verify/state.json`: `qlmanage` PIDs whose command line still
matches, Finder windows by id, and the host app window if `bql install`
opened it. It then deletes `build.noindex/verify/fixtures`. The evidence
folder stays, and the JSON lists the runs it kept. Never kill Quick Look,
Finder or extension processes by name. The only extension kill is the exact
PID that `doctor` reports as stale.

## Helpers

`bql` is the only helper: Python 3 standard library only, no dependencies.
It calls `qlmanage`, `screencapture`, `osascript`, `codesign`, `pluginkit`,
`lsregister` and `log`. `bql <subcommand> --help` shows every flag.
