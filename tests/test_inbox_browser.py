"""The inbox in a real browser. The HTTP tests post to the endpoint directly and
never touch the form, so 'the button works' was an assumption until this file.

Screenshots land in tmp unless SHOTS_DIR points somewhere; that is how the images
in docs/ are produced:

    SHOTS_DIR=docs python -m pytest tests/test_inbox_browser.py
"""

import os

import pytest

from .conftest import cli

playwright_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture
def page(tmp_path):
    from playwright.sync_api import sync_playwright

    try:
        runner = sync_playwright().start()
        browser = runner.chromium.launch()
    except Exception as missing:
        pytest.skip(f"no chromium for playwright: {missing}")

    context = browser.new_context(viewport={"width": 900, "height": 640})
    yield context.new_page()
    browser.close()
    runner.stop()


def shot(page, name):
    directory = os.environ.get("SHOTS_DIR")
    if directory:
        page.screenshot(path=os.path.join(directory, name), full_page=True)


def test_the_button_approves_and_the_agent_finishes(page, server):
    port, workdir = server
    page.goto(f"http://127.0.0.1:{port}/")

    assert "Pending approvals (1)" in page.inner_text("h1")
    assert "A-1042" in page.content()
    assert "R$ 40.000,00" in page.content()
    shot(page, "inbox-pending.png")

    page.click("button:has-text('Approve')")
    page.wait_for_url(f"http://127.0.0.1:{port}/")

    assert "Pending approvals (0)" in page.inner_text("h1")
    assert "Nothing is waiting" in page.content()
    shot(page, "inbox-empty.png")

    done = cli(workdir, "status", "f3a1")
    assert "DONE" in done.stdout
    assert "released" in done.stdout


def test_the_deny_button_closes_without_releasing(page, server):
    port, workdir = server
    page.goto(f"http://127.0.0.1:{port}/")
    page.click("button:has-text('Deny')")
    page.wait_for_url(f"http://127.0.0.1:{port}/")

    assert "Nothing is waiting" in page.content()
    assert "released" not in cli(workdir, "status", "f3a1").stdout


def test_going_back_after_approving_shows_an_empty_list(page, server):
    """POST-redirect-GET at work: back re-runs the GET, so the button is gone."""
    port, _ = server
    page.goto(f"http://127.0.0.1:{port}/")
    page.click("button:has-text('Approve')")
    page.go_back()

    assert "Nothing is waiting" in page.content()
    assert page.locator("button:has-text('Approve')").count() == 0


def test_a_stale_tab_is_refused_instead_of_approving_twice(page, server):
    """Two tabs on the same list. One approves; the other still shows the button."""
    port, _ = server
    page.goto(f"http://127.0.0.1:{port}/")
    stale = page.context.new_page()
    stale.goto(f"http://127.0.0.1:{port}/")

    page.click("button:has-text('Approve')")
    stale.click("button:has-text('Approve')")

    assert "is not paused" in stale.content()
