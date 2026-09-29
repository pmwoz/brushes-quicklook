import importlib.machinery
import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
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


class ArgumentErrorTest(unittest.TestCase):
    def run_bql(self, *argv):
        stdout = io.StringIO()
        with mock.patch("sys.argv", ["bql", *argv]), redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                bql.main()
        return raised.exception.code, json.loads(stdout.getvalue())

    def test_a_subcommand_argument_error_prints_json_naming_its_help(self):
        code, result = self.run_bql("thumb")
        self.assertEqual((code, result["ok"]), (2, False))
        self.assertIn("files", result["error"])
        self.assertIn("bql thumb --help", result["fix"])

    def test_a_top_level_argument_error_prints_json_naming_its_help(self):
        code, result = self.run_bql("nope")
        self.assertEqual((code, result["ok"]), (2, False))
        self.assertIn("nope", result["error"])
        self.assertIn("bql --help", result["fix"])

    def test_an_unknown_option_after_a_subcommand_names_the_subcommand_help(self):
        code, result = self.run_bql("thumb", "x", "--bogus")
        self.assertEqual((code, result["ok"]), (2, False))
        self.assertIn("--bogus", result["error"])
        self.assertIn("bql thumb --help", result["fix"])


def thumbnails(png=True):
    return lambda file, size, scale, out: {"file": str(file), "size_pt": size, "scale": scale,
                                           **({"png": "x.png"} if png else {"png": None, "qlmanage": "no thumbnail"})}


def previews(problem=None, attempts=1):
    return lambda files, run_dir, settle, via: [{"file": str(f), "png": None if problem else "x.png", "problem": problem,
                                                 "attempts": attempts, "extension": None} for f in files]


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
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("GITHUB_STEP_SUMMARY", None)

    def doctor(self, installed=True, built=True, same_cdhash=True, registered=True):
        apps, base = {}, Path(tempfile.mkdtemp(dir=self.dir))
        for name, exists in (("installed", installed), ("built", built)):
            apps[name] = base / name / "BrushesQuickLook.app"
            if exists:
                (apps[name] / "Contents/MacOS").mkdir(parents=True)
                (apps[name] / "Contents/MacOS/BrushesQuickLook").write_bytes(b"")

        def run(args, timeout=120, check=False):
            if args[0] == "pluginkit" and registered:
                appex = f"{apps['installed']}/Contents/PlugIns/{bql.PLUGINS[args[-1].rsplit('.', 1)[1]]}.appex"
                return SimpleNamespace(stdout=f"+    {args[-1]}(1.0)\t{appex}\n")
            return SimpleNamespace(stdout="project.yml" if args[0] == "git" else "")
        return {"APP": apps["installed"], "BUILD": apps["built"], "run": run,
                "cdhash": (lambda path: "same") if same_cdhash else str}

    def run_command(self, command, stubs):
        args = {"thumb": dict(files=[str(self.brush)], size=[256], scale=1),
                "preview": dict(files=[str(self.brush)], settle=0), "finder": dict(files=[str(self.brush)], settle=0),
                "hostile": dict(paths=[str(self.brush), str(self.brush)], via="qlmanage", settle=0), "doctor": {}}
        stubs = {"new_run": lambda name: Path(tempfile.mkdtemp(dir=self.dir)), "crash_reports": dict,
                 "note": lambda message: None, **stubs}
        stdout = io.StringIO()
        with mock.patch.multiple(bql, **stubs), redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            getattr(bql, f"cmd_{command}")(SimpleNamespace(command=command, **args[command]))
        return raised.exception.code, json.loads(stdout.getvalue())

    def test_every_failed_check_exits_1_with_error_and_fix(self):
        crashed, quiet = crash_wait(crashed=True), crash_wait()
        for command, error, stubs in [
            ("thumb", "crash reports from this run: 1",
             {"wait_for_new_crashes": crashed, "render_thumbnail": thumbnails()}),
            ("thumb", "wrote no thumbnail for 1 of 1",
             {"wait_for_new_crashes": quiet, "render_thumbnail": thumbnails(png=False)}),
            ("thumb", "Reports kept arriving",
             {"wait_for_new_crashes": crash_wait(capped=True), "render_thumbnail": thumbnails()}),
            ("thumb", "restarted the crash wait",
             {"wait_for_new_crashes": crash_wait(capped=True, vanished=["BrushesPreview-1.ips"]),
              "render_thumbnail": thumbnails()}),
            ("preview", "crash reports from this run: 1", {"wait_for_new_crashes": crashed, "drive_previews": previews()}),
            ("preview", "1 of 1 previews have a problem",
             {"wait_for_new_crashes": quiet, "drive_previews": previews("no window")}),
            ("finder", "crash reports from this run: 1", {"wait_for_new_crashes": crashed, "drive_previews": previews()}),
            ("finder", "1 of 1 previews have a problem",
             {"wait_for_new_crashes": quiet, "drive_previews": previews("no panel")}),
            ("hostile", "crash reports from this run: 1",
             {"wait_for_new_crashes": crashed, "render_thumbnail": thumbnails(), "drive_previews": previews()}),
            ("hostile", "2 of 2 files were not exercised",
             {"wait_for_new_crashes": quiet, "render_thumbnail": thumbnails(png=False), "drive_previews": previews()}),
            ("hostile", "above the limit of 1",
             {"wait_for_new_crashes": quiet, "render_thumbnail": thumbnails(), "drive_previews": previews(attempts=2)}),
            ("doctor", "installed failed", self.doctor(installed=False)),
            ("doctor", "release-build failed", self.doctor(built=False)),
            ("doctor", "cdhash-app failed", self.doctor(same_cdhash=False)),
            ("doctor", "pluginkit-preview failed", self.doctor(registered=False)),
        ]:
            with self.subTest(command=command, error=error):
                code, result = self.run_command(command, stubs)
                self.assertEqual((code, result["ok"], bool(result.get("fix"))), (1, False, True))
                self.assertIn(error, result.get("error", ""))

    def test_a_clean_run_exits_0_with_neither_error_nor_fix(self):
        for command, stubs in [
            ("thumb", {"wait_for_new_crashes": crash_wait(), "render_thumbnail": thumbnails()}),
            ("preview", {"wait_for_new_crashes": crash_wait(), "drive_previews": previews()}),
            ("finder", {"wait_for_new_crashes": crash_wait(), "drive_previews": previews()}),
            ("hostile", {"wait_for_new_crashes": crash_wait(), "render_thumbnail": thumbnails(),
                         "drive_previews": previews()}),
            ("doctor", self.doctor()),
        ]:
            with self.subTest(command=command):
                code, result = self.run_command(command, stubs)
                self.assertEqual((code, result["ok"], "error" in result, "fix" in result), (0, True, False, False))

    def test_an_unexpected_exception_exits_2_with_error_and_fix(self):
        stdout = io.StringIO()
        with mock.patch("sys.argv", ["bql", "thumb", str(self.brush)]), \
                mock.patch.object(bql, "new_run", side_effect=TimeoutError("hung")), \
                redirect_stdout(stdout), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            bql.main()
        result = json.loads(stdout.getvalue())
        self.assertEqual((raised.exception.code, result["ok"], bool(result.get("error")), bool(result.get("fix"))),
                         (2, False, True, True))


if __name__ == "__main__":
    unittest.main()
