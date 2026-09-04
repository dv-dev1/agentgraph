"""The approval inbox: one page over the same resume() the CLI calls.

Single-threaded on purpose: a SQLite connection does not cross threads.
"""

import html
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from agentgraph import Checkpointer, NotPaused

from . import credit

DB = "agentgraph.db"

PAGE = """<!doctype html>
<title>Approvals</title>
<style>
 body {{ background:#14181A; color:#DFE5E3; font:15px/1.6 system-ui, sans-serif;
        margin:0; padding:40px 24px; }}
 main {{ max-width:760px; margin:0 auto; }}
 h1 {{ font-size:19px; font-weight:600; margin:0 0 24px; }}
 .card {{ border:1px solid #2E3639; background:#1B2124; padding:18px 20px;
          margin:0 0 14px; }}
 .amount {{ font-size:22px; font-weight:600; }}
 .id {{ color:#6E7B79; font-size:12px; letter-spacing:.04em; }}
 dl {{ display:grid; grid-template-columns:auto 1fr; gap:2px 16px;
       margin:14px 0; font-size:13px; }}
 dt {{ color:#6E7B79; }}
 dd {{ margin:0; }}
 form {{ display:inline; }}
 button {{ font:inherit; padding:7px 18px; margin:6px 8px 0 0; cursor:pointer;
           border:1px solid #2E3639; background:#15282A; color:#DFE5E3; }}
 button.deny {{ background:#2B1B18; }}
 .empty {{ color:#6E7B79; }}
</style>
<main>
<h1>Pending approvals ({count})</h1>
{cards}
</main>
"""

CARD = """<div class="card">
  <div class="id">thread {thread}</div>
  <div class="amount">{amount}</div>
  <dl>
    <dt>application</dt><dd>{application}</dd>
    <dt>score</dt><dd>{score}</dd>
    <dt>verified income</dt><dd>{income}</dd>
    <dt>found</dt><dd>{facts}</dd>
    <dt>recommendation</dt><dd>{recommendation}</dd>
  </dl>
  <form method="post" action="/approve">
    <input type="hidden" name="thread" value="{thread}">
    <input type="hidden" name="answer" value="approved">
    <button type="submit">Approve</button>
  </form>
  <form method="post" action="/approve">
    <input type="hidden" name="thread" value="{thread}">
    <input type="hidden" name="answer" value="denied">
    <button class="deny" type="submit">Deny</button>
  </form>
</div>
"""


def card(row: dict) -> str:
    """Four things and nothing else: deciding must not need a second screen."""
    state = row["state"]
    customer = state.get("customer", {})
    facts = state.get("facts", [])
    return CARD.format(
        thread=html.escape(row["thread_id"]),
        amount=html.escape(credit.brl(state.get("amount", 0.0))),
        application=html.escape(str(state.get("application_id", "?"))),
        score=html.escape(str(customer.get("score", "?"))),
        income=html.escape(credit.brl(customer.get("verified_income", 0.0))),
        facts=html.escape("; ".join(facts)),
        recommendation="approve" if "within policy" in " ".join(facts) else "review",
    )


def render(rows: list) -> str:
    cards = "".join(card(row) for row in rows)
    return PAGE.format(
        count=len(rows),
        cards=cards or '<p class="empty">Nothing is waiting. Start one with demo.cli run.</p>',
    )


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: str = "", location: str = None) -> None:
        payload = body.encode()
        self.send_response(code)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            return self._send(404, "not found")
        self._send(200, render(Checkpointer(DB).list_paused()))

    def do_POST(self):
        if self.path != "/approve":
            return self._send(404, "not found")

        length = int(self.headers.get("Content-Length", 0))
        form = urllib.parse.parse_qs(self.rfile.read(length).decode())
        thread = form.get("thread", [""])[0]
        answer = form.get("answer", [""])[0]

        try:
            credit.build(Checkpointer(DB)).resume(thread, answer)
        except (NotPaused, ValueError) as refused:
            return self._send(409, f"<p>{html.escape(str(refused))}</p>")

        # 303 and not 200: reloading the page must not approve a second time.
        self._send(303, "", location="/")

    def log_message(self, *args):
        pass


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="demo.inbox")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"approvals on http://127.0.0.1:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
