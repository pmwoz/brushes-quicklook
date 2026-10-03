import importlib.machinery
import importlib.util
import io
import json
import os
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

    def doctor(self, installed=True, built=True, mismatched=None, unregistered=None, other_copy=False, previews=None):
        """previews maps a BrushesPreview pid to (root, codesign -v error or None, alive).
        root is "app", "build", "other" or None for a process that exited."""
        previews = previews or {}
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
                return SimpleNamespace(stdout="\n".join(previews) if args[-1] == bql.PLUGINS["preview"] else "")
            if args[0] == "ps":
                root = {"app": app, "build": build, "other": base / "Other.app"}.get(previews[args[-1]][0])
                executable = "Contents/PlugIns/BrushesPreview.appex/Contents/MacOS/BrushesPreview"
                return SimpleNamespace(stdout=f"{root}/{executable}\n" if root else "")
            if args[0] == "codesign":
                error = previews[args[-1]][1]
                return SimpleNamespace(returncode=1 if error else 0, stderr=f"{error}\n" if error else "")
            if args[0] == "kill":
                return SimpleNamespace(returncode=0 if previews[args[-1]][2] else 1)
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


if __name__ == "__main__":
    unittest.main()
