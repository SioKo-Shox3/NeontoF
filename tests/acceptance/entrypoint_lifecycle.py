"""Windows実測専用のUvicorn health / graceful lifecycle probe。"""

import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HEALTH_BODY = b'{"status":"ok"}'
WAIT_SECONDS = 10.0


def _wait_for_health(port: int, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("server exited before health became available")
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                body = response.read()
                if response.status != 200 or body != HEALTH_BODY:
                    raise RuntimeError("health response did not match the contract")
                return
        except OSError, TimeoutError, urllib.error.URLError:
            time.sleep(0.25)
    raise TimeoutError("health response timeout")


def _stop_gracefully(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        raise RuntimeError("server exited before CTRL_BREAK_EVENT")
    process.send_signal(signal.CTRL_BREAK_EVENT)
    try:
        exit_code = process.wait(timeout=WAIT_SECONDS)
    except subprocess.TimeoutExpired as error:
        raise TimeoutError("graceful shutdown timeout") from error
    if exit_code != 0:
        raise RuntimeError(f"unexpected graceful exit code: {exit_code}")
    if process.poll() is None:
        raise RuntimeError("server PID remained alive after graceful shutdown")


def _run_once(
    python_executable: str,
    repository_root: Path,
    port: int,
    stdout_path: Path,
    stderr_path: Path,
) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repository_root / "src")
    arguments = [
        python_executable,
        "-m",
        "neontof.main",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--workers",
        "1",
    ]

    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(
            arguments,
            cwd=repository_root,
            env=environment,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            stdout=stdout,
            stderr=stderr,
        )
        try:
            _wait_for_health(port, process)
            _stop_gracefully(process)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=WAIT_SECONDS)

    if stdout_path.read_bytes() != b"":
        raise RuntimeError(f"server stdout was not empty: {stdout_path}")
    if stderr_path.read_bytes() != b"":
        raise RuntimeError(f"server stderr was not empty: {stderr_path}")


def run_probe() -> None:
    """同一portの二回の起動、health、graceful exit、空出力、再bindを検証する。"""

    if sys.platform != "win32":
        raise RuntimeError("entrypoint lifecycle probe requires a Windows measurement")

    repository_root = Path(__file__).resolve().parents[2]
    port = 18765
    python_executable = sys.executable
    with tempfile.TemporaryDirectory(prefix="neontof-p0-entry-") as temporary_root:
        probe_root = Path(temporary_root)
        _run_once(
            python_executable,
            repository_root,
            port,
            probe_root / "stdout.txt",
            probe_root / "stderr.txt",
        )
        _run_once(
            python_executable,
            repository_root,
            port,
            probe_root / "stdout-rebind.txt",
            probe_root / "stderr-rebind.txt",
        )


def main() -> int:
    run_probe()
    print("entrypoint_lifecycle=graceful_exit_0_rebind_health_200")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
