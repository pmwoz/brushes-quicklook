import importlib.machinery
import importlib.util
import io
import json
import os
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
    exec) shift; printf '%s\\n' "$@"; exit 3 ;;
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

    def test_run_passes_the_bql_arguments_and_bqls_exit_code_through(self):
        proc = subprocess.run([sys.executable, str(VM), "run", "thumb", "x.abr", "--size", "256"],
                              env=self.fake_tart("running"), capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 3)
        argv = proc.stdout.splitlines()
        self.assertEqual(argv[0], vm.vm_name("tahoe"))
        self.assertEqual(argv[-5:], ["sh", "thumb", "x.abr", "--size", "256"])


if __name__ == "__main__":
    unittest.main()
