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
bql install             # build, check, replace, register, then the doctor checks (a few minutes)
bql install --main      # the same for origin/main, built in a temporary worktree
bql check-build <app>   # the Release checks that install and CI run; a failure names the bundle, key and file to fix
```

`install` unregisters every other registered copy, then quits the running app
and fails when it is still running 10 s later, for example because a sheet is
open. It then replaces `/Applications/BrushesQuickLook.app`, registers the app
and both extensions, and opens the host app window. Registering ends the app's
running extension processes. Last, `install` runs the checks of `bql doctor`
against the build it installed and fails on any problem, with that problem's
fix. `bql doctor` names every copy that `install` would unregister.

`install --main` fetches `origin/main`, builds it in a temporary detached
worktree and installs that build. It then unregisters the build and removes the
worktree, also after a failed step. When either cleanup command fails, it exits
2 and names the command to finish it. Run it to leave `/Applications` on
`origin/main` after a session.

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
vm up                             # boot it headless, wait for the guest agent, grant it Automation for Finder and System Events, approve its screen captures
vm sync                           # build Release on the host, unregister that build on the host, copy the checkout and the build into the guest
vm run install --no-build         # bql install in the guest, with the host's build
vm run doctor                     # any bql subcommand: vm run <bql args>
vm evidence                       # copy the guest's evidence to build.noindex/verify/vm/<vm>/evidence
vm down                           # stop the VM
```

`vm up` boots the VM under a watcher process that stops it after 30
minutes without use, also when the agent that ran `vm up` has exited.
`vm up`, `vm sync`, `vm run` and `vm evidence` count as use, and `vm sync`
counts during its host build too. So does a `tart exec` into the VM, such as
a host-app recipe, for its first 2 hours, so a guest command that never
returns cannot hold the VM. The watcher checks every 2 seconds, so a `tart
exec` that starts and ends between two checks does not count. The watcher
logs the stop to `build.noindex/verify/vm/<vm>/tart-run.log`. Run `vm down`
when verification ends, so the VM does not hold a VM slot for those 30
minutes. `kill` on the watcher stops the VM too. `kill -9` on the watcher
leaves the VM running without one, and so does `tart run` by hand. `vm up` on
such a VM starts a watcher for it.

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

On the tahoe image (macOS 26), the first capture by an app outside the system
window picker opens an alert in the middle of the screen: "“tart-guest-agent”
is requesting to bypass the system private window picker and directly access
your screen and audio", with the buttons Allow and Open System Settings. It
covers the middle of full-screen captures that follow. `vm up` records a
recent capture for the guest agent in
`~/Library/Group Containers/group.com.apple.replayd/ScreenCaptureApprovals.plist`
before any capture, so the alert does not open. When a capture ran before
`vm up`, for example on a VM booted with `tart run`, the alert can be open.
Run `vm up` with the same `--image` first, because the click below is an
Apple Event and needs the grant that `vm up` writes. Then close the alert:

```
tart exec <vm> osascript -e 'tell application "System Events" to click button "Allow" of window 1 of process "UserNotificationCenter"'
```

An Apple Event sent in the guest before `vm up` wrote the grant, for example
on a VM booted with `tart run`, opens a consent prompt that stays pending for
about 2 minutes. Until it expires, events to that app hang even with the
grant. When it expires, tccd replaces the grant with a deny. So `vm run
finder` or a System Events call can still time out after `vm up`, and `bql`
exits 2 because `osascript` did not return within 60 s. Run `vm down` and
`vm up` with the same `--image`. Restarting tccd or System Events does not
help.

The host-app recipes in [`features/host-app.md`](features/host-app.md) run
in the guest on both images. Run the `bql` ones with `vm run`, and install
with `vm run install --no-build`. Its step list starts at `check-build`.
Every other recipe is a shell command. After `vm run fixtures`, pass it on
stdin, with `<vm>` taken from the `vm` field of `vm up`:

```
tart exec -i <vm> sh -s <<'EOF'
cd /Users/admin/brushes-quicklook
A=/Applications/BrushesQuickLook.app F=build.noindex/verify/fixtures/corpus
<recipe>
EOF
```

`vm up` granted the guest agent Automation, so the System Events calls in
these recipes need no prompt.

## Doctor

Run `bql doctor` first and whenever a result looks wrong. It changes nothing.
It exits 1 on any of these problems, and `error` starts each one with its name:

- `installed`, `release-build`: `/Applications/BrushesQuickLook.app` or
  `build.noindex/Build/Products/Release/BrushesQuickLook.app` is missing.
- `cdhash-app`, `cdhash-preview`, `cdhash-thumbnail`: an installed bundle
  differs from that Release build of this checkout.
- `launchservices`: LaunchServices does not hold exactly one copy of the app,
  at `/Applications`. A copy is any bundle with the app's identifier, whatever
  its name. The error names every other copy.
- `pluginkit-preview`, `pluginkit-thumbnail`: pluginkit does not hold exactly
  one registration, at the `/Applications` path, elected for use (`+`).
- `running-preview`, `running-thumbnail`: a live extension process runs a
  binary other than the installed one: replaced code, a deleted file, an old
  hard link, or another copy of the app, whatever its bundle is called. The
  check uses `codesign -v`, because the CDHash of a pid is read from disk. The
  fix gives the exact `kill <pid>`.
- `running-app`: the host app runs a binary other than the installed one:
  replaced code, a deleted file or an old hard link, so `open` sends files to
  the old code. The check uses `codesign -v` like the extension checks, and the
  fix gives the exact `kill <pid>`. A copy that runs from another bundle on
  disk, such as a Debug build from Xcode, is ignored. With such a copy running,
  `open -a /Applications/BrushesQuickLook.app <file>` starts the
  `/Applications` copy and the quit in `bql install` leaves the other copy
  running. A copy registered at another path is a `launchservices` problem.

`observed` holds what the checks read, including each bundle's CDHash. Its
paths are resolved. A process belongs to the app when the kernel names it
after one of the app's executables or it runs a file in a copy of the app. It
runs the installed app when it runs the same file, so a symlink, a renamed
bundle or a relative launch does not hide it, and the quit in `bql install`
waits for it the same way. A process whose executable was deleted has a null
`path`.
`build_fresh` says whether a tracked source file is newer than the Release
build. It fails nothing. A system command that fails exits 2, so it never
reads as a clean Mac.

## Drive

```
bql fixtures                        # copy ffi/tests/corpus to build.noindex/verify/fixtures/corpus/<name>.<ext>
bql thumb <file|dir>...             # Finder thumbnail, headless: qlmanage -x -t, sizes 256 and 48 pt by default
bql thumb <file> --size 64 --scale 2
bql preview <file|dir>...           # space-bar preview in a qlmanage window, captured by window id
bql finder <file|dir>...            # the real Finder path: new Finder window, select, space, capture panel, Escape
bql hostile [dir|file...]           # thumbnail, preview and open every file in a new app instance, exit 1 on a crash, a capped crash-report wait, an unexercised file or too many retries
bql hostile --via finder            # the same sweep through Finder
bql app [--case NAME]               # launch the installed app in new instances, compare its windows, File menu and title bar with each case
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
- `bql app` runs the cases `launch`, `files`, `menu` and `title`, or the one
  `--case` names, on files from `bql fixtures`. Each case launches a new
  instance with `open -n -F` and a `-BQLLaunch` token, reads it until the
  windows a step waits for show and the read stays the same for 3 s, at most
  20 s, and quits only that instance through its Quit menu item. An instance
  that still runs 10 s later is killed. Before each read, the Close, the Quit
  and the kill, it checks that the pid still has the start time it had at
  launch. If not, the instance exited: a read or the Close exits 2, and the
  Quit and the kill are skipped. Each step in the JSON lists `expected` and
  `observed`. A read with a failed Accessibility call is `{"error": ...}` and
  never passes. It reads through Accessibility and sends no Apple Events, so
  it needs Accessibility for the app that runs the shell and exits 2 without
  it. The `launch` and `files` defects showed only on macOS 14, so also run
  `vm run --image sonoma app`.
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
matches, app instances from `bql app` and `bql hostile` whose PID still has
the start time recorded at launch, and Finder windows by id. An app record
without a start time, from an older `bql`, is listed under
`unverified_app_records` and left alone.
It then deletes `build.noindex/verify/fixtures`. The evidence folder stays,
and the JSON lists the runs it kept. Never kill Quick Look, Finder or
extension processes by name. The only extension kill is the exact PID that
`doctor` reports as stale.

## Helpers

`bql` and `vm` are the only helpers: Python 3 standard library only, no
dependencies. `bql` calls `qlmanage`, `screencapture`, `osascript`, `codesign`,
`lipo`, `nm`, `otool`, `pluginkit`, `lsregister` and `log`. `vm` calls `tart`,
`tar`, `git`, `ps`, `xcodegen` and `xcodebuild` on the host.
`bql <subcommand> --help` and `vm <subcommand> --help` show every flag.
