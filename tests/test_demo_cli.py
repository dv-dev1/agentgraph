"""The kill test, for real: separate operating system processes.

test_engine.py proves resuming works across objects. This proves it across
processes, which is the claim the README makes.
"""

import subprocess
import sys

import pytest

ROOT = __file__.rsplit("/tests/", 1)[0]


def cli(workdir, *args):
    return subprocess.run(
        [sys.executable, "-m", "demo.cli", *args],
        cwd=workdir,
        env={"PYTHONPATH": ROOT, "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )


@pytest.fixture
def workdir(tmp_path):
    return str(tmp_path)


def test_run_pauses_above_the_limit(workdir):
    done = cli(workdir, "run", "--application", "A-1042", "--thread", "f3a1")
    assert done.returncode == 0
    assert "PAUSED  thread=f3a1" in done.stdout
    assert "approve credit of R$ 40.000,00" in done.stdout


def test_a_second_process_finishes_the_thread(workdir):
    cli(workdir, "run", "--application", "A-1042", "--thread", "f3a1")
    done = cli(workdir, "resume", "f3a1", "approved")
    assert done.returncode == 0
    assert "credit of R$ 40.000,00 released" in done.stdout


def test_the_cycle_shows_up_in_the_output(workdir):
    done = cli(workdir, "run", "--application", "A-1042", "--thread", "f3a1")
    assert done.stdout.count("[assess]") == 2


def test_below_the_limit_it_never_pauses(workdir):
    done = cli(workdir, "run", "--application", "A-2001", "--thread", "aa02")
    assert "PAUSED" not in done.stdout
    assert "credit of R$ 3.000,00 released" in done.stdout


def test_a_low_score_is_refused_without_asking_anyone(workdir):
    done = cli(workdir, "run", "--application", "A-3300", "--thread", "bb03")
    assert "outside policy" in done.stdout
    assert "PAUSED" not in done.stdout


def test_answering_twice_fails_instead_of_releasing_twice(workdir):
    cli(workdir, "run", "--application", "A-1042", "--thread", "f3a1")
    cli(workdir, "resume", "f3a1", "approved")
    done = cli(workdir, "resume", "f3a1", "approved")
    assert done.returncode == 1
    assert "ERROR: thread f3a1 is not paused" in done.stderr


def test_status_reports_where_a_thread_stands(workdir):
    cli(workdir, "run", "--application", "A-1042", "--thread", "f3a1")
    assert "PAUSED" in cli(workdir, "status", "f3a1").stdout
    cli(workdir, "resume", "f3a1", "approved")
    assert "DONE" in cli(workdir, "status", "f3a1").stdout


def test_status_of_an_unknown_thread_fails(workdir):
    done = cli(workdir, "status", "nope")
    assert done.returncode == 1
