"""Pausing: a node asks a human, the engine stores the question and exits."""

import contextvars

MISSING = object()

# The answer is handed to the node through a context variable rather than a
# module global: same number of lines, and it does not break if two graphs run
# in different threads.
_answer = contextvars.ContextVar("agentgraph_resume_answer", default=MISSING)


class GraphInterrupt(Exception):  # noqa: N818 -- LangGraph calls it exactly this
    def __init__(self, payload):
        super().__init__(payload)
        self.payload = payload


def interrupt(payload):
    """Raises on the first pass, returns the human's answer on resume.

    Resuming re-runs the node from its first line, so everything above this call
    happens twice. Put side effects below it, or in a node of their own.
    """
    answer = _answer.get()
    if answer is MISSING:
        raise GraphInterrupt(payload)
    return answer


def supply(answer):
    return _answer.set(answer)


def withdraw(token):
    _answer.reset(token)
