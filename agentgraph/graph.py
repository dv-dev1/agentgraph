"""The engine: assemble the graph, run the loop, save every step."""

from .checkpoint import Checkpointer
from .interrupt import MISSING, Interrupted, supply, withdraw
from .state import merge

START = "__start__"
END = "__end__"


class RecursionLimit(RuntimeError):
    """The graph went past its step ceiling. Almost always a cycle with no exit."""


class NotPaused(RuntimeError):
    """The guard against a double click: answering twice would run the node twice."""


class Graph:
    def __init__(self, schema: dict, limit: int = 25):
        self.schema = schema
        self.limit = limit
        self.nodes: dict = {}
        self.edges: dict = {}        # source -> fixed target
        self.routers: dict = {}      # source -> (state) -> target name
        self.checkpointer = None
        self._compiled = False

    def add_node(self, name: str, fn):
        if name in (START, END):
            raise ValueError(f"{name!r} is reserved")
        if name in self.nodes:
            raise ValueError(f"node {name!r} already exists")
        self.nodes[name] = fn
        return self

    def add_edge(self, source: str, target: str):
        """``add_edge(START, "first")`` is what says where execution begins."""
        if source in self.edges or source in self.routers:
            raise ValueError(f"{source!r} already has an outgoing edge")
        self.edges[source] = target
        return self

    def add_conditional_edge(self, source: str, router):
        if source in self.edges or source in self.routers:
            raise ValueError(f"{source!r} already has an outgoing edge")
        self.routers[source] = router
        return self

    def compile(self, checkpointer=None):
        """Freeze the graph and reject what would only fail halfway through a run."""
        if START not in self.edges:
            raise ValueError("missing add_edge(START, ...): nothing says where to begin")

        known = set(self.nodes) | {END}
        for source, target in self.edges.items():
            if source != START and source not in self.nodes:
                raise ValueError(f"edge leaves {source!r}, which is not a node")
            if target not in known:
                raise ValueError(f"edge points at {target!r}, which does not exist")
        for source in self.routers:
            if source not in self.nodes:
                raise ValueError(f"conditional edge leaves {source!r}, which is not a node")

        dangling = set(self.nodes) - set(self.edges) - set(self.routers)
        if dangling:
            raise ValueError(f"node with no way out: {sorted(dangling)}")

        self.checkpointer = checkpointer or Checkpointer()
        self._compiled = True
        return self

    def _next(self, node: str, state: dict) -> str:
        if node in self.routers:
            target = self.routers[node](state)
            if target not in set(self.nodes) | {END}:
                raise ValueError(f"router of {node!r} returned {target!r}, which does not exist")
            return target
        return self.edges[node]

    def _call(self, node: str, state: dict, answer):
        if answer is MISSING:
            return self.nodes[node](state)
        token = supply(answer)
        try:
            return self.nodes[node](state)
        finally:
            withdraw(token)

    def _run(self, state: dict, thread_id: str, node: str, step: int, answer=MISSING) -> dict:
        while node != END:
            if step >= self.limit:
                raise RecursionLimit(f"exceeded {self.limit} steps")
            try:
                delta = self._call(node, state, answer)
            except Interrupted as pause:
                # Save the state as it was *before* the node ran, and the node
                # itself as next_node: resuming re-runs it from its first line.
                self.checkpointer.save(thread_id, step, state, node, pause.payload)
                return {
                    "status": "paused",
                    "thread_id": thread_id,
                    "step": step,
                    "state": state,
                    "interrupt": pause.payload,
                }
            answer = MISSING  # the answer belongs to the node that asked for it
            state = merge(state, delta, self.schema)
            node = self._next(node, state)
            self.checkpointer.save(thread_id, step, state, node)
            step += 1
        return {"status": "done", "thread_id": thread_id, "state": state}

    def invoke(self, state: dict, thread_id: str) -> dict:
        if not self._compiled:
            raise RuntimeError("call compile() before invoke()")
        return self._run(state, thread_id, self.edges[START], 0)

    def resume(self, thread_id: str, answer) -> dict:
        """Carry on a paused thread. Nothing of the first run is still in memory."""
        if not self._compiled:
            raise RuntimeError("call compile() before resume()")
        row = self.checkpointer.load_latest(thread_id)
        if row is None:
            raise ValueError(f"unknown thread {thread_id!r}")
        if row["interrupt"] is None:
            raise NotPaused(f"thread {thread_id} is not paused")
        return self._run(row["state"], thread_id, row["next_node"], row["step"], answer)
