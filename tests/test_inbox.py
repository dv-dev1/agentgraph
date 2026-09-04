"""The approval screen. The unit tests render rows; the integration test drives
a real server, because the 303 is the part that stops a double approval.
"""

import http.client

from demo import inbox

from .conftest import cli

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


def get(port, path="/"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    conn.request("GET", path)
    response = conn.getresponse()
    return response.status, response.read().decode()


def approve(port, thread, answer="approved"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    conn.request(
        "POST",
        "/approve",
        body=f"thread={thread}&answer={answer}",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response = conn.getresponse()
    response.read()
    return response.status


def test_the_page_lists_what_the_engine_paused(server):
    port, _ = server
    status, body = get(port)
    assert status == 200
    assert "A-1042" in body
    assert "Pending approvals (1)" in body


def test_approving_redirects_and_finishes_the_thread(server):
    port, workdir = server
    assert approve(port, "f3a1") == 303

    done = cli(workdir, "status", "f3a1")
    assert "DONE" in done.stdout
    assert "released" in done.stdout


def test_the_page_empties_after_the_approval(server):
    port, _ = server
    approve(port, "f3a1")
    assert "Nothing is waiting" in get(port)[1]


def test_approving_the_same_thread_twice_is_refused(server):
    port, _ = server
    approve(port, "f3a1")
    assert approve(port, "f3a1") == 409


def test_denying_closes_the_thread_without_releasing(server):
    port, workdir = server
    assert approve(port, "f3a1", "denied") == 303
    assert "released" not in cli(workdir, "status", "f3a1").stdout
