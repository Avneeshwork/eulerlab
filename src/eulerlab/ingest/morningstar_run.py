"""`make morningstar` — fetch fund ratings and report how far they join.

The join report is the point of the command, not a footnote. Morningstar
publishes no ISIN and no scheme code, so the only bridge to our AMFI data is
the fund name — and `CLAUDE.md` forbids joining on anything but an internal id.
Printing the match rate every run keeps that compromise visible instead of
letting it settle into the background as though it were solved.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from eulerlab.ingest import amfi, morningstar


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch Morningstar India fund ratings.")
    parser.add_argument("--page-size", type=int, default=200)
    parser.add_argument("--pace", type=float, default=1.2, help="seconds between page requests")
    parser.add_argument("--max-pages", type=int, default=45)
    parser.add_argument("--no-join", action="store_true", help="skip the AMFI join report")
    args = parser.parse_args(argv)

    print("== Morningstar India ratings ==")
    ratings = morningstar.fetch_all(
        page_size=args.page_size, pace=args.pace, max_pages=args.max_pages
    )
    if not ratings:
        print("no ratings parsed — the page structure has probably changed")
        return 1

    path = morningstar.land(ratings)
    print(f"\nlanded {len(ratings):,} ratings -> {path}")

    rated = [r for r in ratings if r.star_rating is not None]
    print(f"  {len(rated):,} carry a star rating; {len(ratings) - len(rated):,} are unrated")

    if args.no_join:
        return 0

    print("\n== join to AMFI ==")
    schemes = amfi.fetch_universe()
    join = morningstar.join_to_amfi(ratings, list(schemes))
    print(f"  matched   : {len(join.matched):,}  ({join.rate * 100:.1f}%)")
    print(f"  ambiguous : {join.ambiguous:,}  (name folds to more than one scheme — left unjoined)")
    print(f"  unmatched : {join.unmatched:,}")
    print(
        "\nThis join is BY NAME and therefore fuzzy. Morningstar publishes no ISIN\n"
        "and no scheme code, and CLAUDE.md requires joins on internal ids only.\n"
        "An ambiguous name is left unjoined rather than resolved by picking one:\n"
        "a rating on the wrong fund is worse than a rating on none."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
