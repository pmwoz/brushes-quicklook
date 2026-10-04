import importlib.machinery
import importlib.util
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
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
    run) printf '%s\\n' '{LIMIT}' >&2; exit 1 ;;
    exec) shift; printf '%s\\n' "$@" > "$FAKE_ARGV"; printf '%s' "$FAKE_STDOUT"; exit 1 ;;
esac
""")
        tart.chmod(0o755)
        self.work = Path(tmp.name) / "work"
        return {**os.environ, "PATH": f"{tmp.name}:{os.environ['PATH']}"}

    def test_up_fails_at_once_with_tarts_error_and_the_running_vms_when_tart_run_exits(self):
        env = self.fake_tart("stopped")
        stdout = io.StringIO()
        started = time.time()
        with mock.patch.dict(os.environ, env), mock.patch.object(vm, "WORK", self.work), \
                mock.patch.object(sys, "argv", ["vm", "up"]), redirect_stdout(stdout), redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit) as exit:
            vm.main()
        result = json.loads(stdout.getvalue())
        self.assertEqual(exit.exception.code, 1)
        self.assertLess(time.time() - started, 10)
        self.assertIn(LIMIT, result["error"])
        self.assertEqual(result["running_vms"], ["abr-verify", "bql-exp"])
        self.assertIn("tart stop", result["fix"])

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


class GuestAutomationTest(unittest.TestCase):
    """Runs the guest half of `vm up` on this Mac against a temporary TCC database."""

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
                grant = subprocess.Popen(["/bin/zsh", "-c", 'sh -c "$1"; exit $?', "zsh", vm.GUEST_AUTOMATION],
                                         env={**os.environ, "HOME": home}, stderr=subprocess.PIPE, text=True)
                if attempt == 0:
                    time.sleep(1)
                    tccd.execute("COMMIT")
                self.assertEqual(grant.wait(timeout=30), 0, grant.stderr.read())
            rows = tccd.execute("SELECT service, client, client_type, auth_value, indirect_object_identifier "
                                "FROM access ORDER BY indirect_object_identifier").fetchall()
        self.assertEqual(rows, [("kTCCServiceAppleEvents", "/bin/zsh", 1, 2, "com.apple.finder"),
                                ("kTCCServiceAppleEvents", "/bin/zsh", 1, 2, "com.apple.systemevents")])


if __name__ == "__main__":
    unittest.main()
