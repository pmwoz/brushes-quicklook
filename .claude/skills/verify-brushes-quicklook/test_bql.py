import ast
import ctypes
import dataclasses
import errno
import importlib.machinery
import importlib.util
import io
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager, nullcontext, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Set, Tuple
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
        root is "app", "build", "renamed" or None for a process that exited."""
        executables = {"BrushesPreview": "Contents/PlugIns/BrushesPreview.appex/Contents/MacOS/BrushesPreview",
                       "BrushesQuickLook": "Contents/MacOS/BrushesQuickLook"}
        processes = {"BrushesPreview": previews or {}, "BrushesQuickLook": apps or {}}
        owner = {pid: name for name, pids in processes.items() for pid in pids}
        states = {pid: state for pids in processes.values() for pid, state in pids.items()}
        base = Path(os.path.realpath(tempfile.mkdtemp(dir=self.dir)))
        app, build = base / "installed/BrushesQuickLook.app", base / "build/BrushesQuickLook.app"
        roots = {"app": app, "build": build, "renamed": base / "Renamed.app"}
        for bundle, exists in ((app, installed), (build, built), (roots["renamed"], True)):
            if exists:
                FakeMac.write_bundle(bundle, "")
        table = {int(pid): f"{roots[state[0]]}/{executables[owner[pid]]}" for pid, state in states.items() if state[0]}
        (base / "project.yml").write_text("")
        os.utime(base / "project.yml", (0, 0))
        hashes = {str(path): f"{kind} cdhash" for bundle in (app, build) for kind, path in bql.bundles(bundle).items()}
        if mismatched:
            hashes[str(bql.bundles(app)[mismatched])] = "older cdhash"

        def run(args, timeout=120, check=False):
            if args[0] == "pluginkit":
                kind = args[-1].rsplit(".", 1)[1]
                line = f"+    {args[-1]}(1.0)\t{bql.bundles(app)[kind]}\n"
                return SimpleNamespace(returncode=0, stdout="" if kind == unregistered else line)
            if args[0] == "git":
                return SimpleNamespace(returncode=0, stdout="project.yml\n")
            if args[0] == "codesign":
                error = states[args[-1]][1]
                return SimpleNamespace(returncode=1 if error else 0, stderr=f"{error}\n" if error else "")
            if args[0] == bql.LSREGISTER:
                copies = [app, base / "Other/BrushesQuickLook.app"] if other_copy else [app]
                return SimpleNamespace(returncode=0, stdout="".join(map(ls_record, copies)))
            return SimpleNamespace(stdout="")
        return {"REPO": base, "APP": app, "BUILD": build, "run": run, "cdhash": lambda path: hashes[str(path)],
                "alive": lambda pid: states[str(pid)][2], "LIBPROC": FakeLibproc(lambda: table)}

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
            (("doctor",), "installed: ", self.doctor(installed=False)),
            (("doctor",), "release-build: ", self.doctor(built=False)),
            (("doctor",), "launchservices: other copies are registered", self.doctor(other_copy=True)),
        ]
        rows += [(("doctor",), f"cdhash-{kind}: ", self.doctor(mismatched=kind))
                 for kind in ("app", "preview", "thumbnail")]
        rows += [(("doctor",), f"pluginkit-{kind}: ", self.doctor(unregistered=kind)) for kind in bql.PLUGINS]
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

    def test_a_doctor_run_with_no_problem_exits_0(self):
        code, result = run_bql("doctor", **self.doctor(previews={"101": ("app", None, True)},
                                                        apps={"201": ("app", None, True)}))
        self.assertEqual((code, result["ok"], "error" in result, "fix" in result), (0, True, False, False))

    def test_doctor_fails_on_a_live_extension_process_not_running_the_installed_code(self):
        replaced = "102: the code on disk does not match what is running"
        previews = {"101": ("app", None, True), "102": ("app", replaced, True), "103": ("build", None, True),
                    "104": ("renamed", None, True), "105": (None, None, False),
                    "106": ("app", "106: No such process", False), "107": ("renamed", "107: No such process", False)}
        code, result = run_bql("doctor", **self.doctor(previews=previews))
        observed = {p["pid"]: p["verify_error"] for p in result["observed"]["processes"]}
        self.assertEqual((code, observed), (1, {101: None, 102: replaced, 103: None, 104: None}))
        self.assertEqual(re.findall(r"running-preview: pid (\d+)", result["error"]), ["102", "103", "104"])

    def test_doctor_fails_on_the_installed_host_app_running_replaced_code_and_ignores_other_copies(self):
        replaced = "202: the code on disk does not match what is running"
        apps = {"201": ("app", None, True), "202": ("app", replaced, True), "203": ("build", None, True)}
        code, result = run_bql("doctor", **self.doctor(apps=apps))
        self.assertEqual((code, re.findall(r"running-app: pid (\d+)", result["error"])), (1, ["202"]))
        self.assertIn("Run `kill 202`", result["fix"])

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


class ProcessTableTest(unittest.TestCase):
    def test_the_kernel_names_each_process_by_the_file_it_executed_whatever_started_it(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        (tmp / "alias").symlink_to("/bin", target_is_directory=True)
        starts = [{"args": [str(tmp / "alias/sleep"), "30"]}, {"args": ["./sleep", "30"], "cwd": tmp / "alias"},
                  {"args": [str(bql.APP / bql.EXECUTABLES["app"]), "30"], "executable": "/bin/sleep"}]
        started = []
        for start in starts:
            proc = subprocess.Popen(**start)
            self.addCleanup(proc.wait)
            self.addCleanup(proc.kill)
            started.append(proc)
        table = bql.process_table()
        self.assertEqual([table.get(proc.pid) for proc in started], [("sleep", "/bin/sleep")] * len(starts))


APP = "/Applications/BrushesQuickLook.app"
RELEASE = "/Users/me/brushes-quicklook/build.noindex/Build/Products/Release/BrushesQuickLook.app"
DEBUG = "/Users/me/Library/Developer/Xcode/DerivedData/BrushesQuickLook-abc/Build/Products/Debug/BrushesQuickLook.app"
REPLACED = "the code on disk does not match what is running"


def ls_record(path, identifier=bql.BUNDLE_ID):
    return (f"{'-' * 80}\nbundle id:                  BrushesQuickLook (0x1)\n"
            f"path:                       {path} (0x2)\nidentifier:                 {identifier}\n")


def process(kind, pid, app=APP, verify_error=None):
    return bql.Process(kind, pid, f"{app}/{bql.EXECUTABLES[kind]}", app != APP, verify_error)


def observed(**changes):
    hashes = {"app": "a1", "preview": "b2", "thumbnail": "c3"}
    plugins = {kind: [bql.Plugin("+", f"{APP}/Contents/PlugIns/{name}.appex")] for kind, name in bql.PLUGINS.items()}
    clean = bql.Observed(app=APP, build=RELEASE, installed=dict(hashes), built=dict(hashes), registered=[APP],
                         plugins=plugins,
                         processes=[process("app", 201), process("preview", 101), process("thumbnail", 111)])
    return dataclasses.replace(clean, **changes)


class ReadinessTest(unittest.TestCase):
    def test_each_fixture_yields_exactly_its_problems(self):
        f3 = [process("app", 201), process("preview", 102, verify_error=f"102: {REPLACED}"), process("thumbnail", 111)]
        f5 = [process("app", 202, verify_error=f"202: {REPLACED}"), process("preview", 101), process("thumbnail", 111)]
        silent = [process("app", 201), process("preview", 102, verify_error=""), process("thumbnail", 111)]
        rows = [
            ("F1 a clean install", observed(), []),
            ("F2 a second registered copy", observed(registered=[APP, RELEASE]),
             [("launchservices", f"other copies are registered: {RELEASE}", "Run `bql install`.")]),
            ("F3 a live preview process whose binary was replaced", observed(processes=f3),
             [("running-preview", f"pid 102 runs {APP}/{bql.EXECUTABLES['preview']}: 102: {REPLACED}",
               "Run `kill 102`.")]),
            ("F5 the installed host app whose binary was replaced", observed(processes=f5),
             [("running-app", f"pid 202 runs {APP}/{bql.EXECUTABLES['app']}: 202: {REPLACED}",
               f"Run `kill 202`, then `open {APP}`.")]),
            ("a live process that failed verification without a message", observed(processes=silent),
             [("running-preview", f"pid 102 runs {APP}/{bql.EXECUTABLES['preview']}: ", "Run `kill 102`.")]),
            ("a live preview process of another copy", observed(processes=[process("preview", 103, app=RELEASE)]),
             [("running-preview", f"pid 103 runs {RELEASE}/{bql.EXECUTABLES['preview']}", "Run `kill 103`.")]),
        ]
        for fixture_name, fixture, expected in rows:
            with self.subTest(fixture_name):
                problems = bql.readiness(fixture)
                self.assertEqual([problem[:2] for problem in problems], [row[:2] for row in expected])
                self.assertEqual([row[2] in problem[2] for problem, row in zip(problems, expected)],
                                 [True] * len(expected))


class FakeLibproc:
    def __init__(self, table):
        caller = {os.getpid(): sys.executable}
        self.table = lambda: {**caller, **table()}
        self.errors: Dict[str, int] = {}
        self.executed_names: Dict[int, str] = {}
        self.exited: Set[int] = set()

    def failed(self, call):
        if call in self.errors:
            ctypes.set_errno(self.errors[call])
            return True
        return False

    def proc_listpids(self, kind, uid, buffer, size):
        if (kind, uid) != (bql.PROC_RUID_ONLY, os.getuid()):
            raise AssertionError(f"proc_listpids lists {kind} {uid}, not the processes of the current user")
        if self.failed("proc_listpids"):
            return 0
        pids = [*self.table(), *sorted(self.exited)][:size // ctypes.sizeof(ctypes.c_int)]
        buffer[:len(pids)] = pids
        return len(pids) * ctypes.sizeof(ctypes.c_int)

    def proc_name(self, pid, buffer, size):
        if self.failed(f"proc_name {pid}"):
            return 0
        if pid not in self.table():
            ctypes.set_errno(errno.ESRCH)
            return 0
        buffer.value = os.fsencode(self.executed_names.get(pid) or Path(os.path.realpath(self.table()[pid])).name)
        return len(buffer.value)

    def proc_pidpath(self, pid, buffer, size):
        if self.failed(f"proc_pidpath {pid}"):
            return 0
        if pid not in self.table():
            ctypes.set_errno(errno.ESRCH)
            return 0
        path = os.path.realpath(self.table()[pid])
        if not os.path.exists(path):
            ctypes.set_errno(errno.ENOENT)
            return 0
        buffer.value = os.fsencode(path)
        return len(buffer.value)


class FakeMac:
    def __init__(self):
        tmp = tempfile.TemporaryDirectory()
        self.cleanup = tmp.cleanup
        self.root = Path(os.path.realpath(tmp.name))
        self.app = self.root / "Applications/BrushesQuickLook.app"
        self.repo = self.root / "repo"
        self.build = self.repo / "build.noindex/Build/Products/Release/BrushesQuickLook.app"
        self.registered, self.other_records = set(), []
        self.plugins, self.elected, self.plugin_suffix = {kind: [] for kind in bql.PLUGINS}, set(), ""
        self.processes, self.replaced, self.replaced_while_running = {}, {}, []
        self.libproc = FakeLibproc(lambda: self.processes)
        self.failures: Dict[Tuple[str, ...], Tuple[int, str, str]] = {}
        self.hangs: Set[Tuple[str, ...]] = set()
        self.missing: Set[Tuple[str, ...]] = set()
        self.worktrees, self.add_fails = set(), None
        self.quits, self.build_fails, self.build_deletes, self.build_problems = True, False, False, []
        self.commands, self.now = [], [0.0]
        self.repo.mkdir()
        (self.repo / "project.yml").write_text("")

    @staticmethod
    def write_bundle(app, binary):
        for kind, executable in bql.EXECUTABLES.items():
            (app / executable).parent.mkdir(parents=True, exist_ok=True)
            (app / executable).write_text(f"{binary}_{kind}")
            identifier = bql.BUNDLE_ID if kind == "app" else f"{bql.BUNDLE_ID}.{kind}"
            (app / executable).parents[1].joinpath("Info.plist").write_bytes(
                plistlib.dumps({"CFBundleIdentifier": identifier}))

    def ready(self):
        self.write_bundle(self.app, "main")
        self.write_bundle(self.build, "main")
        self.registered = {str(self.app)}
        self.plugins = {kind: [f"{self.app}/Contents/PlugIns/{name}.appex"] for kind, name in bql.PLUGINS.items()}
        self.elected = set(bql.PLUGINS)
        self.processes = {201: f"{self.app}/{bql.EXECUTABLES['app']}",
                          101: f"{self.app}/{bql.EXECUTABLES['preview']}"}

    def alias(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root / "Applications", target_is_directory=True)
        return alias / "BrushesQuickLook.app"

    def rename_app(self):
        renamed = self.app.with_name("Renamed.app")
        self.app.rename(renamed)
        self.app.symlink_to(renamed, target_is_directory=True)
        return renamed

    def alias_executable(self):
        executable = self.app / bql.EXECUTABLES["app"]
        executable.rename(executable.with_name("ActualApp"))
        executable.symlink_to("ActualApp")
        return executable.with_name("ActualApp")

    def delete_copy(self, pid, kind):
        copy = self.root / "tmp/Renamed.app"
        self.write_bundle(copy, "copy")
        self.processes[pid] = f"{copy}/{bql.EXECUTABLES[kind]}"
        shutil.rmtree(copy)

    def swap_bundle(self, pid, kind):
        old = self.root / "tmp/Old.app"
        old.parent.mkdir(exist_ok=True)
        self.app.rename(old)
        shutil.copytree(old, self.app)
        # proc_pidpath follows the rename, so pid reports Old.app until it is deleted, then ENOENT.
        self.processes[pid] = f"{old}/{bql.EXECUTABLES[kind]}"
        shutil.rmtree(old)

    def hard_link(self, pid, kind):
        return self.keep_old_executable(pid, kind, self.root / f"old-{kind}")

    def rename_in_place(self, pid, kind):
        return self.keep_old_executable(pid, kind, (self.app / bql.EXECUTABLES[kind]).with_name("Old"))

    def keep_old_executable(self, pid, kind, old):
        executable = self.app / bql.EXECUTABLES[kind]
        os.link(executable, old)
        executable.unlink()
        shutil.copy(old, executable)
        self.processes[pid] = str(old)
        self.libproc.executed_names[pid] = executable.name
        return old

    def inside(self, path):
        if self.root not in Path(os.path.realpath(path)).parents:
            raise AssertionError(f"{path} is outside the test folder")
        return Path(path)

    def installed(self):
        return (self.app / bql.EXECUTABLES["app"]).read_text()

    def mutations(self):
        def mutates(args):
            return (args[0] in ("check-build", "osascript", "rm", "ditto", "open")
                    or args[:2] in ([bql.LSREGISTER, "-u"], [bql.LSREGISTER, "-f"], ["pluginkit", "-a"],
                                    ["pluginkit", "-e"]))
        return [args[:1] if args[0] == "osascript" else args for args in self.commands if mutates(args)]

    def run(self, args, input=None, capture_output=True, text=True, timeout=120):
        args = list(map(str, args))
        self.commands.append(args)
        if any(args[:len(prefix)] == list(prefix) for prefix in self.hangs):
            raise subprocess.TimeoutExpired(args, timeout)
        if any(args[:len(prefix)] == list(prefix) for prefix in self.missing):
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), args[0])
        for prefix, (returncode, stdout, stderr) in self.failures.items():
            if args[:len(prefix)] == list(prefix):
                return subprocess.CompletedProcess(args, returncode, stdout, stderr)
        return self.answer(args)

    def answer(self, args):
        done = subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == [bql.LSREGISTER, "-dump"]:
            apps = sorted(self.registered)
            records = ([(path, bql.BUNDLE_ID) for path in apps] + self.other_records
                       + [(f"{path}/Contents/PlugIns/{name}.appex", f"{bql.BUNDLE_ID}.{kind}")
                          for path in apps for kind, name in bql.PLUGINS.items()])
            done.stdout = "".join(ls_record(*record) for record in records)
        elif args[:2] == [bql.LSREGISTER, "-u"]:
            matches = {path for path in self.registered if os.path.realpath(path) == os.path.realpath(args[2])}
            if not matches and not os.path.exists(args[2]):
                done.returncode, done.stderr = 1, f"failed to scan {args[2]}: -10814\n"
            self.registered -= matches
        elif args[:3] == [bql.LSREGISTER, "-f", "-R"]:
            self.registered.add(str(self.inside(args[3])))
        elif args[:2] == ["pluginkit", "-m"]:
            kind = args[-1].rsplit(".", 1)[1]
            election = "+" if kind in self.elected else " "
            done.stdout = "".join(f"{election}    {args[-1]}(1.0)\t1A2B3C4D-0000-0000-0000-000000000001\t"
                                  f"2026-10-01 12:00:00 +0000\t{path}{self.plugin_suffix}\n"
                                  for path in self.plugins[kind])
        elif args[:2] == ["pluginkit", "-a"]:
            kind = next(kind for kind, name in bql.PLUGINS.items() if args[2].endswith(f"/{name}.appex"))
            self.plugins[kind] = [str(self.inside(args[2]))]
        elif args[:3] == ["pluginkit", "-e", "use"]:
            self.elected.add(args[-1].rsplit(".", 1)[1])
        elif args[:2] == ["codesign", "-v"]:
            if int(args[2]) in self.replaced:
                done.returncode, done.stderr = 1, self.replaced[int(args[2])]
        elif args[:2] == ["codesign", "-dvvv"]:
            bundle = Path(args[2])
            executable = f"Contents/MacOS/{bundle.stem}" if bundle.suffix == ".appex" else bql.EXECUTABLES["app"]
            done.stderr = f"Executable={bundle}\nCDHash={(bundle / executable).read_text()}\n"
        elif args[0] == "osascript":
            if self.quits:
                installed = os.path.realpath(self.app / bql.EXECUTABLES["app"])
                self.processes = {pid: path for pid, path in self.processes.items()
                                  if os.path.realpath(path) != installed}
        elif args[0] == "rm":
            removed = Path(args[-1]) / bql.EXECUTABLES["app"]
            if removed.exists():
                self.replaced_while_running += [pid for pid, path in self.processes.items()
                                                if os.path.exists(path) and os.path.samefile(path, removed)]
            shutil.rmtree(self.inside(args[-1]), ignore_errors=True)
        elif args[0] == "ditto":
            shutil.copytree(self.inside(args[1]), self.inside(args[2]))
        elif args[0] == "open":
            self.processes[300] = f"{self.inside(args[1])}/{bql.EXECUTABLES['app']}"
        elif args[:3] == ["git", "-C", str(self.repo)]:
            self.git(args[3:], done)
        elif args[0].endswith("/scripts/build.sh"):
            build = Path(args[0]).parents[1] / self.build.relative_to(self.repo)
            self.write_bundle(self.inside(build), "main")
            self.registered.add(str(build))
            if self.build_deletes:
                shutil.rmtree(build)
            if self.build_fails:
                done.returncode, done.stderr = 65, "** BUILD FAILED **\n"
        else:
            raise AssertionError(f"unexpected command {args}")
        return done

    def git(self, args, done):
        if args[:2] == ["worktree", "add"]:
            if self.add_fails != "before":
                (self.inside(args[-2]) / "scripts").mkdir(parents=True)
                self.worktrees.add(args[-2])
            if self.add_fails:
                done.returncode, done.stderr = 128, "fatal: could not check out origin/main\n"
        elif args[:2] == ["worktree", "remove"]:
            if args[-1] in self.worktrees:
                shutil.rmtree(self.inside(args[-1]))
                self.worktrees.discard(args[-1])
            else:
                done.returncode, done.stderr = 128, f"fatal: '{args[-1]}' is not a working tree\n"
        elif args[0] == "ls-files":
            done.stdout = "project.yml\n"
        elif args[:2] != ["fetch", "origin"]:
            raise AssertionError(f"unexpected git {args}")

    def stubs(self, **changes):
        def sleep(seconds):
            self.now[0] += seconds

        def check_build(app):
            self.commands.append(["check-build", str(app)])
            return self.build_problems
        return {"subprocess": SimpleNamespace(run=self.run, TimeoutExpired=subprocess.TimeoutExpired),
                "LIBPROC": self.libproc, "alive": lambda pid: pid in self.processes, "check_build": check_build,
                "REPO": self.repo, "BUILD": self.build, "APP": self.app, "WORK": self.root / "work",
                "STATE": self.root / "work/state.json", "time": SimpleNamespace(time=lambda: self.now[0], sleep=sleep),
                "tempfile": SimpleNamespace(mkdtemp=lambda: tempfile.mkdtemp(dir=self.root)), **changes}


class DoctorTest(unittest.TestCase):
    def setUp(self):
        self.mac = FakeMac()
        self.addCleanup(self.mac.cleanup)
        self.mac.ready()

    def test_paths_compare_by_the_bundle_they_resolve_to(self):
        alias = self.mac.alias()
        executable = f"{self.mac.app}/{bql.EXECUTABLES['app']}"
        self.mac.processes = {201: f"{alias}/{bql.EXECUTABLES['app']}", 101: f"{alias}/{bql.EXECUTABLES['preview']}"}
        self.mac.replaced = {201: f"201: {REPLACED}"}
        self.mac.plugin_suffix = "/"
        code, result = run_bql("doctor", **self.mac.stubs())
        self.assertEqual((code, result.get("error")), (1, f"running-app: pid 201 runs {executable}: 201: {REPLACED}"))
        self.mac.replaced = {}
        code, result = run_bql("doctor", **self.mac.stubs(APP=alias))
        self.assertEqual((code, result["ok"], result["observed"]["app"]), (0, True, str(self.mac.app)))

    def test_a_live_process_of_the_app_or_a_copy_counts_however_its_path_is_spelled(self):
        def renamed_app(mac):
            mac.replaced = {201: f"201: {REPLACED}"}
            return f"running-app: pid 201 runs {mac.rename_app()}/{bql.EXECUTABLES['app']}: 201: {REPLACED}"

        def executable_alias(mac):
            mac.replaced = {201: f"201: {REPLACED}"}
            return f"running-app: pid 201 runs {mac.alias_executable()}: 201: {REPLACED}"

        def renamed_copy(mac):
            copy = mac.root / "tmp/Renamed.app"
            mac.write_bundle(copy, "copy")
            mac.processes[102] = f"{copy}/{bql.EXECUTABLES['preview']}"
            return f"running-preview: pid 102 runs {mac.processes[102]}"

        def debug_host_app(mac):
            debug = mac.root / "DerivedData/Debug/BrushesQuickLook.app"
            mac.write_bundle(debug, "debug")
            mac.processes[203] = f"{debug}/{bql.EXECUTABLES['app']}"
            return None

        for name, setup in [("the installed app is a symlink to a renamed bundle", renamed_app),
                            ("the installed executable is a symlink", executable_alias),
                            ("a renamed copy runs its preview extension", renamed_copy),
                            ("F4 a Debug build runs its host app", debug_host_app)]:
            with self.subTest(name):
                mac = FakeMac()
                self.addCleanup(mac.cleanup)
                mac.ready()
                error = setup(mac)
                code, result = run_bql("doctor", **mac.stubs())
                self.assertEqual((code, result.get("error")), (1 if error else 0, error))

    def test_only_complete_paths_of_records_with_the_app_bundle_id_are_copies(self):
        app, other, renamed = str(self.mac.app), f"{self.mac.app}-other", str(self.mac.root / "tmp/Renamed.app")
        rows = [
            ("a prefix collision alone", {other},
             f"launchservices: other copies are registered: {other}. launchservices: {app} is not registered"),
            ("a prefix collision beside the app", {app, other},
             f"launchservices: other copies are registered: {other}"),
            ("a renamed copy", {app, renamed}, f"launchservices: other copies are registered: {renamed}"),
        ]
        for name, registered, error in rows:
            with self.subTest(name):
                self.mac.registered = registered
                code, result = run_bql("doctor", **self.mac.stubs())
                self.assertEqual((code, result.get("error")), (1, error))

    def test_a_live_process_that_fails_verification_without_a_message_fails_readiness(self):
        self.mac.replaced = {101: ""}
        code, result = run_bql("doctor", **self.mac.stubs())
        executable = f"{self.mac.app}/{bql.EXECUTABLES['preview']}"
        self.assertEqual((code, result.get("error")),
                         (1, f"running-preview: pid 101 runs {executable}: codesign -v exited 1"))

    def test_a_failed_or_signalled_collector_exits_2_instead_of_reading_as_an_observation(self):
        cdhash = f"Executable={self.mac.app}\nCDHash=main_app\n"
        source_list = ("git", "-C", str(self.mac.repo), "ls-files")
        rows = [((bql.LSREGISTER, "-dump"), 1, "", ""), ((bql.LSREGISTER, "-dump"), -15, "", ""),
                (("pluginkit", "-m"), 1, "", ""), (("pluginkit", "-m"), -15, "", ""),
                (("codesign", "-v"), 2, "", ""), (("codesign", "-v"), -15, "", ""),
                (("codesign", "-dvvv"), 7, "", cdhash), (("codesign", "-dvvv"), -15, "", ""),
                (("codesign", "-dvvv"), 0, "", "Executable=x\n"),
                (source_list, 7, "project.yml\n", "partial listing"), (source_list, -15, "project.yml\n", "")]
        for prefix, returncode, stdout, stderr in rows:
            with self.subTest(command=" ".join(prefix), returncode=returncode):
                self.mac.failures = {prefix: (returncode, stdout, stderr)}
                code, result = run_bql("doctor", **self.mac.stubs())
                self.assertEqual((code, result["ok"], bool(result.get("fix"))), (2, False, True))
                self.assertIn(" ".join(prefix), result["error"])
        self.mac.failures = {}
        for call, error in [("proc_listpids", errno.EPERM), ("proc_name 101", errno.EINVAL),
                            ("proc_pidpath 101", errno.EPERM)]:
            with self.subTest(call=call):
                self.mac.libproc.errors = {call: error}
                code, result = run_bql("doctor", **self.mac.stubs())
                self.assertEqual((code, result["ok"], bool(result.get("fix"))), (2, False, True))
                self.assertIn(f"{call} failed: {os.strerror(error)}", result["error"])

    def test_a_process_listed_after_the_first_1024_is_observed(self):
        self.mac.processes = {**{10000 + i: f"/usr/bin/tool{i}" for i in range(1100)}, **self.mac.processes}
        self.mac.replaced = {201: f"201: {REPLACED}"}
        code, result = run_bql("doctor", **self.mac.stubs())
        self.assertEqual((code, re.findall(r"running-app: pid (\d+)", result.get("error", ""))), (1, ["201"]))

    def test_a_process_that_exited_after_the_listing_or_runs_as_another_user_is_not_observed(self):
        self.mac.processes[401] = "/usr/bin/login"
        self.mac.libproc.errors = {"proc_name 401": errno.EPERM}
        self.mac.libproc.exited = {402}
        code, result = run_bql("doctor", **self.mac.stubs())
        self.assertEqual((code, [p["pid"] for p in result["observed"]["processes"]]), (0, [201, 101]))

    def test_a_process_that_runs_the_installed_file_through_a_hard_link_runs_the_installed_app(self):
        link = self.mac.root / "link"
        os.link(self.mac.app / bql.EXECUTABLES["preview"], link)
        self.mac.processes[101] = str(link)
        self.mac.libproc.executed_names[101] = "BrushesPreview"
        code, result = run_bql("doctor", **self.mac.stubs())
        self.assertEqual((code, [(p["pid"], p["elsewhere"]) for p in result["observed"]["processes"]]),
                         (0, [(201, False), (101, False)]))

    def test_a_live_process_counts_after_its_executable_is_deleted_or_replaced(self):
        for kind in bql.EXECUTABLES:
            for setup in (FakeMac.delete_copy, FakeMac.swap_bundle, FakeMac.hard_link, FakeMac.rename_in_place):
                with self.subTest(kind=kind, setup=setup.__name__):
                    mac = FakeMac()
                    self.addCleanup(mac.cleanup)
                    mac.ready()
                    mac.processes = {}
                    runs = setup(mac, 102, kind) or "a deleted executable"
                    code, result = run_bql("doctor", **mac.stubs())
                    self.assertEqual((code, result.get("error")), (1, f"running-{kind}: pid 102 runs {runs}"))
                    self.assertIn("Run `kill 102`", result["fix"])


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.mac = self.new_mac()

    def new_mac(self):
        mac = FakeMac()
        self.addCleanup(mac.cleanup)
        mac.write_bundle(mac.app, "old")
        mac.write_bundle(mac.build, "branch")
        debug = mac.root / "DerivedData/Debug/BrushesQuickLook.app"
        mac.write_bundle(debug, "debug")
        mac.registered = {DEBUG}
        mac.processes = {201: f"{mac.app}/{bql.EXECUTABLES['app']}", 203: f"{debug}/{bql.EXECUTABLES['app']}"}
        return mac

    def worktree(self, mac):
        return next(Path(args[-2]) for args in mac.commands if args[3:5] == ["worktree", "add"])

    def test_it_replaces_registers_and_elects_the_build_in_order_then_passes_readiness(self):
        app, build = self.mac.app, self.mac.build
        code, result = run_bql("install", "--no-build", **self.mac.stubs())
        self.assertEqual((code, result["steps"]), (0, ["check-build", "unregister 1 stale paths", "quit", "replace",
                                                       "register", "verify"]))
        self.assertEqual(self.mac.mutations(), [
            ["check-build", str(build)], [bql.LSREGISTER, "-u", DEBUG], ["osascript"], ["rm", "-rf", "--", str(app)],
            ["ditto", str(build), str(app)], [bql.LSREGISTER, "-f", "-R", str(app)],
            ["pluginkit", "-a", f"{app}/Contents/PlugIns/BrushesPreview.appex"],
            ["pluginkit", "-a", f"{app}/Contents/PlugIns/BrushesThumbnail.appex"], ["open", str(app)],
            ["pluginkit", "-e", "use", "-i", f"{bql.BUNDLE_ID}.preview"],
            ["pluginkit", "-e", "use", "-i", f"{bql.BUNDLE_ID}.thumbnail"]])
        self.assertEqual((self.mac.installed(), self.mac.registered, set(self.mac.processes)),
                         ("branch_app", {str(app)}, {203, 300}))

    def test_a_build_that_fails_check_build_changes_nothing(self):
        self.mac.build_problems = [("BrushesQuickLook.app Contents/Resources/AppIcon.icns", "is missing", "Keep it.")]
        code, result = run_bql("install", "--no-build", **self.mac.stubs())
        self.assertEqual((code, result["failed_step"], result["error"]),
                         (1, "check-build", "BrushesQuickLook.app Contents/Resources/AppIcon.icns: is missing"))
        self.assertEqual((self.mac.mutations(), self.mac.installed(), self.mac.registered),
                         ([["check-build", str(self.mac.build)]], "old_app", {DEBUG}))

    def test_a_problem_left_after_the_install_fails_it_with_the_fix_from_readiness(self):
        def stale_preview(mac):
            mac.processes[102] = f"{mac.app}/{bql.EXECUTABLES['preview']}"
            mac.replaced = {102: f"102: {REPLACED}"}
            return f"running-preview: pid 102 runs {mac.processes[102]}: 102: {REPLACED}"

        def renamed_copy_preview(mac):
            copy = mac.root / "tmp/Renamed.app"
            mac.write_bundle(copy, "copy")
            mac.processes[102] = f"{copy}/{bql.EXECUTABLES['preview']}"
            return f"running-preview: pid 102 runs {mac.processes[102]}"

        for name, setup in [("a preview process of the replaced app", stale_preview),
                            ("a preview process of a renamed copy", renamed_copy_preview)]:
            with self.subTest(name):
                mac = self.new_mac()
                error = setup(mac)
                code, result = run_bql("install", "--no-build", **mac.stubs())
                self.assertEqual((code, result.get("failed_step"), result.get("error"), mac.installed()),
                                 (1, "verify", error, "branch_app"))
                self.assertIn("Run `kill 102`.", result["fix"])

    def test_an_app_still_running_10_s_after_the_quit_request_fails_the_install_and_is_not_killed(self):
        self.mac.quits = False
        code, result = run_bql("install", "--no-build", **self.mac.stubs())
        self.assertEqual((code, result["failed_step"], result["steps"]),
                         (1, "quit", ["check-build", "unregister 1 stale paths"]))
        self.assertIn(f"pid 201 still runs {self.mac.app} 10 s after the quit request", result["error"])
        self.assertEqual((self.mac.now[0], set(self.mac.processes), self.mac.installed()), (10, {201, 203}, "old_app"))

    def test_the_running_installed_app_blocks_the_replacement_however_its_path_is_spelled_or_lost(self):
        def app_through_alias(mac):
            mac.processes[201] = f"{mac.alias()}/{bql.EXECUTABLES['app']}"
            return {}

        def destination_alias(mac):
            return {"APP": mac.alias()}

        def renamed_destination(mac):
            mac.rename_app()
            return {}

        def executable_alias(mac):
            mac.alias_executable()
            return {}

        def destination_in_another_case(mac):
            other_case = mac.app.with_name(mac.app.name.lower())
            if not other_case.exists():
                self.skipTest("the volume is case-sensitive")
            return {"APP": other_case}

        def swapped_bundle(mac):
            mac.swap_bundle(201, "app")
            return {}

        def old_hard_link(mac):
            mac.hard_link(201, "app")
            return {}

        def renamed_in_place(mac):
            mac.rename_in_place(201, "app")
            return {}

        for name, setup in [("the app runs through an alias", app_through_alias),
                            ("the destination is an alias", destination_alias),
                            ("the destination is a symlink to a renamed bundle", renamed_destination),
                            ("the installed executable is a symlink", executable_alias),
                            ("the destination is spelled in another case", destination_in_another_case),
                            ("an installer swapped the bundle under the app", swapped_bundle),
                            ("the app runs an old hard link of its executable", old_hard_link),
                            ("the app runs its old executable renamed in the bundle", renamed_in_place)]:
            with self.subTest(name):
                mac = self.new_mac()
                mac.quits = False
                code, result = run_bql("install", "--no-build", **mac.stubs(**setup(mac)))
                self.assertEqual((code, result.get("failed_step"), mac.replaced_while_running, mac.installed()),
                                 (1, "quit", [], "old_app"))

    def test_a_registration_of_the_destination_through_an_alias_is_not_unregistered(self):
        for name, registration_is_alias in (("the registration is an alias", True),
                                            ("the destination is an alias", False)):
            with self.subTest(name):
                mac = self.new_mac()
                alias = mac.alias()
                registration, destination = (alias, mac.app) if registration_is_alias else (mac.app, alias)
                mac.registered = {str(registration), DEBUG}
                code, result = run_bql("install", "--no-build", **mac.stubs(APP=destination))
                unregistered = [args[2] for args in mac.commands if args[:2] == [bql.LSREGISTER, "-u"]]
                self.assertEqual((code, result["ok"], unregistered), (0, True, [DEBUG]))

    def test_a_failed_process_table_read_stops_the_install_before_the_replacement(self):
        for call, error in [("proc_listpids", errno.EPERM), ("proc_name 201", errno.EINVAL),
                            ("proc_pidpath 201", errno.EPERM)]:
            with self.subTest(call=call):
                mac = self.new_mac()
                mac.quits = False
                mac.libproc.errors = {call: error}
                code, result = run_bql("install", "--no-build", **mac.stubs())
                self.assertEqual((code, result["ok"], mac.replaced_while_running, mac.installed()),
                                 (2, False, [], "old_app"))
                self.assertIn(f"{call} failed", result["error"])

    def test_a_failed_unregister_stops_the_install_before_the_quit(self):
        self.mac.failures[(bql.LSREGISTER, "-u")] = (7, "", "unregister denied")
        code, result = run_bql("install", "--no-build", **self.mac.stubs())
        self.assertEqual((code, result["ok"]), (2, False))
        self.assertIn(f"{bql.LSREGISTER} -u {DEBUG} exited 7: unregister denied", result["error"])
        self.assertEqual(self.mac.mutations(), [["check-build", str(self.mac.build)], [bql.LSREGISTER, "-u", DEBUG]])

    def test_main_installs_origin_main_built_in_a_temporary_worktree_then_removes_it(self):
        code, result = run_bql("install", "--main", **self.mac.stubs())
        worktree = self.worktree(self.mac)
        repo = str(self.mac.repo)
        self.assertEqual((code, result["steps"]), (0, ["build", "check-build", "unregister 2 stale paths", "quit",
                                                       "replace", "register", "verify"]))
        self.assertEqual([args for args in self.mac.commands if args[0] == "git" or args[0].endswith("build.sh")], [
            ["git", "-C", repo, "fetch", "origin", "main"],
            ["git", "-C", repo, "worktree", "add", "--detach", str(worktree), "origin/main"],
            [f"{worktree}/scripts/build.sh"],
            ["git", "-C", repo, "worktree", "remove", "--force", str(worktree)]])
        self.assertEqual((self.mac.installed(), self.mac.registered, set(self.mac.processes)),
                         ("main_app", {str(self.mac.app)}, {203, 300}))
        self.assertFalse(worktree.exists())

    def test_main_cleanup_runs_after_every_failure_and_reports_what_it_left(self):
        build_failed = "scripts/build.sh: ** BUILD FAILED **"
        unregister, remove = "{lsregister} -u {build}", "git -C {repo} worktree remove --force {worktree}"
        rows = [
            ("the build fails", {"build_fails": True}, 1, [build_failed], False, False, []),
            ("the build registers its product, deletes it and fails", {"build_fails": True, "build_deletes": True},
             1, [build_failed], False, False, []),
            ("the build fails and its unregister fails",
             {"build_fails": True, "failures": {("{lsregister}", "-u"): (7, "", "unregister denied")}}, 2,
             [build_failed, "-u {build} exited 7: unregister denied"], False, True, [unregister]),
            ("the build fails and its unregister hangs", {"build_fails": True, "hangs": {("{lsregister}", "-u")}}, 2,
             [build_failed, "-u {build} did not return within 120 s"], False, True, [unregister]),
            ("the build fails and its unregister cannot start",
             {"build_fails": True, "missing": {("{lsregister}", "-u")}}, 2,
             [build_failed, "-u {build}: [Errno 2] No such file or directory"], False, True, [unregister]),
            ("the build fails and LaunchServices cannot be read",
             {"build_fails": True, "failures": {("{lsregister}", "-dump"): (7, "", "dump denied")}}, 2,
             [build_failed, "-dump exited 7: dump denied"], False, False, [unregister]),
            ("pluginkit -a fails", {"failures": {("pluginkit", "-a"): (7, "", "add denied")}}, 2,
             ["exited 7: add denied"], False, False, []),
            ("the worktree add fails before it writes", {"add_fails": "before"}, 2,
             ["worktree add --detach {worktree} origin/main exited 128"], False, False, []),
            ("the worktree add fails after it registers the worktree", {"add_fails": "after"}, 2,
             ["worktree add --detach {worktree} origin/main exited 128"], False, False, []),
            ("the worktree removal fails",
             {"failures": {("git", "-C", "{repo}", "worktree", "remove"): (128, "", "fatal: busy")}}, 2,
             ["worktree remove --force {worktree} exited 128: fatal: busy"], True, False, [remove]),
            ("the worktree removal cannot start", {"missing": {("git", "-C", "{repo}", "worktree", "remove")}}, 2,
             ["worktree remove --force {worktree}: [Errno 2] No such file or directory"], True, False, [remove]),
        ]
        for name, changes, expected_code, errors, kept, registered, repairs in rows:
            with self.subTest(name):
                mac = self.new_mac()

                def command(prefix):
                    return tuple(part.format(repo=mac.repo, lsregister=bql.LSREGISTER) for part in prefix)
                for attribute, value in changes.items():
                    if attribute == "failures":
                        value = {command(prefix): failure for prefix, failure in value.items()}
                    elif attribute in ("hangs", "missing"):
                        value = set(map(command, value))
                    setattr(mac, attribute, value)
                code, result = run_bql("install", "--main", **mac.stubs())
                worktree = self.worktree(mac)
                paths = {"build": worktree / bql.BUILD.relative_to(bql.REPO), "worktree": worktree, "repo": mac.repo,
                         "lsregister": bql.LSREGISTER}
                self.assertEqual((code, result["ok"], worktree.exists(), str(paths["build"]) in mac.registered),
                                 (expected_code, False, kept, registered))
                self.assertEqual([error.format(**paths) in result["error"] for error in errors],
                                 [True] * len(errors), result["error"])
                self.assertEqual([f"Run `{repair.format(**paths)}`." in result["fix"] for repair in repairs],
                                 [True] * len(repairs), result["fix"])
                if kept:
                    self.assertEqual(result["steps"][-1], "verify")


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


POLLERS = {"bql": {"wait_for", "wait_for_new_crashes"}, "vm": {"cmd_up", "cmd_watch"}}


def fixed_sleeps(name, source):
    lines, problems = source.splitlines(), []

    def visit(node, function):
        if isinstance(node, ast.FunctionDef):
            if node.name in POLLERS[name]:
                return
            function = node.name
        if (isinstance(node, ast.Call) and ast.unparse(node.func) == "time.sleep"
                and ast.unparse(node) != "time.sleep(settle)"
                and not re.search(r"# sleep-ok: \S", lines[node.lineno - 1])):
            problems.append(f"{name}:{node.lineno} {function} calls time.sleep. "
                            "Poll with wait_for(probe, timeout) or wait_for_new_crashes(before, since).")
        for child in ast.iter_child_nodes(node):
            visit(child, function)

    visit(ast.parse(source), "<module>")
    return problems


class SleepLintTest(unittest.TestCase):
    def test_bql_and_vm_poll_for_evidence_instead_of_sleeping(self):
        self.assertEqual(fixed_sleeps("bql", "import time\n\ndef capture():\n    time.sleep(1)\n"),
                         ["bql:4 capture calls time.sleep. "
                          "Poll with wait_for(probe, timeout) or wait_for_new_crashes(before, since)."])
        self.assertEqual([problem for name in POLLERS
                          for problem in fixed_sleeps(name, Path(__file__).with_name(name).read_text())], [])


if __name__ == "__main__":
    unittest.main()
