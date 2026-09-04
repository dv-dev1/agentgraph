"""Durable state: one row per step, in SQLite."""

import json
import sqlite3
from datetime import datetime, timezone

DDL = """
CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id  TEXT    NOT NULL,
    step       INTEGER NOT NULL,
    state      TEXT    NOT NULL,
    next_node  TEXT    NOT NULL,
    interrupt  TEXT,
    created_at TEXT    NOT NULL,
    PRIMARY KEY (thread_id, step)
)
"""


def _decode(row: sqlite3.Row) -> dict:
    return {
        "thread_id": row["thread_id"],
        "step": row["step"],
        "state": json.loads(row["state"]),
        "next_node": row["next_node"],
        "interrupt": None if row["interrupt"] is None else json.loads(row["interrupt"]),
        "created_at": row["created_at"],
    }


class Checkpointer:
    def __init__(self, path: str = "agentgraph.db"):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(DDL)
        self.conn.commit()

    def save(self, thread_id, step, state, next_node, interrupt=None) -> None:
        # INSERT OR REPLACE, not INSERT: resuming re-runs the interrupted node,
        # which rewrites that step's row rather than adding a second one.
        self.conn.execute(
            "INSERT OR REPLACE INTO checkpoints"
            " (thread_id, step, state, next_node, interrupt, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                thread_id,
                step,
                json.dumps(state),
                next_node,
                None if interrupt is None else json.dumps(interrupt),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()

    def load_latest(self, thread_id: str):
        row = self.conn.execute(
            "SELECT * FROM checkpoints WHERE thread_id = ? ORDER BY step DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
        return None if row is None else _decode(row)

    def list_paused(self) -> list:
        # The subquery matters: a thread that paused and then resumed still has
        # an old row with an interrupt in it, and must not show up here.
        rows = self.conn.execute(
            "SELECT * FROM checkpoints AS c"
            " WHERE c.interrupt IS NOT NULL"
            "   AND c.step = (SELECT MAX(step) FROM checkpoints WHERE thread_id = c.thread_id)"
            " ORDER BY c.created_at"
        ).fetchall()
        return [_decode(row) for row in rows]
