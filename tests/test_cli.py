import os
import subprocess
import sys

from filelock import FileLock


def test_second_launch_does_not_reconcile_a_live_executors_database(settings):
    with FileLock(settings.data / "instance.lock", timeout=0):
        result = subprocess.run(
            [sys.executable, "-m", "drive_transfer_agent.cli", "--no-browser"],
            env={**os.environ, "DTA_DATA_DIR": str(settings.data), "PYTHONIOENCODING": "utf-8"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
    assert result.returncode == 0
    assert "instância existente" in result.stdout
    assert not (settings.data / "jobs.sqlite3").exists()
