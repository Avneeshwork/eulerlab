# ADR-065 — Company pages show what is held and name what is not

**Context.** Operator, 2026-10-12: "build pages for each stocks about their
details from data we have from fundamental data", with a screenshot of a US
broker's stock page. That page has panels for analyst ratings, price targets,
forward estimates and a discounted cash flow. None of those is in any landed
file: the fundamentals tree is screener.in's header ratios, sector, index
membership and six statement tables.

**Options.** (a) Build only the panels the data supports and list the rest as
not held. (b) Add a paid or scraped source for analyst data. (c) Compute a
DCF from the cash-flow table with an assumed discount rate and growth.

**Choice.** (a). `features/company_page.py` builds the page; `NOT_HELD` is
printed on it. One page per company at `/terminal/company/<SYMBOL>`.

**Why.** (b) is a new data source and a cost, which needs its own decision.
(c) would put a "fair value" on screen that is mostly the two assumed inputs;
on a page next to real figures it would read as a measurement. The handful of
figures that are computed (debt to equity, margins, trailing EPS, growth,
industry median P/E) are arithmetic on rows the page also shows.

**Cost if wrong.** The page is thinner than a broker's. Adding a panel later
is additive: a new source, a new key in the payload, a new section.
