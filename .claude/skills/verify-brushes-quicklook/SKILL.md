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
On 1 and 2 the JSON has top-level `error` and `fix` fields that say what failed
and what to do. When a run fails for several reasons, both fields list each
one. Per-item fields such as `problem` give the detail. Progress lines go to
stderr.

## Launch

There is no server. Launching means installing this checkout's Release build:

```
bql install --dry-run   # lists the stale registrations and what would be replaced; changes nothing
bql install             # wraps scripts/install.sh: build, check, replace, register (a few minutes)
```

`install` quits the running app and fails when it is still running 10 s later,
for example because a sheet is open. It then replaces `/Applications/BrushesQuickLook.app`,
unregisters every other registered copy, registers the app and both
extensions, and opens the host app window. Registering ends the app's running
extension processes. `install` fails when a live extension process still runs
another binary. The dry run only reads
`lsregister -dump`. It was checked to leave the app's mtime, the pluginkit
registration and the running processes unchanged.

Ready means `bql doctor` exits 0.

Isolation: a Mac has one registered copy. Two checkouts or worktrees cannot
verify different builds at the same time. If `doctor` shows a CDHash mismatch
you did not cause, another session may have installed its build. Ask before
you install over it. To verify without touching the host's copy, or on another
macOS release, use a VM. See [VM](#vm).

## VM

`vm` runs `bql` inside a Tart macOS VM, so a run has its own registration and
its own Finder and leaves the host's copy alone. It needs `tart` on the host.
The guest needs no Xcode.

```
vm setup [--image tahoe|sonoma]   # clone the cirruslabs base image into this checkout's VM, once
vm up                             # boot it headless, wait for the guest agent, grant it Automation for Finder and System Events
vm sync                           # build Release on the host, unregister that build on the host, copy the checkout and the build into the guest
vm run install --no-build         # bql install in the guest, with the host's build
vm run doctor                     # any bql subcommand: vm run <bql args>
vm evidence                       # copy the guest's evidence to build.noindex/verify/vm/<vm>/evidence
vm down                           # stop the VM
```

`vm` keeps `bql`'s contract: one JSON object on stdout and exit codes 0, 1
and 2. `vm run` prints the guest `bql`'s JSON and exits with its code. Paths
in that JSON are guest paths. Pass `--image` before the `bql` arguments, as in
`vm run --image sonoma doctor`. `tahoe` is the default. Use `sonoma` for
macOS 14 checks.

One VM holds one installed build. Quick Look's one-registration rule applies
inside the guest too. Each checkout gets its own VM per image, named
`bql-<checkout folder>-<path hash>-<image>`, so two worktrees verify different
builds at the same time. After every `vm sync`, run `vm run install --no-build` again.
A plain `vm run install` fails in the guest, because it has no `xcodegen`.

Apple allows two running macOS VMs on one Mac, and other work may hold one of
them. When the VM cannot start, `vm up` fails within seconds with Tart's
error and the running VMs. Stop only VMs you started. `vm` never touches a VM
other than its own.

`bql` runs in the guest's logged-in session. The guest agent already has
Screen Recording and Accessibility, and `vm up` grants it Automation for
Finder and System Events, so `vm run preview` and `vm run finder` need no
setup. `BQL_REAL_FILES` is not copied into the guest.
Remove a VM you no longer need with `tart delete <name>`.

The host-app recipes in [`features/host-app.md`](features/host-app.md) run
in the guest on both images. Install, registration and types use `bql`, so
run them with `vm run`. Run window ids, setup window, settings button, open a
file, File > Open, File menu, title and too large with
`tart exec <vm> sh -c '<recipe>'`. Set `A` in that script and use the guest
fixtures under `/Users/admin/brushes-quicklook/build.noindex/verify/fixtures`
from `vm run fixtures`. The recipes run as the guest agent, so their System
Events calls need no prompt. In the sonoma guest, wait 2 s between the Open
panel keystrokes. There the settings button opens Privacy & Security >
Extensions, not the Quick Look sheet, see #143.

## Doctor

Run `bql doctor` first and whenever a result looks wrong. It changes nothing and checks:

- `cdhash-app`, `cdhash-preview`, `cdhash-thumbnail`: the installed bundles
  match `build.noindex/Build/Products/Release` of this checkout.
- `build-fresh` (warn): no tracked source file is newer than that build.
- `pluginkit-preview`, `pluginkit-thumbnail`: exactly one enabled registration,
  at the `/Applications` path.
- `launchservices` (warn): no other copy of the app is registered.
- `running-preview`, `running-thumbnail` (warn): a live extension process runs
  an older binary. `bql install` ends these processes, so the warning means the
  app was replaced without registering it again, for example by another
  checkout or a manual copy. The check reads each process's executable path and
  uses `codesign -v`, because the CDHash of a pid is read from disk. The check
  gives the exact `kill <pid>`.
- `running-app` (warn): the host app at `/Applications` runs a binary that
  was replaced on disk, so `open` sends files to the old code. The check uses
  `codesign -v` like the extension checks and gives the exact `kill <pid>`. A
  copy that runs from another path, such as a Debug build from Xcode, is
  ignored, like in `bql install`. With such a copy running,
  `open -a /Applications/BrushesQuickLook.app <file>` starts the
  `/Applications` copy and the quit in `bql install` leaves the other copy
  running. A copy registered at another path is reported by `launchservices`.

## Drive

```
bql fixtures                        # copy ffi/tests/corpus to build.noindex/verify/fixtures/corpus/<name>.<ext>
bql thumb <file|dir>...             # Finder thumbnail, headless: qlmanage -x -t, sizes 256 and 48 pt by default
bql thumb <file> --size 64 --scale 2
bql preview <file|dir>...           # space-bar preview in a qlmanage window, captured by window id
bql finder <file|dir>...            # the real Finder path: new Finder window, select, space, capture panel, Escape
bql hostile [dir|file...]           # thumbnail, preview and open every file in a new app instance, exit 1 on a crash, a capped crash-report wait, an unexercised file or too many retries
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
PNGs under `thumb/<size>pt@<scale>x/`, `preview/` and, for `hostile`, `app/`,
plus `result.json`, a copy of the stdout JSON. The folder is in
`build.noindex`, which git and Spotlight ignore.

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
  records `attempts: 2`. The proof then uses only the second attempt's time
  window. `hostile` counts those files in `retried` and fails when more than
  `retry_limit` needed a second attempt. The limit is 1 plus 1 per 100 files.
  Under GitHub Actions it appends the verdict and the counts to the job
  summary.
- An app proof in `hostile` is the PNG of the window titled with the file, from
  a new instance launched with a `-BQLLaunch bql-<uuid>` argument. The CLI
  finds that instance by the token, so it never adopts or ends another one. It
  captures the window `--settle` seconds after the instance's `load` signpost
  intervals end. A `log stream` started before the launch records them to
  `app-loads.ndjson`. A load that has not ended 15 s after the window appears,
  an instance that exits before the capture and a window with another title are
  each a problem for that file.
- A thumbnail proof is the PNG. It must show the extension's drawing: the white
  card with the format badge or strip. A generic document icon means Quick
  Look did not use the extension.
- Look at the PNG. `ok: true` means the drive ran, not that the picture is
  right.
- `new_crash_reports` must be empty. Reports are `Brushes*` files in
  `~/Library/Logs/DiagnosticReports`, and `hostile` names the likely file
  for each one. ReportCrash can write a report 25 s after the crash, so
  `thumb`, `preview`, `finder` and `hostile` wait at the end until no new
  report from the run has arrived for 30 s, at most 120 s. When a report
  arrives too late for 30 quiet seconds to fit before 120 s, the result has
  `crash_wait_capped: true` and the command fails, because a report from the
  run can arrive later. The wait runs once per
  command, so pass every file of a check to one command.
- `qlmanage -p` hosts the same extension as Finder, with a `[DEBUG]` window
  title. When the change is about Finder behavior (panel size, the space-bar
  toggle, file switching), prove it with `bql finder`.

## Cleanup

```
bql cleanup
```

Cleanup stops only what `bql` started, as listed in
`build.noindex/verify/state.json`: `qlmanage` PIDs whose command line still
matches, app instance PIDs from `bql hostile` whose command line still has
their launch token, Finder windows by id, and the host app window if
`bql install` opened it.
It then deletes `build.noindex/verify/fixtures`. The evidence folder stays,
and the JSON lists the runs it kept. Never kill Quick Look, Finder or
extension processes by name. The only extension kill is the exact PID that
`doctor` reports as stale.

## Helpers

`bql` and `vm` are the only helpers: Python 3 standard library only, no
dependencies. `bql` calls `qlmanage`, `screencapture`, `osascript`, `codesign`,
`pluginkit`, `lsregister` and `log`. `vm` calls `tart`, `tar`, `git`,
`xcodegen` and `xcodebuild` on the host. `bql <subcommand> --help` and
`vm <subcommand> --help` show every flag.
