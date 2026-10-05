import argparse
import datetime
import importlib.machinery
import importlib.util
import io
import json
import os
import plistlib
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

VM = Path(__file__).with_name("vm")
loader = importlib.machinery.SourceFileLoader("vm", str(VM))
vm = importlib.util.module_from_spec(importlib.util.spec_from_loader("vm", loader))
loader.exec_module(vm)

LIMIT = "The number of VMs exceeds the system limit (other running VMs: abr-verify, bql-exp)"


class FakeTartTest(unittest.TestCase):
    """Puts a `tart` on PATH that lists this checkout's Tahoe VM in `state` beside two running VMs of other sessions."""

    def fake_tart(self, state):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        listed = [{"Name": vm.vm_name("tahoe"), "State": state, "Source": "local"},
                  {"Name": "abr-verify", "State": "running", "Source": "local"},
                  {"Name": "bql-exp", "State": "running", "Source": "local"}]
        tart = Path(tmp.name) / "tart"
        tart.write_text(f"""#!/bin/sh
case $1 in
    list) printf '%s\\n' '{json.dumps(listed)}' ;;
    run) printf '%s\\n' '{LIMIT}' >&2; exit ${{FAKE_RUN_EXIT:-1}} ;;
    exec) shift; printf '%s\\n' "$@" > "$FAKE_ARGV"; printf '%s' "$FAKE_STDOUT"; exit 1 ;;
esac
""")
        tart.chmod(0o755)
        self.work = Path(tmp.name) / "work"
        return {**os.environ, "PATH": f"{tmp.name}:{os.environ['PATH']}"}

    def up_with_a_vm_that_tart_run_cannot_boot(self, run_exit):
        env = {**self.fake_tart("stopped"), "FAKE_RUN_EXIT": run_exit}
        stdout = io.StringIO()
        started = time.time()
        with mock.patch.dict(os.environ, env), mock.patch.object(vm, "WORK", self.work), \
                mock.patch.object(sys, "argv", ["vm", "up"]), redirect_stdout(stdout), redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit) as exit:
            vm.main()
        self.assertEqual(exit.exception.code, 1)
        self.assertLess(time.time() - started, 10)
        return json.loads(stdout.getvalue())

    def test_up_fails_at_once_with_tarts_error_and_the_running_vms_when_tart_run_exits(self):
        result = self.up_with_a_vm_that_tart_run_cannot_boot("1")
        self.assertIn(LIMIT, result["error"])
        self.assertEqual(result["running_vms"], ["abr-verify", "bql-exp"])
        self.assertIn("tart stop", result["fix"])

    def test_up_fails_at_once_when_tart_run_exits_0_during_the_boot(self):
        self.assertIn("The watcher exited 0", self.up_with_a_vm_that_tart_run_cannot_boot("0")["error"])

    def run_vm(self, stdout):
        env = {**self.fake_tart("running"), "FAKE_ARGV": str(self.work.parent / "argv"), "FAKE_STDOUT": stdout}
        proc = subprocess.run([sys.executable, str(VM), "run", "thumb", "x.abr", "--size", "256"],
                              env=env, capture_output=True, text=True, timeout=30)
        return proc, (self.work.parent / "argv").read_text().splitlines()

    def test_run_passes_the_bql_arguments_json_and_exit_code_through(self):
        proc, argv = self.run_vm('{"ok": false}')
        self.assertEqual((proc.returncode, proc.stdout), (1, '{"ok": false}'))
        self.assertEqual(argv[0], vm.vm_name("tahoe"))
        self.assertEqual(argv[-4:], ["thumb", "x.abr", "--size", "256"])

    def test_run_exits_2_with_json_when_bql_did_not_run_in_the_guest(self):
        proc, _ = self.run_vm("")
        result = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("without bql's JSON", result["error"])


class IdleStopTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        repo = mock.patch.object(vm, "REPO", self.root)
        repo.start()
        self.addCleanup(repo.stop)
        self.stopped = self.root / "stopped"
        self.tart = self.root / "tart"
        listed = {state: json.dumps([{"Name": vm.vm_name("tahoe"), "State": state, "Source": "local"}])
                  for state in ("running", "stopped")}
        self.tart.write_text(f"""#!/bin/sh
case $1 in
    list) if [ -e "$FAKE_STOPPED.booted" ] && [ ! -e "$FAKE_STOPPED" ]; then printf '%s\\n' '{listed["running"]}'
          else printf '%s\\n' '{listed["stopped"]}'; fi ;;
    run) echo $$ > "$FAKE_STOPPED.pid"; mv "$FAKE_STOPPED.pid" "$FAKE_STOPPED.booted"
         test_dir=${{FAKE_STOPPED%/*}}
         while [ ! -e "$FAKE_STOPPED" ] && [ -d "$test_dir" ]; do sleep 0.1; done ;;
    exec) printf '{{}}' ;;
    stop) touch "$FAKE_STOPPED" ;;
esac
""")
        self.tart.chmod(0o755)
        self.env = {**os.environ, "PATH": f"{tmp.name}:{os.environ['PATH']}", "FAKE_STOPPED": str(self.stopped)}

    def vm(self, idle, *argv, exec_limit=60):
        with mock.patch.dict(os.environ, self.env), mock.patch.object(vm, "IDLE_SECONDS", idle), \
                mock.patch.object(vm, "EXEC_SECONDS", exec_limit), \
                mock.patch.object(vm, "WORK", self.root / "work"), mock.patch.object(sys, "argv", ["vm", *argv]), \
                redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit) as exit:
            vm.main()
        self.assertEqual(exit.exception.code, 0, stdout.getvalue())

    def tart_run_pid(self):
        booted = Path(f"{self.stopped}.booted")
        deadline = time.time() + 20
        while not booted.exists():
            self.assertLess(time.time(), deadline, "tart run did not start within 20 s")
            time.sleep(0.05)
        return int(booted.read_text())

    def stop_time(self):
        deadline = time.time() + 20
        while not self.stopped.exists():
            self.assertLess(time.time(), deadline, "the VM still runs 20 s after its idle time")
            time.sleep(0.1)
        return self.stopped.stat().st_mtime

    def test_a_vm_that_nothing_uses_stops_by_itself_after_vm_up_returned(self):
        booted = time.time()
        self.vm(1, "up")
        self.assertGreaterEqual(self.stop_time() - booted, 1)
        log = (self.root / "work/vm" / vm.vm_name("tahoe") / "tart-run.log").read_text()
        self.assertIn("without use", log)

    def test_a_vm_whose_checkout_was_removed_still_stops_after_the_idle_time(self):
        booted = time.time()
        self.vm(1, "up")
        (self.root / "work/vm" / vm.vm_name("tahoe") / "used").unlink()
        self.assertGreaterEqual(self.stop_time() - booted, 1)
        log = (self.root / "work/vm" / vm.vm_name("tahoe") / "tart-run.log").read_text()
        self.assertIn("without use", log)

    def test_every_vm_command_starts_the_idle_time_again(self):
        self.vm(3, "up")
        time.sleep(1.5)
        used = time.time()
        self.vm(3, "run", "doctor")
        self.assertGreaterEqual(self.stop_time() - used, 3)

    def test_a_live_tart_exec_into_the_vm_keeps_it_running(self):
        self.vm(1, "up")
        (self.root / "exec").write_text("sleep 3\n")
        started = time.time()
        # sh runs the script `exec` under argv[0] `tart`, so ps lists it like a real `tart exec <vm>`.
        subprocess.run(["tart", "exec", vm.vm_name("tahoe")], executable="/bin/sh", cwd=self.root, check=True)
        self.assertGreaterEqual(self.stop_time() - started, 3)

    def test_a_tart_exec_that_never_returns_stops_counting_as_use(self):
        self.vm(1, "up", exec_limit=2)
        (self.root / "exec").write_text("sleep 30\n")
        started = time.time()
        hung = subprocess.Popen(["tart", "exec", vm.vm_name("tahoe")], executable="/bin/sh", cwd=self.root)
        self.addCleanup(hung.wait)
        self.addCleanup(hung.kill)
        self.assertGreaterEqual(self.stop_time() - started, 3)
        self.assertIsNone(hung.poll())

    def test_a_vm_sync_keeps_the_vm_up_through_a_host_build_longer_than_the_idle_time(self):
        build = self.root / "build.noindex/Build/Products/Release/BrushesQuickLook.app"
        build.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.vm(3, "up")
        self.tart_run_pid()
        with mock.patch.object(vm, "HOST_BUILD", [["sh", "-c", 'sleep 6; test ! -e "$FAKE_STOPPED"']]), \
                mock.patch.object(vm, "BUILD", build), mock.patch.object(vm.bql, "LSREGISTER", "true"):
            self.vm(3, "sync")
        synced = time.time()
        self.assertLess(self.stop_time() - synced, 10)

    def test_a_watcher_stopped_with_sigterm_ends_the_vm_it_runs(self):
        self.vm(60, "up")
        tart = self.tart_run_pid()
        watcher = int(subprocess.run(["ps", "-o", "ppid=", "-p", str(tart)], capture_output=True, text=True,
                                     check=True).stdout)
        os.kill(watcher, signal.SIGTERM)
        deadline = time.time() + 10
        while subprocess.run(["ps", "-p", str(tart)], capture_output=True).returncode == 0:
            self.assertLess(time.time(), deadline, "tart run still runs 10 s after its watcher got SIGTERM")
            time.sleep(0.1)

    def test_vm_up_puts_a_vm_whose_watcher_got_kill_9_back_under_the_idle_stop(self):
        self.vm(60, "up")
        tart = self.tart_run_pid()
        watcher = int(subprocess.run(["ps", "-o", "ppid=", "-p", str(tart)], capture_output=True, text=True,
                                     check=True).stdout)
        os.kill(watcher, signal.SIGKILL)
        up = time.time()
        self.vm(1, "up")
        self.assertGreaterEqual(self.stop_time() - up, 1)

    def test_a_second_watcher_on_a_watched_vm_neither_runs_nor_stops_it(self):
        self.vm(60, "up")
        tart = self.tart_run_pid()
        outcomes = {}

        def watch(adopt):
            args = argparse.Namespace(vm=vm.vm_name("tahoe"), used=self.root / "work/vm" / vm.vm_name("tahoe") / "used",
                                      idle=60, exec_limit=60, adopt=adopt)
            try:
                vm.cmd_watch(args)
                outcomes[adopt] = "returned"
            except vm.Fail as failure:
                outcomes[adopt] = failure.error

        with mock.patch.dict(os.environ, self.env), mock.patch.object(vm, "LOCK_SECONDS", 1), \
                mock.patch.object(signal, "signal"):
            for adopt in (True, False):
                watcher = threading.Thread(target=watch, args=(adopt,), daemon=True)
                watcher.start()
                watcher.join(5)
        self.assertEqual(outcomes, {True: "returned", False: f"Another `vm watch` has {vm.vm_name('tahoe')}"})
        self.assertEqual(int(Path(f"{self.stopped}.booted").read_text()), tart)
        self.assertFalse(self.stopped.exists())

    def test_a_watcher_that_fails_ends_the_vm_it_runs(self):
        booted = Path(f"{self.stopped}.booted")

        def ps_fails(*_):
            while not booted.exists():
                time.sleep(0.05)
            raise OSError("ps failed")

        args = argparse.Namespace(vm=vm.vm_name("tahoe"), used=self.root / "used", idle=60, exec_limit=60,
                                  adopt=False)
        with mock.patch.dict(os.environ, self.env), mock.patch.object(vm, "run", ps_fails), \
                self.assertRaises(OSError):
            vm.cmd_watch(args)
        with self.assertRaises(ProcessLookupError):
            os.kill(int(booted.read_text()), 0)


class GuestSyncTest(unittest.TestCase):
    """Runs the guest half of `vm sync` on this Mac against a temporary guest checkout."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.repo = self.root / "guest/brushes-quicklook"
        source = self.root / "host"
        (source / "scripts").mkdir(parents=True)
        (source / "scripts/install.sh").write_text("new")
        self.archive = self.root / "checkout.tar"
        subprocess.run(["tar", "-c", "-f", str(self.archive), "-C", str(source), "scripts"], check=True)

    def sync(self):
        with self.archive.open("rb") as stdin:
            subprocess.run(["sh", "-c", vm.GUEST_SYNC, "sh", str(self.repo)], stdin=stdin, check=True,
                           capture_output=True)

    def test_a_sync_replaces_the_checkout_and_keeps_bqls_state_and_evidence(self):
        (self.repo / "build.noindex/verify/evidence/run").mkdir(parents=True)
        (self.repo / "deleted-on-host").write_text("old")
        self.sync()
        self.assertEqual((self.repo / "scripts/install.sh").read_text(), "new")
        self.assertFalse((self.repo / "deleted-on-host").exists())
        self.assertTrue((self.repo / "build.noindex/verify/evidence/run").is_dir())
        self.assertIn("scripts/install.sh", subprocess.run(["git", "-C", str(self.repo), "ls-files"],
                                                           capture_output=True, text=True).stdout)

    def test_a_sync_after_one_interrupted_past_the_state_move_keeps_bqls_state_and_evidence(self):
        (self.root / "guest/brushes-quicklook.new/build.noindex/verify/evidence/run").mkdir(parents=True)
        self.sync()
        self.assertTrue((self.repo / "build.noindex/verify/evidence/run").is_dir())
        self.assertFalse((self.root / "guest/brushes-quicklook.new").exists())


# The `access` table of the user TCC.db in the macos-tahoe-base and macos-sonoma-base guests.
TCC_ACCESS = """CREATE TABLE access (    service        TEXT        NOT NULL,     client         TEXT        NOT NULL,
    client_type    INTEGER     NOT NULL,     auth_value     INTEGER     NOT NULL,
    auth_reason    INTEGER     NOT NULL,     auth_version   INTEGER     NOT NULL,     csreq          BLOB,
    policy_id      INTEGER,
    indirect_object_identifier_type    INTEGER,     indirect_object_identifier         TEXT NOT NULL DEFAULT 'UNUSED',
    indirect_object_code_identity      BLOB,     flags          INTEGER,
    last_modified  INTEGER     NOT NULL DEFAULT (CAST(strftime('%s','now') AS INTEGER)),     pid            INTEGER,
    pid_version    INTEGER,     boot_uuid      TEXT NOT NULL DEFAULT 'UNUSED',
    last_reminded  INTEGER     NOT NULL DEFAULT (CAST(strftime('%s','now') AS INTEGER)),
    PRIMARY KEY (service, client, client_type, indirect_object_identifier),
    FOREIGN KEY (policy_id) REFERENCES policies(id) ON DELETE CASCADE ON UPDATE CASCADE)"""


class GuestGrantsTest(unittest.TestCase):
    """Runs the guest half of `vm up` on this Mac against a temporary home."""

    def test_its_parent_gets_automation_for_finder_and_system_events_once_while_tccd_holds_a_lock(self):
        with tempfile.TemporaryDirectory() as home:
            db = Path(home, "Library/Application Support/com.apple.TCC/TCC.db")
            db.parent.mkdir(parents=True)
            tccd = sqlite3.connect(db, isolation_level=None)
            self.addCleanup(tccd.close)
            tccd.execute(TCC_ACCESS)
            for attempt in range(2):
                if attempt == 0:
                    tccd.execute("BEGIN EXCLUSIVE")
                # zsh stands in for the guest agent. The trailing command keeps zsh from exec'ing sh in its place.
                grant = subprocess.Popen(["/bin/zsh", "-c", 'sh -c "$1"; exit $?', "zsh", vm.GUEST_GRANTS],
                                         env={**os.environ, "HOME": home}, stderr=subprocess.PIPE, text=True)
                if attempt == 0:
                    time.sleep(1)
                    tccd.execute("COMMIT")
                self.assertEqual(grant.wait(timeout=30), 0, grant.stderr.read())
            rows = tccd.execute("SELECT service, client, client_type, auth_value, indirect_object_identifier "
                                "FROM access ORDER BY indirect_object_identifier").fetchall()
        self.assertEqual(rows, [("kTCCServiceAppleEvents", "/bin/zsh", 1, 2, "com.apple.finder"),
                                ("kTCCServiceAppleEvents", "/bin/zsh", 1, 2, "com.apple.systemevents")])

    def test_its_parent_gets_a_recent_screen_capture_approval_that_keeps_other_entries_when_tcc_fails(self):
        with tempfile.TemporaryDirectory() as home:
            approvals = Path(home, "Library/Group Containers/group.com.apple.replayd/ScreenCaptureApprovals.plist")
            approvals.parent.mkdir(parents=True)
            old = datetime.datetime(2026, 1, 1)
            approvals.write_bytes(plistlib.dumps({"/bin/zsh": {"kScreenCaptureAlertableUsageCount": 2},
                                                  "/usr/bin/other": {"kScreenCaptureApprovalLastUsed": old}}))
            # No TCC database exists, so the Automation grant fails after the approval is written.
            grant = subprocess.run(["/bin/zsh", "-c", 'sh -c "$1"; exit $?', "zsh", vm.GUEST_GRANTS],
                                   env={**os.environ, "HOME": home}, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(grant.returncode, 0)
            entries = plistlib.loads(approvals.read_bytes())
        self.assertEqual(entries["/usr/bin/other"], {"kScreenCaptureApprovalLastUsed": old})
        self.assertEqual(entries["/bin/zsh"]["kScreenCaptureAlertableUsageCount"], 2)
        last_used = entries["/bin/zsh"]["kScreenCaptureApprovalLastUsed"].replace(tzinfo=datetime.timezone.utc)
        self.assertLess(abs((datetime.datetime.now(datetime.timezone.utc) - last_used).total_seconds()), 60)

if __name__ == "__main__":
    unittest.main()
