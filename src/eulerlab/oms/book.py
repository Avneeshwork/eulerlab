"""`make reconcile-book` — what do we think we hold, and what does the broker say?

The command to run first on a morning that looks wrong, before anything else
is touched. It recovers any orders left in flight, resolves whatever it can by
asking, and then compares the two position books.

It changes nothing at the broker and places no orders. It exits non-zero when
there is a break, so it can be a scheduled check rather than something someone
remembers to look at.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from eulerlab.db.stream import stream_for
from eulerlab.oms import reconcile
from eulerlab.oms.journal import KIND, Journal, verify_replay
from eulerlab.paper import runner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile the order book against the broker.")
    parser.add_argument("--dir", default=str(runner.PAPER_DIR), help="which book to reconcile")
    parser.add_argument("--no-recover", action="store_true", help="compare without querying first")
    args = parser.parse_args(argv)

    root = Path(args.dir)
    # The header prints before the early exit on purpose. A fresh clone has no
    # journal, and a caller checking this command's output needs to be able to
    # tell "the book is empty" from "the command did not run".
    print(f"book: {root}")
    path = root / "orders.jsonl"
    stream = stream_for(path, KIND)
    if not (stream.count() if stream is not None else path.exists()):
        print("no journal yet — nothing has traded. Run `make paper` to create one.")
        print("\nreconciliation: nothing to compare")
        return 0

    oms = runner.fresh_oms(root)
    print(f"orders on record: {len(oms.states()):,}")

    problems = verify_replay(Journal(root / "orders.jsonl"))
    if problems:
        print(f"\nJOURNAL DISAGREES WITH THE STATE MACHINE in {len(problems)} place(s):")
        for line in problems[:10]:
            print(f"  {line}")
        print("\nStop here. One of the two was wrong when it mattered.")
        return 1

    if not args.no_recover:
        report = oms.recover()
        print(report.render())

    result = reconcile.reconcile(oms)
    print(result.render())

    unresolved = oms.unresolved()
    if unresolved:
        print(f"\n{len(unresolved)} order(s) still UNKNOWN — the broker could not be asked:")
        for client_order_id in unresolved[:10]:
            print(f"  {client_order_id}")
        print("These may be live. Do not send more until they are resolved.")
        return 1
    return 0 if result.clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
