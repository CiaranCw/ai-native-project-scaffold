"""Windows install-tree swap. Public launcher only for the consumer update."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from test_consumer_installation import _copy_live_dist, _install, _run_installed

from scaffold_p5 import consumer_install
from scaffold_p5.consumer_install import _swap_existing_install


def _tree(root: Path, files: dict[str, str]) -> Path:
    if root.exists():
        shutil.rmtree(root)
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


class WindowsInstallSwapTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._retry = consumer_install.INSTALL_SWAP_RETRY_SECONDS
        consumer_install.INSTALL_SWAP_RETRY_SECONDS = 0.4

    def tearDown(self):
        consumer_install.INSTALL_SWAP_RETRY_SECONDS = self._retry
        self._tmp.cleanup()

    def test_open_unchanged_file_updates_without_renaming_directory(self):
        install = _tree(
            self.root / ".scaffold" / "install",
            {"a.txt": "same\n", "b.txt": "old\n"},
        )
        staging = _tree(
            self.root / ".scaffold" / "install.staging-t" / "install",
            {"a.txt": "same\n", "b.txt": "new\n"},
        )
        before = install.stat().st_ino
        held = open(install / "a.txt", "rb")
        try:
            _swap_existing_install(install, staging, "install.staging-t")
        finally:
            held.close()
        self.assertEqual(install.stat().st_ino, before)
        self.assertEqual((install / "b.txt").read_text(encoding="utf-8"), "new\n")
        self.assertEqual((install / "a.txt").read_text(encoding="utf-8"), "same\n")
        self.assertFalse((self.root / ".scaffold" / "install.keep-install.staging-t").exists())
        self.assertFalse((self.root / ".scaffold" / "install.bak-install.staging-t").exists())

    def test_open_changed_file_rolls_back_and_keeps_previous_tree(self):
        install = _tree(
            self.root / ".scaffold" / "install",
            {"a.txt": "old-a\n", "b.txt": "old-b\n"},
        )
        staging = _tree(
            self.root / ".scaffold" / "install.staging-t" / "install",
            {"a.txt": "new-a\n", "b.txt": "new-b\n"},
        )
        held = open(install / "b.txt", "rb")
        try:
            with self.assertRaises(OSError) as caught:
                _swap_existing_install(install, staging, "install.staging-t")
            self.assertIn(getattr(caught.exception, "winerror", None), {5, 32})
        finally:
            held.close()
        self.assertEqual((install / "a.txt").read_text(encoding="utf-8"), "old-a\n")
        self.assertEqual((install / "b.txt").read_text(encoding="utf-8"), "old-b\n")
        self.assertFalse(any(self.root.joinpath(".scaffold").glob("install.keep-*")))
        self.assertFalse(any(self.root.joinpath(".scaffold").glob("install.bak-*")))

    def test_released_file_still_completes_swap(self):
        install = _tree(
            self.root / ".scaffold" / "install",
            {"a.txt": "old\n"},
        )
        staging = _tree(
            self.root / ".scaffold" / "install.staging-t" / "install",
            {"a.txt": "new\n"},
        )
        held = open(install / "a.txt", "rb")

        def _release() -> None:
            time.sleep(0.15)
            held.close()

        threading.Thread(target=_release).start()
        _swap_existing_install(install, staging, "install.staging-t")
        self.assertEqual((install / "a.txt").read_text(encoding="utf-8"), "new\n")


class WindowsPublicUpdateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.host = self.root / "host"
        self.host.mkdir()
        (self.host / "README.md").write_text("# host\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_public_update_installs_n1_and_preserves_authority(self):
        dist_n = _copy_live_dist(self.root / "dist-n")
        dist_n1 = _copy_live_dist(self.root / "dist-n1")
        entry = dist_n1 / "src" / "scaffold_entry.py"
        entry.write_text(
            entry.read_text(encoding="utf-8") + "\n# n1-swap-marker\n",
            encoding="utf-8",
            newline="\n",
        )
        plan, installed = _install(self.host, dist=dist_n)
        self.assertTrue(plan.allowed, plan.blockers)
        self.assertEqual(installed.get("outcome"), "COMPLETED", installed)
        lock = self.host / ".scaffold" / "skills.lock"
        task = self.host / ".scaffold" / "tasks" / "kept.yaml"
        product = self.host / "src" / "app.py"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("lock-bytes\n", encoding="utf-8")
        task.parent.mkdir(parents=True, exist_ok=True)
        task.write_text("task-bytes\n", encoding="utf-8")
        product.parent.mkdir(parents=True, exist_ok=True)
        product.write_text("value = 1\n", encoding="utf-8")

        proc = _run_installed(
            self.host,
            "consumer",
            "update",
            "--distribution",
            str(dist_n1),
        )
        payload = json.loads(proc.stdout or "{}")
        self.assertEqual(payload.get("outcome"), "COMPLETED", payload)
        self.assertEqual(payload.get("verify", {}).get("status"), "VALID", payload)
        runtime = (
            self.host / ".scaffold" / "install" / "runtime" / "scaffold_entry.py"
        ).read_text(encoding="utf-8")
        self.assertIn("n1-swap-marker", runtime)
        self.assertEqual(lock.read_text(encoding="utf-8"), "lock-bytes\n")
        self.assertEqual(task.read_text(encoding="utf-8"), "task-bytes\n")
        self.assertEqual(product.read_text(encoding="utf-8"), "value = 1\n")
        verify = _run_installed(self.host, "verify")
        self.assertEqual(verify.returncode, 0, verify.stderr)
        self.assertIn("VALID", verify.stdout)

    def test_public_update_refuses_open_changed_file_without_claiming_n1(self):
        dist_n = _copy_live_dist(self.root / "dist-n")
        dist_n1 = _copy_live_dist(self.root / "dist-n1")
        entry = dist_n1 / "src" / "scaffold_entry.py"
        entry.write_text(
            entry.read_text(encoding="utf-8") + "\n# n1-swap-marker\n",
            encoding="utf-8",
            newline="\n",
        )
        plan, installed = _install(self.host, dist=dist_n)
        self.assertTrue(plan.allowed, plan.blockers)
        self.assertEqual(installed.get("outcome"), "COMPLETED", installed)
        target = (
            self.host / ".scaffold" / "install" / "runtime" / "scaffold_entry.py"
        )
        before = target.read_bytes()
        lock = self.host / ".scaffold" / "skills.lock"
        task = self.host / ".scaffold" / "tasks" / "kept.yaml"
        product = self.host / "src" / "app.py"
        lock.write_text("lock-bytes\n", encoding="utf-8")
        task.parent.mkdir(parents=True, exist_ok=True)
        task.write_text("task-bytes\n", encoding="utf-8")
        product.parent.mkdir(parents=True, exist_ok=True)
        product.write_text("value = 1\n", encoding="utf-8")
        manifest = (self.host / ".scaffold" / "install" / "install.yaml").read_bytes()
        holder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import sys,time; f=open(sys.argv[1],'rb'); time.sleep(60); f.close()",
                str(target),
            ]
        )
        try:
            proc = _run_installed(
                self.host,
                "consumer",
                "update",
                "--distribution",
                str(dist_n1),
            )
        finally:
            holder.kill()
            holder.wait(timeout=10)
        payload = json.loads(proc.stdout or "{}")
        self.assertEqual(payload.get("outcome"), "FAILED", payload)
        self.assertNotEqual(payload.get("verify", {}).get("status"), "VALID")
        self.assertEqual(target.read_bytes(), before)
        self.assertNotIn("n1-swap-marker", target.read_text(encoding="utf-8"))
        self.assertEqual(
            (self.host / ".scaffold" / "install" / "install.yaml").read_bytes(),
            manifest,
        )
        self.assertEqual(lock.read_text(encoding="utf-8"), "lock-bytes\n")
        self.assertEqual(task.read_text(encoding="utf-8"), "task-bytes\n")
        self.assertEqual(product.read_text(encoding="utf-8"), "value = 1\n")
        self.assertFalse(any((self.host / ".scaffold").glob("install.keep-*")))
        self.assertFalse(any((self.host / ".scaffold").glob("install.bak-*")))


if __name__ == "__main__":
    unittest.main()
