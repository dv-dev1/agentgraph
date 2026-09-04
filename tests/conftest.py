import socket
import subprocess
import sys
import time

import pytest

ROOT = __file__.rsplit("/tests/", 1)[0]
ENV = {"PYTHONPATH": ROOT, "PATH": "/usr/bin:/bin"}


def cli(workdir, *args):
    return subprocess.run(
        [sys.executable, "-m", "demo.cli", *args],
        cwd=workdir, env=ENV, capture_output=True, text=True,
    )


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def server(tmp_path):
    """A paused thread and an inbox serving it. Yields (port, workdir)."""
    workdir = str(tmp_path)
    cli(workdir, "run", "--application", "A-1042", "--thread", "f3a1")

    port = free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "demo.inbox", "--port", str(port)],
        cwd=workdir, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.05)
    else:
        process.kill()
        pytest.fail("the inbox never came up")

    yield port, workdir
    process.kill()
