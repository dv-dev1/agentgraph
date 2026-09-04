"""A credit desk agent, written against the engine and nothing else.

The bank releases credit on its own up to a limit. Above it, the graph stops
and waits for a human. Every node is a plain ``(dict) -> dict`` function: none
of them knows there is a database, a pause, or a second process.

No model is called here. ``assess`` applies rules, so the whole demo runs with
no API key. Swapping it for a model call is ten lines and the engine does not
change -- see the README.
"""

import json
from pathlib import Path

from agentgraph import END, START, Graph, add, interrupt, replace

DATA = Path(__file__).parent / "data"

LIMIT = 5000.0          # above this, a human decides
MIN_SCORE = 600
MAX_DEBT_RATIO = 0.30   # instalment over verified monthly income

SCHEMA = {
    "application_id": replace,
    "application": replace,
    "customer": replace,
    "facts": add,
    "amount": replace,
    "approved": replace,
    "outcome": replace,
}


def _load(name: str) -> dict:
    return json.loads((DATA / name).read_text())


def _brl(value: float) -> str:
    whole, cents = f"{value:,.2f}".split(".")
    return f"R$ {whole.replace(',', '.')},{cents}"


def say(node: str, message: str) -> None:
    print(f"[{node}]".ljust(20) + message)


# ---- nodes ---------------------------------------------------------------


def fetch_application(state: dict) -> dict:
    application = _load("applications.json")[state["application_id"]]
    say(
        "fetch_application",
        f"proposal {state['application_id']}, {_brl(application['value'])}"
        f" over {application['months']} months",
    )
    return {"application": application}


def score(state: dict) -> dict:
    customer = _load("bureau.json")[state["application"]["customer"]]
    say("score", f"score {customer['score']}, declared income {_brl(customer['declared_income'])}")
    return {"customer": customer, "facts": [f"credit score {customer['score']}"]}


def fetch_income(state: dict) -> dict:
    """Reached only when assess asks for it. This is what closes the cycle."""
    verified = _load("payroll.json")[state["application"]["customer"]]
    say("fetch_income", f"verified income {_brl(verified)}")
    return {
        "customer": {**state["customer"], "verified_income": verified},
        "facts": [f"verified income {_brl(verified)}"],
    }


def assess(state: dict) -> dict:
    """Apply the policy, or say what is still missing and let the router loop."""
    customer = state["customer"]
    if "verified_income" not in customer:
        say("assess", "income not verified yet")
        return {"facts": ["income not verified"]}

    application = state["application"]
    instalment = application["value"] / application["months"]
    ratio = instalment / customer["verified_income"]
    percent = round(ratio * 100)

    if customer["score"] < MIN_SCORE or ratio > MAX_DEBT_RATIO:
        say("assess", f"debt ratio {percent} percent, outside policy")
        return {"amount": 0.0, "facts": [f"debt ratio {percent} percent, outside policy"]}

    say("assess", f"debt ratio {percent} percent, within policy")
    return {
        "amount": application["value"],
        "facts": [f"debt ratio {percent} percent, within policy"],
    }


def human_approval(state: dict) -> dict:
    """interrupt() is the first line on purpose: a resume re-runs this node."""
    answer = interrupt(
        f"approve credit of {_brl(state['amount'])}"
        f" for customer {state['application']['customer']}?"
    )
    say("human_approval", f"answer: {answer}")
    return {"approved": answer == "approved", "facts": [f"human said {answer}"]}


def disburse(state: dict) -> dict:
    say("disburse", f"credit of {_brl(state['amount'])} released")
    return {"outcome": "released"}


# ---- routing -------------------------------------------------------------


def route_after_assess(state: dict) -> str:
    """One conditional edge, three destinations. The loop lives on the first."""
    if "verified_income" not in state["customer"]:
        return "fetch_income"
    if state["amount"] <= 0:
        say("check_threshold", "outside policy, nothing to release")
        return END
    if state["amount"] > LIMIT:
        say("check_threshold", f"{state['amount']:.2f} above the {LIMIT:.2f} limit")
        return "human_approval"
    say("check_threshold", f"{state['amount']:.2f} within the {LIMIT:.2f} limit")
    return "disburse"


def route_after_approval(state: dict) -> str:
    return "disburse" if state["approved"] else END


def build(checkpointer) -> Graph:
    graph = Graph(SCHEMA)
    graph.add_node("fetch_application", fetch_application)
    graph.add_node("score", score)
    graph.add_node("fetch_income", fetch_income)
    graph.add_node("assess", assess)
    graph.add_node("human_approval", human_approval)
    graph.add_node("disburse", disburse)

    graph.add_edge(START, "fetch_application")
    graph.add_edge("fetch_application", "score")
    graph.add_edge("score", "assess")
    graph.add_conditional_edge("assess", route_after_assess)
    graph.add_edge("fetch_income", "assess")  # the cycle
    graph.add_conditional_edge("human_approval", route_after_approval)
    graph.add_edge("disburse", END)
    return graph.compile(checkpointer)
