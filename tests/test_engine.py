"""Engine tests. Every one writes to a real file: an in-memory database would
pass and destroy the only thing this project proves.
"""

import pytest

from agentgraph import (
    END,
    START,
    Checkpointer,
    Graph,
    GraphRecursionError,
    NotPausedError,
    add,
    interrupt,
    merge,
    replace,
)

SCHEMA = {"facts": add, "step_name": replace, "value": replace}


def checkpointer(tmp_path):
    return Checkpointer(str(tmp_path / "test.db"))


def test_absent_field_survives_the_merge():
    state = {"facts": ["a"], "value": 10}
    assert merge(state, {"value": 20}, SCHEMA) == {"facts": ["a"], "value": 20}


def test_add_concatenates_and_replace_overwrites():
    state = {"facts": ["a"], "value": 10}
    merged = merge(state, {"facts": ["b"], "value": 20}, SCHEMA)
    assert merged == {"facts": ["a", "b"], "value": 20}


def test_field_outside_the_schema_raises():
    with pytest.raises(KeyError):
        merge({}, {"typo": 1}, SCHEMA)


def test_merge_does_not_mutate_the_original_state():
    state = {"facts": ["a"]}
    merge(state, {"facts": ["b"]}, SCHEMA)
    assert state == {"facts": ["a"]}


def test_compile_rejects_an_edge_to_an_unknown_node():
    graph = Graph(SCHEMA)
    graph.add_node("one", lambda s: {})
    graph.add_edge(START, "one")
    graph.add_edge("one", "ghost")
    with pytest.raises(ValueError, match="ghost"):
        graph.compile()


def test_compile_rejects_a_node_with_no_way_out():
    graph = Graph(SCHEMA)
    graph.add_node("one", lambda s: {})
    graph.add_edge(START, "one")
    with pytest.raises(ValueError, match="no way out"):
        graph.compile()


def test_compile_rejects_a_graph_with_no_entry():
    graph = Graph(SCHEMA)
    graph.add_node("one", lambda s: {})
    graph.add_edge("one", END)
    with pytest.raises(ValueError, match="where to begin"):
        graph.compile()


def test_invoke_before_compile_raises(tmp_path):
    graph = Graph(SCHEMA)
    graph.add_node("one", lambda s: {})
    graph.add_edge(START, "one")
    graph.add_edge("one", END)
    with pytest.raises(RuntimeError, match="compile"):
        graph.invoke({}, "t1")


def linear_graph(tmp_path):
    graph = Graph(SCHEMA)
    for name in ("first", "second", "third"):
        graph.add_node(name, lambda s, n=name: {"facts": [n], "step_name": n})
    graph.add_edge(START, "first")
    graph.add_edge("first", "second")
    graph.add_edge("second", "third")
    graph.add_edge("third", END)
    return graph.compile(checkpointer(tmp_path))


def test_a_linear_graph_runs_to_the_end(tmp_path):
    result = linear_graph(tmp_path).invoke({"facts": []}, "t1")
    assert result["status"] == "done"
    assert result["state"]["facts"] == ["first", "second", "third"]
    assert result["state"]["step_name"] == "third"


def test_one_row_per_step(tmp_path):
    graph = linear_graph(tmp_path)
    graph.invoke({"facts": []}, "t1")
    rows = graph.checkpointer.conn.execute(
        "SELECT step, next_node FROM checkpoints WHERE thread_id = 't1' ORDER BY step"
    ).fetchall()
    assert [r["step"] for r in rows] == [0, 1, 2]
    assert [r["next_node"] for r in rows] == ["second", "third", END]


def test_the_saved_state_grows_step_by_step(tmp_path):
    graph = linear_graph(tmp_path)
    graph.invoke({"facts": []}, "t1")
    first = graph.checkpointer.conn.execute(
        "SELECT state FROM checkpoints WHERE thread_id = 't1' AND step = 0"
    ).fetchone()
    assert '"first"' in first["state"] and '"second"' not in first["state"]


def test_a_conditional_edge_picks_the_target_at_run_time(tmp_path):
    graph = Graph(SCHEMA)
    graph.add_node("gate", lambda s: {"value": s["value"] * 2})
    graph.add_node("big", lambda s: {"facts": ["big"]})
    graph.add_node("small", lambda s: {"facts": ["small"]})
    graph.add_edge(START, "gate")
    graph.add_conditional_edge("gate", lambda s: "big" if s["value"] > 10 else "small")
    graph.add_edge("big", END)
    graph.add_edge("small", END)
    graph.compile(checkpointer(tmp_path))
    assert graph.invoke({"facts": [], "value": 9}, "t1")["state"]["facts"] == ["big"]
    assert graph.invoke({"facts": [], "value": 2}, "t2")["state"]["facts"] == ["small"]


def test_a_router_pointing_at_nothing_raises(tmp_path):
    graph = Graph(SCHEMA)
    graph.add_node("gate", lambda s: {})
    graph.add_edge(START, "gate")
    graph.add_conditional_edge("gate", lambda s: "ghost")
    graph.compile(checkpointer(tmp_path))
    with pytest.raises(ValueError, match="ghost"):
        graph.invoke({}, "t1")


def test_a_cycle_without_an_exit_hits_the_ceiling(tmp_path):
    graph = Graph(SCHEMA, limit=25)
    graph.add_node("spin", lambda s: {"facts": ["turn"]})
    graph.add_edge(START, "spin")
    graph.add_edge("spin", "spin")
    graph.compile(checkpointer(tmp_path))
    with pytest.raises(GraphRecursionError, match="exceeded 25 steps"):
        graph.invoke({"facts": []}, "t1")


def test_the_ceiling_is_checked_before_running_the_node(tmp_path):
    """25 steps means 25 node runs, not 26."""
    runs = []
    graph = Graph(SCHEMA, limit=3)
    graph.add_node("spin", lambda s: runs.append(1) or {})
    graph.add_edge(START, "spin")
    graph.add_edge("spin", "spin")
    graph.compile(checkpointer(tmp_path))
    with pytest.raises(GraphRecursionError):
        graph.invoke({}, "t1")
    assert len(runs) == 3


def approving_graph(store, log=None, ask_again=False):
    """prepare -> approval (asks a human) -> act -> END."""
    log = [] if log is None else log

    def approval(state):
        log.append("ran")
        answer = interrupt("sign off?")
        return {"facts": [f"answered {answer}"]}

    def act(state):
        if ask_again:
            interrupt("and again?")
        return {"facts": ["acted"]}

    graph = Graph(SCHEMA)
    graph.add_node("prepare", lambda s: {"facts": ["prepared"]})
    graph.add_node("approval", approval)
    graph.add_node("act", act)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "approval")
    graph.add_edge("approval", "act")
    graph.add_edge("act", END)
    return graph.compile(store)


def test_a_node_that_asks_for_a_human_pauses_the_graph(tmp_path):
    result = approving_graph(checkpointer(tmp_path)).invoke({"facts": []}, "t1")
    assert result["status"] == "paused"
    assert result["interrupt"] == "sign off?"
    assert result["state"]["facts"] == ["prepared"]  # the asking node did not land


def test_the_paused_row_points_at_the_node_that_asked(tmp_path):
    store = checkpointer(tmp_path)
    approving_graph(store).invoke({"facts": []}, "t1")
    row = store.load_latest("t1")
    assert row["next_node"] == "approval"
    assert row["interrupt"] == "sign off?"


def test_a_brand_new_graph_resumes_from_the_file(tmp_path):
    """The kill test. Nothing of the first run survives except the file."""
    path = str(tmp_path / "test.db")
    approving_graph(Checkpointer(path)).invoke({"facts": []}, "t1")

    fresh = approving_graph(Checkpointer(path))  # different objects, same file
    result = fresh.resume("t1", "approved")

    assert result["status"] == "done"
    assert result["state"]["facts"] == ["prepared", "answered approved", "acted"]


def test_resuming_replaces_the_paused_row_instead_of_adding_one(tmp_path):
    store = checkpointer(tmp_path)
    graph = approving_graph(store)
    graph.invoke({"facts": []}, "t1")
    graph.resume("t1", "approved")
    steps = store.conn.execute(
        "SELECT step FROM checkpoints WHERE thread_id = 't1' ORDER BY step"
    ).fetchall()
    assert [r["step"] for r in steps] == [0, 1, 2]


def test_resume_on_a_thread_that_is_not_paused_raises(tmp_path):
    store = checkpointer(tmp_path)
    graph = approving_graph(store)
    graph.invoke({"facts": []}, "t1")
    graph.resume("t1", "approved")
    with pytest.raises(NotPausedError, match="not paused"):
        graph.resume("t1", "approved")


def test_resume_on_an_unknown_thread_raises(tmp_path):
    with pytest.raises(ValueError, match="unknown thread"):
        approving_graph(checkpointer(tmp_path)).resume("nope", "approved")


def test_everything_above_the_interrupt_runs_twice(tmp_path):
    """The trap, pinned by a test so nobody 'fixes' it by accident."""
    log = []
    store = checkpointer(tmp_path)
    graph = approving_graph(store, log)
    graph.invoke({"facts": []}, "t1")
    assert log == ["ran"]
    graph.resume("t1", "approved")
    assert log == ["ran", "ran"]


def test_the_answer_does_not_leak_into_the_next_node(tmp_path):
    store = checkpointer(tmp_path)
    graph = approving_graph(store, ask_again=True)
    graph.invoke({"facts": []}, "t1")
    result = graph.resume("t1", "approved")
    assert result["status"] == "paused"
    assert result["interrupt"] == "and again?"


def test_load_latest_returns_the_highest_step(tmp_path):
    store = checkpointer(tmp_path)
    store.save("t1", 0, {"value": 1}, "second")
    store.save("t1", 1, {"value": 2}, END)
    assert store.load_latest("t1")["state"] == {"value": 2}


def test_load_latest_of_an_unknown_thread_is_none(tmp_path):
    assert checkpointer(tmp_path).load_latest("nope") is None


def test_list_paused_sees_a_thread_the_engine_actually_paused(tmp_path):
    store = checkpointer(tmp_path)
    approving_graph(store).invoke({"facts": [], "value": 1}, "t1")
    paused = store.list_paused()
    assert len(paused) == 1
    assert paused[0]["thread_id"] == "t1"
    assert paused[0]["interrupt"] == "sign off?"


def test_list_paused_ignores_a_thread_that_already_resumed(tmp_path):
    store = checkpointer(tmp_path)
    store.save("t1", 0, {}, "approval", interrupt={"question": "ok?"})
    store.save("t2", 0, {}, "approval", interrupt={"question": "ok?"})
    store.save("t1", 1, {}, END)  # t1 moved on
    assert [row["thread_id"] for row in store.list_paused()] == ["t2"]
