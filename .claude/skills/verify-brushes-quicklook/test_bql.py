import importlib.machinery
import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
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

    def wait(self, on_tick):
        clock = FakeClock(self.START, on_tick)
        with mock.patch.object(bql, "time", clock):
            before = bql.crash_reports()
            crashes, capped, vanished = bql.wait_for_new_crashes(before, clock.now)
        return clock.now - self.START, capped, crashes, vanished

    def test_reports_from_before_the_run_do_not_restart_the_quiet_window(self):
        self.assertEqual(self.wait(lambda now: self.write_report(self.START - 3600)), (30, False, [], set()))

    def test_reports_present_before_the_wait_are_not_returned(self):
        # A captureTime inside the run passes the time filter, so only the before filter can drop this report.
        self.write_report(self.START + 5)
        (self.dir / "BrushesThumbnail-unreadable.ips").write_text("{}")
        self.assertEqual(self.wait(lambda now: None), (30, False, [], set()))

    def test_deleted_reports_do_not_restart_the_quiet_window(self):
        for _ in range(20):
            self.write_report(self.START - 3600)
        self.assertEqual(self.wait(lambda now: self.written.pop().unlink()), (30, False, [], set()))

    def test_one_report_from_the_run_restarts_the_quiet_window_once(self):
        elapsed, capped, crashes, _ = self.wait(lambda now: self.written or self.write_report(now))
        self.assertEqual((elapsed, capped), (40, False))
        self.assertEqual([crash["report"] for crash in crashes], [str(self.written[0])])

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

    def doctor(self, installed=True, built=True, mismatched=None, unregistered=None, other_copy=False):
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
            if args[0] == bql.LSREGISTER and other_copy:
                return SimpleNamespace(stdout=f"    path:    {base}/Other/BrushesQuickLook.app (0x1)\n")
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
        rows += [
            (hostile, "crash reports from this run: 1",
             {"wait_for_new_crashes": crashed, "render_thumbnail": thumbnails(), "drive_previews": previews()}),
            (hostile, "Reports kept arriving",
             {"wait_for_new_crashes": capped, "render_thumbnail": thumbnails(), "drive_previews": previews()}),
            (hostile, "2 of 2 files were not exercised",
             {"wait_for_new_crashes": quiet, "render_thumbnail": thumbnails(png=False), "drive_previews": previews()}),
            (hostile, "2 of 2 files were not exercised",
             {"wait_for_new_crashes": quiet, "render_thumbnail": thumbnails(),
              "drive_previews": previews("no window")}),
            (hostile, "above the limit of 1",
             {"wait_for_new_crashes": quiet, "render_thumbnail": thumbnails(), "drive_previews": previews(attempts=2)}),
            (("doctor",), "installed failed", self.doctor(installed=False)),
            (("doctor",), "release-build failed", self.doctor(built=False)),
        ]
        rows += [(("doctor",), f"cdhash-{kind} failed", self.doctor(mismatched=kind))
                 for kind in ("app", "preview", "thumbnail")]
        rows += [(("doctor",), f"pluginkit-{kind} failed", self.doctor(unregistered=kind)) for kind in bql.PLUGINS]
        for argv, error, stubs in rows:
            with self.subTest(command=argv[0], error=error):
                code, result = run_bql(*argv, **self.stubs, **stubs)
                self.assertEqual((code, result["ok"], bool(result.get("fix"))), (1, False, True))
                self.assertIn(error, result.get("error", ""))

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
             {"wait_for_new_crashes": crash_wait(), "render_thumbnail": thumbnails(), "drive_previews": previews()}),
        ]:
            with self.subTest(command=argv[0]):
                code, result = run_bql(*argv, **self.stubs, **stubs)
                self.assertEqual((code, result["ok"], "error" in result, "fix" in result), (0, True, False, False))

    def test_a_doctor_warning_does_not_fail_the_run(self):
        code, result = run_bql("doctor", **self.doctor(other_copy=True))
        self.assertEqual((code, result["ok"], "error" in result, "fix" in result), (0, True, False, False))
        self.assertIn("warn", [check["status"] for check in result["checks"]])

    def test_a_missing_file_exits_2_with_error_and_fix(self):
        code, result = run_bql("thumb", self.dir / "missing.abr")
        self.assertEqual((code, result["ok"], bool(result.get("fix"))), (2, False, True))
        self.assertIn("does not exist", result["error"])

    def test_an_unexpected_exception_exits_2_with_error_and_fix(self):
        code, result = run_bql("thumb", self.brush, new_run=mock.Mock(side_effect=TimeoutError("hung")))
        self.assertEqual((code, result["ok"], bool(result.get("error")), bool(result.get("fix"))),
                         (2, False, True, True))


if __name__ == "__main__":
    unittest.main()
