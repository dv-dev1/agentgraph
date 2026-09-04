"""The approval screen. The unit tests render rows; the integration test drives
a real server, because the 303 is the part that stops a double approval.
"""

import http.client
import socket
import subprocess
import sys
import time

import pytest

from demo import inbox

ROOT = __file__.rsplit("/tests/", 1)[0]

ROW = {
    "thread_id": "f3a1",
    "state": {
        "application_id": "A-1042",
        "amount": 40000.0,
        "customer": {"score": 742, "verified_income": 8000.0},
        "facts": ["credit score 742", "debt ratio 21 percent, within policy"],
    },
}


def test_an_empty_inbox_says_so():
    assert "Nothing is waiting" in inbox.render([])


def test_a_card_carries_the_four_things_needed_to_decide():
    html = inbox.card(ROW)
    assert "R$ 40.000,00" in html
    assert "742" in html
    assert "R$ 8.000,00" in html
    assert "within policy" in html
    assert "approve" in html


def test_the_card_offers_both_answers():
    html = inbox.card(ROW)
    assert 'value="approved"' in html
    assert 'value="denied"' in html


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def server(tmp_path):
    env = {"PYTHONPATH": ROOT, "PATH": "/usr/bin:/bin"}
    subprocess.run(
        [sys.executable, "-m", "demo.cli", "run", "--application", "A-1042",
         "--thread", "f3a1"],
        cwd=str(tmp_path), env=env, capture_output=True,
    )
    port = free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "demo.inbox", "--port", str(port)],
        cwd=str(tmp_path), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
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

    yield port, str(tmp_path), env
    process.kill()


def get(port, path="/"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    conn.request("GET", path)
    response = conn.getresponse()
    return response.status, response.read().decode()


def approve(port, thread, answer="approved"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    conn.request(
        "POST", "/approve",
        body=f"thread={thread}&answer={answer}",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response = conn.getresponse()
    response.read()
    return response.status


def test_the_page_lists_what_the_engine_paused(server):
    port, _, _ = server
    status, body = get(port)
    assert status == 200
    assert "A-1042" in body
    assert "Pending approvals (1)" in body


def test_approving_redirects_and_finishes_the_thread(server):
    port, workdir, env = server
    assert approve(port, "f3a1") == 303

    done = subprocess.run(
        [sys.executable, "-m", "demo.cli", "status", "f3a1"],
        cwd=workdir, env=env, capture_output=True, text=True,
    )
    assert "DONE" in done.stdout
    assert "released" in done.stdout


def test_the_page_empties_after_the_approval(server):
    port, _, _ = server
    approve(port, "f3a1")
    assert "Nothing is waiting" in get(port)[1]


def test_approving_the_same_thread_twice_is_refused(server):
    port, _, _ = server
    approve(port, "f3a1")
    assert approve(port, "f3a1") == 409


def test_denying_closes_the_thread_without_releasing(server):
    port, workdir, env = server
    assert approve(port, "f3a1", "denied") == 303
    done = subprocess.run(
        [sys.executable, "-m", "demo.cli", "status", "f3a1"],
        cwd=workdir, env=env, capture_output=True, text=True,
    )
    assert "released" not in done.stdout
