"""Three commands. run and resume are separate on purpose: a single command with
a --resume flag would hide the fact that they are different processes.
"""

import argparse
import sys
import uuid

from agentgraph import Checkpointer, NotPaused

from . import credit

DB = "agentgraph.db"


def cmd_run(args) -> int:
    thread_id = args.thread or uuid.uuid4().hex[:4]
    graph = credit.build(Checkpointer(DB))
    result = graph.invoke({"application_id": args.application, "facts": []}, thread_id)
    if result["status"] == "paused":
        print(f"PAUSED  thread={thread_id}  waiting: {result['interrupt']}")
    else:
        print("OK")
    return 0


def cmd_resume(args) -> int:
    graph = credit.build(Checkpointer(DB))
    try:
        graph.resume(args.thread, args.answer)
    except NotPaused:
        print(f"ERROR: thread {args.thread} is not paused", file=sys.stderr)
        return 1
    except ValueError as unknown:
        print(f"ERROR: {unknown}", file=sys.stderr)
        return 1
    print("OK")
    return 0


def cmd_status(args) -> int:
    row = Checkpointer(DB).load_latest(args.thread)
    if row is None:
        print(f"ERROR: unknown thread {args.thread}", file=sys.stderr)
        return 1
    if row["interrupt"] is not None:
        print(f"PAUSED     waiting: {row['interrupt']}")
    elif row["next_node"] == "__end__":
        outcome = row["state"].get("outcome", "closed with no release")
        print(f"DONE       {outcome}")
    else:
        print(f"RUNNING    next node: {row['next_node']}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="demo.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="start a credit application")
    run.add_argument("--application", required=True)
    run.add_argument("--thread", help="use a fixed thread id instead of a random one")
    run.set_defaults(handler=cmd_run)

    resume = sub.add_parser("resume", help="answer a paused thread")
    resume.add_argument("thread")
    resume.add_argument("answer")
    resume.set_defaults(handler=cmd_resume)

    status = sub.add_parser("status", help="where a thread stands")
    status.add_argument("thread")
    status.set_defaults(handler=cmd_status)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
