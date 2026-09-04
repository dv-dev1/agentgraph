"""Pausing: a node asks a human, the engine stores the question and exits.

The node calls ``interrupt(...)`` and does not know whether it is being run for
the first time or being resumed. That ignorance is the design: a node stays a
plain ``(dict) -> dict`` function and never learns about threads, databases or
processes.
"""

import contextvars

MISSING = object()

# The answer is handed to the node through a context variable rather than a
# module global: same number of lines, and it does not break if two graphs run
# in different threads.
_answer = contextvars.ContextVar("agentgraph_resume_answer", default=MISSING)


class Interrupted(Exception):
    """Raised by ``interrupt`` when no human answer is available yet."""

    def __init__(self, payload):
        super().__init__(payload)
        self.payload = payload


def interrupt(payload):
    """Ask a human. Raises on the first pass, returns the answer on resume.

    Resuming re-runs the node from its first line, so everything above this
    call happens twice. Put side effects below it, or in a node of their own.
    """
    answer = _answer.get()
    if answer is MISSING:
        raise Interrupted(payload)
    return answer


def supply(answer):
    """Make ``answer`` visible to the next ``interrupt`` call. Used by the engine."""
    return _answer.set(answer)


def withdraw(token):
    """Undo a ``supply``. The answer belongs to one node run, not to the graph."""
    _answer.reset(token)
