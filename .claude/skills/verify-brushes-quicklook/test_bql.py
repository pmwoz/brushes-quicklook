import importlib.machinery
import importlib.util
import io
import json
import os
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from contextlib import contextmanager, nullcontext, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

loader = importlib.machinery.SourceFileLoader("bql", str(Path(__file__).with_name("bql")))
bql = importlib.util.module_from_spec(importlib.util.spec_from_loader("bql", loader))
loader.exec_module(bql)


class FakeClock:
    def __init__(self, start, on_tick):
        self.start = self.now = start
        self.on_tick = on_tick

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        if self.now - self.start > bql.CRASH_WAIT_CAP + 30:
            raise AssertionError("the wait ran past its cap")
        if (self.now - self.start) % 10 == 0:
            self.on_tick(self.now)


class WaitForNewCrashesTest(unittest.TestCase):
    START = 1_800_000_000

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.written = []
        for patch in (mock.patch.object(bql, "CRASH_DIR", self.dir), mock.patch.object(bql, "note")):
            patch.start()
            self.addCleanup(patch.stop)

    def write_report(self, capture):
        path = self.dir / f"BrushesPreview-{len(self.written)}.ips"
        stamp = datetime.fromtimestamp(capture, timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f %z")
        path.write_text(json.dumps({"app_name": "BrushesPreview"}) + "\n" + json.dumps({"captureTime": stamp}))
        self.written.append(path)

    def wait(self, on_tick, before=None):
        clock = FakeClock(self.START, on_tick)
        with mock.patch.object(bql, "time", clock):
            before = bql.crash_reports() if before is None else before
            crashes, capped, vanished = bql.wait_for_new_crashes(before, clock.now)
        return clock.now - self.START, capped, crashes, vanished

    def test_reports_from_before_the_run_do_not_restart_the_quiet_window(self):
        self.assertEqual(self.wait(lambda now: self.write_report(self.START - 3600)), (30, False, [], set()))

    def test_reports_present_before_the_wait_are_not_returned(self):
        # A captureTime inside the run passes the time filter, so only the before filter can drop this report.
        self.write_report(self.START + 5)
        (self.dir / "BrushesThumbnail-unreadable.ips").write_text("{}")
        self.assertEqual(self.wait(lambda now: None), (30, False, [], set()))

    def test_a_report_from_the_run_present_when_the_wait_starts_is_returned_and_does_not_restart_the_quiet_window(self):
        before = bql.crash_reports()
        self.write_report(self.START)
        elapsed, capped, crashes, vanished = self.wait(lambda now: None, before=before)
        self.assertEqual((elapsed, capped, vanished), (30, False, set()))
        self.assertEqual([crash["report"] for crash in crashes], [str(self.written[0])])

    def test_deleted_reports_do_not_restart_the_quiet_window(self):
        for _ in range(20):
            self.write_report(self.START - 3600)
        self.assertEqual(self.wait(lambda now: self.written.pop().unlink()), (30, False, [], set()))

    def test_one_report_from_the_run_restarts_the_quiet_window_once(self):
        elapsed, capped, crashes, _ = self.wait(lambda now: self.written or self.write_report(now))
        self.assertEqual((elapsed, capped), (40, False))
        self.assertEqual([crash["report"] for crash in crashes], [str(self.written[0])])

    def test_a_report_with_no_readable_capture_time_is_returned_and_restarts_the_quiet_window_once(self):
        path = self.dir / "BrushesPreview-unreadable.ips"
        elapsed, capped, crashes, _ = self.wait(lambda now: path.exists() or path.write_text("{}"))
        self.assertEqual((elapsed, capped), (40, False))
        self.assertEqual(crashes, [{"report": str(path), "process": "BrushesPreview", "time": None}])

    def test_reports_from_the_run_that_keep_arriving_hit_the_cap(self):
        elapsed, capped, crashes, _ = self.wait(self.write_report)
        self.assertTrue(capped)
        self.assertLessEqual(bql.CRASH_WAIT_CAP, elapsed)
        self.assertEqual({crash["report"] for crash in crashes}, set(map(str, self.written)))

    def test_reports_from_the_run_deleted_during_the_wait_hit_the_cap_with_no_crash(self):
        def write_or_delete(now):
            if self.written and self.written[-1].exists():
                self.written[-1].unlink()
            elif now - self.START < bql.CRASH_WAIT_CAP - 5:
                self.write_report(now)
        _, capped, crashes, vanished = self.wait(write_or_delete)
        self.assertEqual((capped, crashes, vanished), (True, [], set(map(str, self.written))))

    def test_a_report_seen_at_the_wait_start_and_deleted_during_a_capped_wait_is_not_vanished(self):
        self.write_report(self.START + 5)
        early = self.written[0]
        self.assertEqual([crash["report"] for crash in bql.run_crashes({}, self.START)], [str(early)])
        def delete_early_and_write(now):
            early.unlink(missing_ok=True)
            self.write_report(now)
        _, capped, _, vanished = self.wait(delete_early_and_write, before={})
        self.assertEqual((capped, vanished), (True, set()))


class CrashVerdictTest(unittest.TestCase):
    def test_a_capped_wait_adds_one_failure_that_names_vanished_reports_only_when_there_are_any(self):
        crash = {"report": "BrushesThumbnail-1.ips", "process": "BrushesThumbnail", "time": 2e9}
        [crash_failure] = bql.crash_verdict([crash], False, set())[0]

        def capped(crashes, vanished):
            return bql.crash_verdict(crashes, True, vanished)[0]
        [kept], [gone] = capped([], set()), capped([], {"BrushesPreview-1.ips"})
        self.assertIn("kept arriving", kept[0])
        self.assertIn("restarted the crash wait", gone[0])
        self.assertEqual(capped([crash], set()), [crash_failure, kept])
        self.assertEqual(capped([crash], {"BrushesPreview-1.ips"}), [crash_failure, gone])


def run_bql(*argv, **stubs):
    stdout = io.StringIO()
    stubbed = mock.patch.multiple(bql, **stubs) if stubs else nullcontext()
    with mock.patch("sys.argv", ["bql", *map(str, argv)]), stubbed, redirect_stdout(stdout), \
            redirect_stderr(io.StringIO()):
        try:
            bql.main()
        except SystemExit as exit:
            return exit.code, json.loads(stdout.getvalue())
    raise AssertionError("bql returned without exiting")


class ArgumentErrorTest(unittest.TestCase):
    def test_a_subcommand_argument_error_prints_json_naming_its_help(self):
        code, result = run_bql("thumb")
        self.assertEqual((code, result["ok"]), (2, False))
        self.assertIn("files", result["error"])
        self.assertIn("bql thumb --help", result["fix"])

    def test_a_top_level_argument_error_prints_json_naming_its_help(self):
        code, result = run_bql("nope")
        self.assertEqual((code, result["ok"]), (2, False))
        self.assertIn("nope", result["error"])
        self.assertIn("bql --help", result["fix"])

    def test_an_unknown_option_after_a_subcommand_names_the_subcommand_help(self):
        code, result = run_bql("thumb", "x", "--bogus")
        self.assertEqual((code, result["ok"]), (2, False))
        self.assertIn("--bogus", result["error"])
        self.assertIn("bql thumb --help", result["fix"])


def thumbnails(png=True):
    return lambda file, size, scale, out: {"file": str(file), "size_pt": size, "scale": scale,
                                           **({"png": "x.png"} if png else {"png": None, "qlmanage": "no thumbnail"})}


def previews(problem=None, attempts=1):
    return lambda files, run_dir, settle, via: [{"file": str(f), "png": None if problem else "x.png",
                                                 "problem": problem, "attempts": attempts, "extension": None}
                                                for f in files]


def app_windows(problem=None):
    return lambda file, run_dir, settle: {"file": str(file), "png": None if problem else "x.png", "pid": 200,
                                      "problem": problem}


def crash_wait(crashed=False, capped=False, vanished=()):
    crash = {"report": "BrushesThumbnail-1.ips", "process": "BrushesThumbnail", "time": 2e9}
    return lambda before, since: ([dict(crash)] if crashed else [], capped, set(vanished))


class ExitContractTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.brush = self.dir / "a.abr"
        self.brush.write_bytes(b"")
        self.stubs = {"new_run": lambda name: Path(tempfile.mkdtemp(dir=self.dir)), "crash_reports": dict,
                      "note": lambda message: None}
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("GITHUB_STEP_SUMMARY", None)

    def doctor(self, installed=True, built=True, mismatched=None, unregistered=None, other_copy=False, previews=None,
               apps=None):
        """previews and apps map a BrushesPreview or BrushesQuickLook pid to (root, codesign -v error or None, alive).
        root is "app", "build", "other" or None for a process that exited."""
        executables = {"BrushesPreview": "Contents/PlugIns/BrushesPreview.appex/Contents/MacOS/BrushesPreview",
                       "BrushesQuickLook": "Contents/MacOS/BrushesQuickLook"}
        processes = {"BrushesPreview": previews or {}, "BrushesQuickLook": apps or {}}
        owner = {pid: name for name, pids in processes.items() for pid in pids}
        states = {pid: state for pids in processes.values() for pid, state in pids.items()}
        base = Path(tempfile.mkdtemp(dir=self.dir))
        app, build = base / "installed/BrushesQuickLook.app", base / "build/BrushesQuickLook.app"
        for bundle, exists in ((app, installed), (build, built)):
            if exists:
                (bundle / "Contents/MacOS").mkdir(parents=True)
                (bundle / "Contents/MacOS/BrushesQuickLook").write_bytes(b"")
        (base / "project.yml").write_text("")
        os.utime(base / "project.yml", (0, 0))
        hashes = {str(path): f"{kind} cdhash" for bundle in (app, build) for kind, path in bql.bundles(bundle).items()}
        if mismatched:
            hashes[str(bql.bundles(app)[mismatched])] = "older cdhash"

        def run(args, timeout=120, check=False):
            if args[0] == "pluginkit":
                kind = args[-1].rsplit(".", 1)[1]
                line = f"+    {args[-1]}(1.0)\t{bql.bundles(app)[kind]}\n"
                return SimpleNamespace(stdout="" if kind == unregistered else line)
            if args[0] == "git":
                return SimpleNamespace(stdout="project.yml\n")
            if args[0] == "pgrep":
                return SimpleNamespace(stdout="\n".join(processes.get(args[-1], {})))
            if args[0] == "ps":
                root = {"app": app, "build": build, "other": base / "Other.app"}.get(states[args[-1]][0])
                return SimpleNamespace(stdout=f"{root}/{executables[owner[args[-1]]]}\n" if root else "")
            if args[0] == "codesign":
                error = states[args[-1]][1]
                return SimpleNamespace(returncode=1 if error else 0, stderr=f"{error}\n" if error else "")
            if args[0] == "kill":
                return SimpleNamespace(returncode=0 if states[args[-1]][2] else 1)
            if args[0] == bql.LSREGISTER:
                copies = [app, base / "Other/BrushesQuickLook.app"] if other_copy else [app]
                return SimpleNamespace(stdout="".join(f"    path:    {copy} (0x1)\n" for copy in copies))
            return SimpleNamespace(stdout="")
        return {"REPO": base, "APP": app, "BUILD": build, "run": run, "cdhash": lambda path: hashes[str(path)]}

    def test_every_failed_check_exits_1_with_error_and_fix(self):
        brush, settle = str(self.brush), ("--settle", "0")
        crashed, capped, quiet = crash_wait(crashed=True), crash_wait(capped=True), crash_wait()
        rows = [
            (("thumb", brush), "crash reports from this run: 1",
             {"wait_for_new_crashes": crashed, "render_thumbnail": thumbnails()}),
            (("thumb", brush), "wrote no thumbnail for 2 of 2",
             {"wait_for_new_crashes": quiet, "render_thumbnail": thumbnails(png=False)}),
            (("thumb", brush), "Reports kept arriving",
             {"wait_for_new_crashes": capped, "render_thumbnail": thumbnails()}),
            (("thumb", brush), "restarted the crash wait",
             {"wait_for_new_crashes": crash_wait(capped=True, vanished=["BrushesPreview-1.ips"]),
              "render_thumbnail": thumbnails()}),
        ]
        for command in ("preview", "finder"):
            rows += [
                ((command, brush, *settle), "crash reports from this run: 1",
                 {"wait_for_new_crashes": crashed, "drive_previews": previews()}),
                ((command, brush, *settle), "Reports kept arriving",
                 {"wait_for_new_crashes": capped, "drive_previews": previews()}),
                ((command, brush, *settle), "1 of 1 previews have a problem",
                 {"wait_for_new_crashes": quiet, "drive_previews": previews("no window")}),
            ]
        hostile = ("hostile", brush, brush, *settle)
        drives = {"render_thumbnail": thumbnails(), "drive_previews": previews(), "open_in_app": app_windows()}
        rows += [
            (hostile, "crash reports from this run: 1", {**drives, "wait_for_new_crashes": crashed}),
            (hostile, "Reports kept arriving", {**drives, "wait_for_new_crashes": capped}),
            (hostile, "2 of 2 files were not exercised",
             {**drives, "wait_for_new_crashes": quiet, "render_thumbnail": thumbnails(png=False)}),
            (hostile, "2 of 2 files were not exercised",
             {**drives, "wait_for_new_crashes": quiet, "drive_previews": previews("no window")}),
            (hostile, "2 of 2 files were not exercised",
             {**drives, "wait_for_new_crashes": quiet, "open_in_app": app_windows("no window")}),
            (hostile, "above the limit of 1",
             {**drives, "wait_for_new_crashes": quiet, "drive_previews": previews(attempts=2)}),
            (("doctor",), "installed failed", self.doctor(installed=False)),
            (("doctor",), "release-build failed", self.doctor(built=False)),
        ]
        rows += [(("doctor",), f"cdhash-{kind} failed", self.doctor(mismatched=kind))
                 for kind in ("app", "preview", "thumbnail")]
        rows += [(("doctor",), f"pluginkit-{kind} failed", self.doctor(unregistered=kind)) for kind in bql.PLUGINS]
        fragments = {error for _, error, _ in rows}
        for argv, error, stubs in rows:
            with self.subTest(command=argv[0], error=error):
                code, result = run_bql(*argv, **self.stubs, **stubs)
                self.assertEqual((code, result["ok"], bool(result.get("fix"))), (1, False, True))
                self.assertEqual({f for f in fragments if f in result.get("error", "")}, {error})

    def test_a_run_with_several_causes_lists_each_error_and_fix(self):
        code, result = run_bql("thumb", self.brush, **self.stubs, wait_for_new_crashes=crash_wait(crashed=True),
                               render_thumbnail=thumbnails(png=False))
        self.assertEqual((code, result["ok"]), (1, False))
        self.assertIn("crash reports from this run: 1", result["error"])
        self.assertIn("wrote no thumbnail for 2 of 2", result["error"])
        self.assertIn("find the crashing frame", result["fix"])
        self.assertIn("Read the `qlmanage` field", result["fix"])

    def test_a_clean_run_exits_0_with_neither_error_nor_fix(self):
        brush, settle = str(self.brush), ("--settle", "0")
        for argv, stubs in [
            (("thumb", brush), {"wait_for_new_crashes": crash_wait(), "render_thumbnail": thumbnails()}),
            (("preview", brush, *settle), {"wait_for_new_crashes": crash_wait(), "drive_previews": previews()}),
            (("finder", brush, *settle), {"wait_for_new_crashes": crash_wait(), "drive_previews": previews()}),
            (("hostile", brush, brush, *settle),
             {"wait_for_new_crashes": crash_wait(), "render_thumbnail": thumbnails(), "drive_previews": previews(),
              "open_in_app": app_windows()}),
        ]:
            with self.subTest(command=argv[0]):
                code, result = run_bql(*argv, **self.stubs, **stubs)
                self.assertEqual((code, result["ok"], "error" in result, "fix" in result), (0, True, False, False))

    def test_a_doctor_run_with_no_failed_check_exits_0(self):
        for other_copy, not_ok in ((False, {}), (True, {"launchservices": "warn"})):
            with self.subTest(other_copy=other_copy):
                code, result = run_bql("doctor", **self.doctor(other_copy=other_copy))
                self.assertEqual((code, result["ok"], "error" in result, "fix" in result), (0, True, False, False))
                self.assertEqual({c["check"]: c["status"] for c in result["checks"] if c["status"] != "ok"}, not_ok)

    def test_doctor_warns_on_a_live_extension_process_not_running_the_installed_code(self):
        replaced = "102: the code on disk does not match what is running"
        previews = {"101": ("app", None, True), "102": ("app", replaced, True), "103": ("build", None, True),
                    "104": ("other", None, True), "105": (None, None, False),
                    "106": ("app", "106: No such process", False)}
        code, result = run_bql("doctor", **self.doctor(previews=previews))
        running = {c["detail"]["pid"]: (c["status"], c["detail"]["verify"])
                   for c in result["checks"] if c["check"] == "running-preview"}
        self.assertEqual((code, running), (0, {101: ("ok", None), 102: ("warn", replaced), 103: ("warn", None),
                                               106: ("ok", None)}))

    def test_doctor_warns_on_the_installed_host_app_running_replaced_code_and_ignores_other_copies(self):
        replaced = "202: the code on disk does not match what is running"
        apps = {"201": ("app", None, True), "202": ("app", replaced, True), "203": ("build", None, True)}
        code, result = run_bql("doctor", **self.doctor(apps=apps))
        running = {c["detail"]["pid"]: (c["status"], c.get("fix")) for c in result["checks"]
                   if c["check"] == "running-app"}
        self.assertEqual((code, {pid: status for pid, (status, _) in running.items()}),
                         (0, {201: "ok", 202: "warn"}))
        self.assertIn("kill 202", running[202][1])

    def test_a_missing_file_exits_2_with_error_and_fix(self):
        code, result = run_bql("thumb", self.dir / "missing.abr")
        self.assertEqual((code, result["ok"], bool(result.get("fix"))), (2, False, True))
        self.assertIn("does not exist", result["error"])

    def test_an_unexpected_exception_exits_2_with_error_and_fix(self):
        code, result = run_bql("thumb", self.brush, new_run=mock.Mock(side_effect=TimeoutError("hung")))
        self.assertEqual((code, result["ok"], bool(result.get("error")), bool(result.get("fix"))),
                         (2, False, True, True))


class OpenInAppTest(unittest.TestCase):
    START = 1_800_000_000

    def open(self, dies=False, load=("begin", "end")):
        """Pid 100 is an instance that ran before. `open` starts 200, the new instance, and 300, an instance of the
        same app that someone else starts during the call. Only 200 has the token, and 300 starts a load too."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        running, signals, launched, now = {100}, [], {}, [self.START]

        @contextmanager
        def log_stream(log, *args):
            launched["log"] = log
            yield lambda: None

        def run(args, timeout=120, check=False):
            if args[0] == "open":
                launched["token"] = args[-1]
                running.update({200, 300})
                events = [(300, "begin"), *((200, kind) for kind in load)]
                launched["log"].write_text("".join(
                    json.dumps({"processID": pid, "signpostName": "load", "signpostType": kind}) + "\n"
                    for pid, kind in events))
            if args[0] == "pgrep":
                return SimpleNamespace(stdout="200\n" if args[-1] == launched.get("token") and 200 in running else "")
            return SimpleNamespace(returncode=0, stderr="")

        def sleep(seconds):
            now[0] += seconds
            if dies:
                running.discard(200)

        def kill(pid, signal):
            if signal:
                signals.append((pid, signal))
            if pid not in running:
                raise ProcessLookupError(pid)
            if signal:
                running.discard(pid)

        def windows():
            return [w for w in [{"id": 1, "pid": 100, "layer": 0, "name": "Brushes Quick Look"},
                                {"id": 7, "pid": 200, "layer": 0, "name": "a"}] if w["pid"] in running]

        def vanished(window_id, png):
            raise bql.Fail("screencapture failed: could not create image from window", "")

        capture = mock.Mock(side_effect=lambda window_id, png: 200 in running or vanished(window_id, png))
        clock = SimpleNamespace(time=lambda: now[0], sleep=sleep)
        with mock.patch.multiple(bql, run=run, windows=windows, capture=capture, log_stream=log_stream, time=clock,
                                 WORK=Path(tmp.name), STATE=Path(tmp.name) / "state.json"), \
                mock.patch.object(bql.os, "kill", kill):
            result = bql.open_in_app(Path(tmp.name) / "a.abr", Path(tmp.name), 2)
            state = bql.load_state()
        return result, signals, running, state["app"], now[0] - self.START

    def test_it_ends_only_the_instance_it_started_and_reports_one_that_died_while_showing_the_file(self):
        for dies, problem in ((False, None), (True, "the app exited while it showed the file")):
            with self.subTest(dies=dies):
                result, signals, running, tracked, _ = self.open(dies)
                self.assertEqual((result["pid"], result["problem"], bool(result["png"])), (200, problem, not dies))
                self.assertEqual((signals, running, tracked), ([(200, 15)], {100, 300}, []))

    def test_a_load_that_never_ends_is_a_problem_after_15_s(self):
        result, signals, _, _, elapsed = self.open(load=("begin", "begin", "end"))
        self.assertEqual((result["problem"], result["png"], elapsed, signals),
                         ("the app did not finish loading the file within 15 s", None, 15, [(200, 15)]))


class CleanupTest(unittest.TestCase):
    def test_it_ends_a_tracked_app_instance_only_while_its_pid_still_has_the_token(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        work = Path(tmp.name)
        mine = {"pid": 200, "file": "a.abr", "token": "bql-a"}
        reused = {"pid": 300, "file": "b.abr", "token": "bql-b"}
        (work / "state.json").write_text(json.dumps({"app": [mine, reused]}))
        executable = bql.APP / "Contents/MacOS/BrushesQuickLook"
        commands = {"200": f"{executable} -ApplePersistenceIgnoreState YES -BQLLaunch bql-a\n",
                    "300": f"{executable} -ApplePersistenceIgnoreState YES -BQLLaunch bql-c\n"}
        signals = []
        with mock.patch.object(bql.os, "kill", lambda pid, signal: signals.append((pid, signal))):
            code, result = run_bql("cleanup", run=lambda args, **kwargs: SimpleNamespace(stdout=commands[args[-1]]),
                                   WORK=work, STATE=work / "state.json", FIXTURES=work / "fixtures",
                                   EVIDENCE=work / "evidence")
        self.assertEqual((code, signals, result["ended_app_instances"]), (0, [(200, 15)], [mine]))


class HungOsascriptTest(unittest.TestCase):
    @staticmethod
    def hang(args, timeout=120, **kwargs):
        raise bql.subprocess.TimeoutExpired(args, timeout)

    def test_a_hung_apple_event_exits_2_naming_its_app_the_automation_pane_and_the_vm_recovery(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        work = Path(tmp.name)
        (work / "state.json").write_text(json.dumps({"finder_windows": [7]}))
        code, result = run_bql("cleanup", run=self.hang, WORK=work, STATE=work / "state.json",
                               FIXTURES=work / "fixtures", EVIDENCE=work / "evidence")
        self.assertEqual((code, result["ok"]), (2, False))
        self.assertIn("Automation prompt", result["error"])
        for recovery in ("control Finder in System Settings > Privacy & Security > Automation", "`vm down`", "`vm up`"):
            self.assertIn(recovery, result["fix"])

    def test_a_hung_script_that_sends_no_apple_event_stays_an_unexpected_error(self):
        with mock.patch.object(bql, "run", self.hang), self.assertRaises(bql.subprocess.TimeoutExpired):
            bql.osascript(bql.WINDOWS_JS, language="JavaScript")


TYPE, REASONS = "NSPrivacyAccessedAPIType", "NSPrivacyAccessedAPITypeReasons"
FILE_TIMESTAMP = {TYPE: "NSPrivacyAccessedAPICategoryFileTimestamp", REASONS: ["C617.1"]}
USER_DEFAULTS = {TYPE: "NSPrivacyAccessedAPICategoryUserDefaults", REASONS: ["CA92.1"]}
BRUSH_TYPES = ["pl.esdesign.brushesquicklook.abr", "pl.esdesign.brushesquicklook.brush",
               "pl.esdesign.brushesquicklook.brushset"]


def manifest(*entries):
    return plistlib.dumps({"NSPrivacyTracking": False, "NSPrivacyAccessedAPITypes": list(entries)})


def user_defaults(changes):
    return {key: value for key, value in {**USER_DEFAULTS, **changes}.items() if value is not None}


class PrivacyManifestTest(unittest.TestCase):
    def test_each_defect_is_reported_at_its_key_and_nowhere_else(self):
        entries = "NSPrivacyAccessedAPITypes"
        keyboards = {TYPE: "NSPrivacyAccessedAPICategoryActiveKeyboards", REASONS: ["3EC4.1"]}
        rows = [
            ("M0 the shipped manifest", manifest(FILE_TIMESTAMP, USER_DEFAULTS), []),
            ("an ActiveKeyboards entry, which no symbol needs", manifest(FILE_TIMESTAMP, USER_DEFAULTS, keyboards), []),
            ("not a property list", b"<plist><dict>", [""]),
            ("no entries array", plistlib.dumps({"NSPrivacyTracking": False}), [entries]),
            ("M1 an entry without a category", manifest(FILE_TIMESTAMP, user_defaults({TYPE: None})),
             [f"{entries}[1].{TYPE}", entries]),
            ("M1b the last entry without a category", manifest(FILE_TIMESTAMP, USER_DEFAULTS, {REASONS: ["85F4.1"]}),
             [f"{entries}[2].{TYPE}"]),
            ("M2 an entry that is not a dictionary",
             manifest(FILE_TIMESTAMP, USER_DEFAULTS, "NSPrivacyAccessedAPICategoryDiskSpace"), [f"{entries}[2]"]),
            ("M3 an unknown category",
             manifest(FILE_TIMESTAMP, USER_DEFAULTS, user_defaults({TYPE: "NSPrivacyAccessedAPICategoryBogus"})),
             [f"{entries}[2].{TYPE}"]),
            ("M4 a category with a trailing newline",
             manifest(FILE_TIMESTAMP, user_defaults({TYPE: "NSPrivacyAccessedAPICategoryUserDefaults\n"})),
             [f"{entries}[1].{TYPE}", entries]),
            ("M5 no entry for a category the binary uses", manifest(FILE_TIMESTAMP), [entries]),
            ("M6 an entry without reasons", manifest(FILE_TIMESTAMP, user_defaults({REASONS: None})),
             [f"{entries}[1].{REASONS}"]),
            ("V1 an empty reason array", manifest(FILE_TIMESTAMP, user_defaults({REASONS: []})),
             [f"{entries}[1].{REASONS}"]),
            ("V2 an empty reason", manifest(FILE_TIMESTAMP, user_defaults({REASONS: [""]})),
             [f"{entries}[1].{REASONS}[0]"]),
            ("V3 a reason that is not a code", manifest(FILE_TIMESTAMP, user_defaults({REASONS: ["because"]})),
             [f"{entries}[1].{REASONS}[0]"]),
            ("V4 a reason code with a trailing newline",
             manifest(FILE_TIMESTAMP, user_defaults({REASONS: ["CA92.1\n"]})), [f"{entries}[1].{REASONS}[0]"]),
        ]
        for name, data, keys in rows:
            with self.subTest(name):
                problems = bql.privacy_problems(data, {"_fstat", "_OBJC_CLASS_$_NSUserDefaults", "dealloc"})
                self.assertEqual([key for key, _ in problems], keys)

    def test_a_required_reason_api_needs_any_one_of_its_categories(self):
        disk_space = {TYPE: "NSPrivacyAccessedAPICategoryDiskSpace", REASONS: ["85F4.1"]}
        self.assertEqual(bql.privacy_problems(manifest(disk_space), {"_getattrlist"}), [])
        self.assertEqual(bql.privacy_problems(manifest(), {"_getattrlist"}), [(
            "NSPrivacyAccessedAPITypes", "the binary uses _getattrlist, which needs "
            "NSPrivacyAccessedAPICategoryFileTimestamp or NSPrivacyAccessedAPICategoryDiskSpace")])


def write_manifests(app, data):
    for bundle in bql.bundles(app).values():
        (bundle / "Contents/Resources/PrivacyInfo.xcprivacy").write_bytes(data)


def set_info(bundle, **changes):
    info = bundle / "Contents/Info.plist"
    info.write_bytes(plistlib.dumps({**plistlib.loads(info.read_bytes()), **changes}))


def set_brush_types(app, app_types, extension_types):
    set_info(app, UTImportedTypeDeclarations=app_types)
    for kind in bql.PLUGINS:
        set_info(bql.bundles(app)[kind],
                 NSExtension={"NSExtensionAttributes": {"QLSupportedContentTypes": extension_types}})


def add_unknown_tag(app, path):
    for bundle in bql.bundles(app).values():
        plist = bundle / path
        plist.write_bytes(plist.read_bytes().replace(b"</dict>\n</plist>", b"<bogus/>\n</dict>\n</plist>"))


def entitlements(sandbox, tag=""):
    return plistlib.dumps({"com.apple.security.app-sandbox": sandbox}).decode().replace("</dict>", f"{tag}</dict>")


class CheckBuildTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def shippable_build(self):
        app = Path(tempfile.mkdtemp(dir=self.dir)) / "BrushesQuickLook.app"
        extension = {"NSExtension": {"NSExtensionAttributes": {"QLSupportedContentTypes": BRUSH_TYPES}}}
        infos = {"app": {"CFBundleIconName": "AppIcon", "ITSAppUsesNonExemptEncryption": False,
                         "LSApplicationCategoryType": "public.app-category.graphics-design",
                         "UTImportedTypeDeclarations": [{"UTTypeIdentifier": t} for t in BRUSH_TYPES]},
                 "preview": extension, "thumbnail": extension}
        for kind, bundle in bql.bundles(app).items():
            (bundle / "Contents/MacOS").mkdir(parents=True)
            (bundle / "Contents/Resources").mkdir()
            (bundle / "Contents/MacOS" / bundle.stem).write_bytes(b"")
            (bundle / "Contents/Info.plist").write_bytes(plistlib.dumps(infos[kind]))
        (app / "Contents/Resources/AppIcon.icns").write_bytes(b"")
        write_manifests(app, manifest(FILE_TIMESTAMP, USER_DEFAULTS))
        tool_output = {kind: {"archs": "x86_64 arm64", "flags": "0x10002(adhoc,runtime)",
                              "entitlements": entitlements(True), "symbols": ["_fstat"], "selectors": ["dealloc"],
                              "exit": {}} for kind in infos}
        tool_output["app"]["symbols"].append("_OBJC_CLASS_$_NSUserDefaults")
        return app, tool_output

    @staticmethod
    def tools(app, tool_output):
        plutil = subprocess.run

        def run(args, **kwargs):
            if args[0] == "plutil":
                return plutil(args, **kwargs)
            path = Path(args[-1])
            kind = next(kind for kind, bundle in bql.bundles(app).items()
                        if path in (bundle, bundle / "Contents/MacOS" / bundle.stem))
            reported = tool_output[kind]
            tool = " ".join(args[:2]) if args[0] == "codesign" else args[0]
            stdout = stderr = ""
            if tool == "lipo":
                stdout = reported["archs"] + "\n"
            elif tool == "codesign -dv":
                stderr = (f"Executable={path}\nCodeDirectory v=20500 size=3709 flags={reported['flags']} "
                          "hashes=105+7 location=embedded\n")
            elif tool == "codesign -d":
                stdout = reported["entitlements"]
            elif tool == "nm":
                stdout = "".join(f"{path} (for architecture {arch}):\n"
                                 + "".join(f"{symbol}\n" for symbol in reported["symbols"])
                                 for arch in ("x86_64", "arm64"))
            else:
                stdout = (f"{path} (architecture arm64):\nContents of (__TEXT,__objc_methname) section\n"
                          + "".join(f"00000001000ed0a2  {selector}\n" for selector in reported["selectors"]))
            return subprocess.CompletedProcess(args, reported["exit"].get(tool, 0), stdout, stderr)
        return run

    def test_each_defect_is_reported_at_its_bundle_and_key_with_the_file_to_fix(self):
        reasons = "PrivacyInfo.xcprivacy NSPrivacyAccessedAPITypes[1].NSPrivacyAccessedAPITypeReasons[0]"
        names = ("BrushesQuickLook.app", "BrushesPreview.appex", "BrushesThumbnail.appex")
        brush_types = ["BrushesQuickLook.app Info.plist UTImportedTypeDeclarations",
                       "BrushesPreview.appex Info.plist NSExtension.NSExtensionAttributes.QLSupportedContentTypes",
                       "BrushesThumbnail.appex Info.plist NSExtension.NSExtensionAttributes.QLSupportedContentTypes"]
        joined, keyed = " ".join(BRUSH_TYPES), dict.fromkeys(BRUSH_TYPES, True)
        rows = [
            ("a shippable build", lambda app, tool_output: None, [], ""),
            ("a single architecture", lambda app, tool_output: tool_output["preview"].update(archs="arm64"),
             ["BrushesPreview.appex Contents/MacOS/BrushesPreview"], "scripts/build.sh"),
            ("no hardened runtime", lambda app, tool_output: tool_output["thumbnail"].update(flags="0x2(adhoc)"),
             ["BrushesThumbnail.appex code signature"], "project.yml"),
            ("no sandbox", lambda app, tool_output: tool_output["app"].update(entitlements=entitlements(False)),
             ["BrushesQuickLook.app entitlements com.apple.security.app-sandbox"], "project.yml"),
            ("an entitlement tag that plutil rejects", lambda app, tool_output: [
                output.update(entitlements=entitlements(True, "<bogus/>")) for output in tool_output.values()],
             [f"{name} entitlements" for name in names], "project.yml"),
            ("an app without a brush type", lambda app, tool_output: set_info(
                app, UTImportedTypeDeclarations=[{"UTTypeIdentifier": t} for t in BRUSH_TYPES[1:]]),
             ["BrushesQuickLook.app Info.plist UTImportedTypeDeclarations"], "project.yml"),
            ("an extension without a brush type", lambda app, tool_output: set_info(
                bql.bundles(app)["thumbnail"],
                NSExtension={"NSExtensionAttributes": {"QLSupportedContentTypes": BRUSH_TYPES[:2]}}),
             ["BrushesThumbnail.appex Info.plist NSExtension.NSExtensionAttributes.QLSupportedContentTypes"],
             "project.yml"),
            ("brush types in one string", lambda app, tool_output: set_brush_types(app, joined, joined),
             brush_types, "project.yml"),
            ("brush types as dictionary keys", lambda app, tool_output: set_brush_types(app, keyed, keyed),
             brush_types, "project.yml"),
            ("brush type arrays with items of the wrong type",
             lambda app, tool_output: set_brush_types(app, BRUSH_TYPES, [*BRUSH_TYPES, 1]), brush_types, "project.yml"),
            ("an Info.plist tag that plutil rejects",
             lambda app, tool_output: add_unknown_tag(app, "Contents/Info.plist"),
             [f"{name} Info.plist" for name in names], "project.yml"),
            ("another icon name", lambda app, tool_output: set_info(app, CFBundleIconName="Icon"),
             ["BrushesQuickLook.app Info.plist CFBundleIconName"], "App/Assets.xcassets"),
            ("no icon file", lambda app, tool_output: (app / "Contents/Resources/AppIcon.icns").unlink(),
             ["BrushesQuickLook.app Contents/Resources/AppIcon.icns"], "App/Assets.xcassets"),
            ("another category",
             lambda app, tool_output: set_info(app, LSApplicationCategoryType="public.app-category.games"),
             ["BrushesQuickLook.app Info.plist LSApplicationCategoryType"], "project.yml"),
            ("an encryption flag of integer 0", lambda app, tool_output: set_info(app, ITSAppUsesNonExemptEncryption=0),
             ["BrushesQuickLook.app Info.plist ITSAppUsesNonExemptEncryption"], "project.yml"),
            ("an extension not embedded", lambda app, tool_output: shutil.rmtree(bql.bundles(app)["preview"]),
             ["BrushesPreview.appex Contents/MacOS/BrushesPreview"], "project.yml"),
            ("V5 no privacy manifest",
             lambda app, tool_output: [(bundle / "Contents/Resources/PrivacyInfo.xcprivacy").unlink()
                                 for bundle in bql.bundles(app).values()],
             [f"{name} PrivacyInfo.xcprivacy" for name in names], "buildPhase: resources"),
            ("a manifest tag that plutil rejects",
             lambda app, tool_output: add_unknown_tag(app, "Contents/Resources/PrivacyInfo.xcprivacy"),
             [f"{name} PrivacyInfo.xcprivacy" for name in names], "PrivacyInfo.xcprivacy"),
            ("V2 an empty reason",
             lambda app, tool_output: write_manifests(app, manifest(FILE_TIMESTAMP, user_defaults({REASONS: [""]}))),
             [f"{name} {reasons}" for name in names], "PrivacyInfo.xcprivacy"),
            ("M5 no UserDefaults entry, which only the app needs",
             lambda app, tool_output: write_manifests(app, manifest(FILE_TIMESTAMP)),
             ["BrushesQuickLook.app PrivacyInfo.xcprivacy NSPrivacyAccessedAPITypes"], "PrivacyInfo.xcprivacy"),
            ("an extension selector that needs SystemBootTime",
             lambda app, tool_output: tool_output["preview"]["selectors"].append("systemUptime"),
             ["BrushesPreview.appex PrivacyInfo.xcprivacy NSPrivacyAccessedAPITypes"], "PrivacyInfo.xcprivacy"),
        ]
        for name, mutate, wheres, fix_file in rows:
            with self.subTest(name):
                app, tool_output = self.shippable_build()
                mutate(app, tool_output)
                with mock.patch.object(subprocess, "run", self.tools(app, tool_output)):
                    problems = bql.check_build(app)
                self.assertEqual([where for where, _, _ in problems], wheres)
                self.assertEqual([fix_file in fix for _, _, fix in problems], [True] * len(wheres))

    def test_the_cli_exits_0_on_a_shippable_build_1_naming_each_defect_and_2_without_an_app(self):
        app, tool_output = self.shippable_build()
        with mock.patch.object(subprocess, "run", self.tools(app, tool_output)):
            code, result = run_bql("check-build", app)
            self.assertEqual((code, result["ok"], "error" in result, "fix" in result), (0, True, False, False))
            write_manifests(app, manifest(FILE_TIMESTAMP, user_defaults({REASONS: ["CA92.1\n"]})))
            code, result = run_bql("check-build", app)
            self.assertEqual((code, result["ok"]), (1, False))
            self.assertIn("BrushesThumbnail.appex PrivacyInfo.xcprivacy NSPrivacyAccessedAPITypes[1]."
                          "NSPrivacyAccessedAPITypeReasons[0]: 'CA92.1\\n' is not a reason code", result["error"])
            self.assertIn("Edit PrivacyInfo.xcprivacy at the repository root.", result["fix"])
            tool_output["thumbnail"].update(entitlements=entitlements(True, "<bogus/>"))
            code, result = run_bql("check-build", app)
            self.assertEqual((code, result["ok"]), (1, False))
            self.assertIn("BrushesThumbnail.appex entitlements: is not a valid property list "
                          "(Encountered unknown tag bogus on line ", result["error"])
            add_unknown_tag(app, "Contents/Resources/PrivacyInfo.xcprivacy")
            code, result = run_bql("check-build", app)
        self.assertEqual((code, result["ok"]), (1, False))
        self.assertIn("BrushesPreview.appex PrivacyInfo.xcprivacy: is not a valid property list "
                      "(Encountered unknown tag bogus on line ", result["error"])
        code, result = run_bql("check-build", self.dir / "BrushesQuickLook.app")
        self.assertEqual((code, result["ok"], result["error"]),
                         (2, False, f"{self.dir}/BrushesQuickLook.app is not an app bundle"))

    def test_a_tool_that_prints_valid_output_and_exits_nonzero_fails_the_cli_in_every_bundle(self):
        for kind in ("app", *bql.PLUGINS):
            for tool in ("lipo", "codesign -dv", "codesign -d", "nm", "otool"):
                with self.subTest(f"{tool} on the {kind}"):
                    app, tool_output = self.shippable_build()
                    tool_output[kind]["exit"][tool] = 9
                    bundle = bql.bundles(app)[kind]
                    target = bundle if tool.startswith("codesign") else bundle / "Contents/MacOS" / bundle.stem
                    with mock.patch.object(subprocess, "run", self.tools(app, tool_output)):
                        code, result = run_bql("check-build", app)
                    self.assertEqual((code, result["ok"], bool(result.get("fix"))), (2, False, True))
                    self.assertTrue(result["error"].startswith(f"{tool} "), result["error"])
                    self.assertIn(f" {target} exited 9: ", result["error"])


if __name__ == "__main__":
    unittest.main()
