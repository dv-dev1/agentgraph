"""The engine: assemble the graph, run the loop, save every step.

Two phases, like LangGraph: you assemble the whole graph first, then ``compile``
freezes and validates it, and only then can it run.
"""

from .checkpoint import Checkpointer
from .state import merge

START = "__start__"
END = "__end__"


class RecursionLimit(RuntimeError):
    """The graph went past its step ceiling. Almost always a cycle with no exit."""


class Graph:
    def __init__(self, schema: dict, limit: int = 25):
        self.schema = schema
        self.limit = limit
        self.nodes: dict = {}
        self.edges: dict = {}        # source -> fixed target
        self.routers: dict = {}      # source -> (state) -> target name
        self.checkpointer = None
        self._compiled = False

    # ---- assembly -------------------------------------------------------

    def add_node(self, name: str, fn):
        """Register a node. A node is a plain function ``(dict) -> dict``."""
        if name in (START, END):
            raise ValueError(f"{name!r} is reserved")
        if name in self.nodes:
            raise ValueError(f"node {name!r} already exists")
        self.nodes[name] = fn
        return self

    def add_edge(self, source: str, target: str):
        """A fixed edge. ``add_edge(START, "first")`` says where execution begins."""
        if source in self.edges or source in self.routers:
            raise ValueError(f"{source!r} already has an outgoing edge")
        self.edges[source] = target
        return self

    def add_conditional_edge(self, source: str, router):
        """An edge whose target is decided at run time by ``router(state)``."""
        if source in self.edges or source in self.routers:
            raise ValueError(f"{source!r} already has an outgoing edge")
        self.routers[source] = router
        return self

    def compile(self, checkpointer=None):
        """Freeze and validate. Every failure here is a failure you get for free."""
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

    # ---- execution ------------------------------------------------------

    def _next(self, node: str, state: dict) -> str:
        if node in self.routers:
            target = self.routers[node](state)
            if target not in set(self.nodes) | {END}:
                raise ValueError(f"router of {node!r} returned {target!r}, which does not exist")
            return target
        return self.edges[node]

    def invoke(self, state: dict, thread_id: str) -> dict:
        """Run from the start until END, saving every step."""
        if not self._compiled:
            raise RuntimeError("call compile() before invoke()")

        node = self.edges[START]
        step = 0
        while node != END:
            if step >= self.limit:
                raise RecursionLimit(f"exceeded {self.limit} steps")
            delta = self.nodes[node](state)
            state = merge(state, delta, self.schema)
            node = self._next(node, state)
            self.checkpointer.save(thread_id, step, state, node)
            step += 1
        return state
