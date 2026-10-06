# ADR-056: One home per feature, in OpenAlgo's shell

## Status

Accepted, 2026-10-06. Supersedes the visual grammar of ADR-041 and
`docs/RESEARCH/018`; keeps ADR-041's rule that green means "cleared the bar".

## Context

The operator found the terminal hard to use. Nine top-level tabs, and the same
job reachable from several of them: a backtest could be configured from the
Library toolbar (universe, instruments), the Run tab (asset, universe, window,
tier) and the Backtest dialog (all of it), so a run's real settings could only
be known by checking three places. Risk and Live were two tabs answering one
question. The Data tab was built and reachable from nowhere. The ⌘K palette
listed strategies and a "RUN" action that did nothing when chosen.

The operator asked for OpenAlgo's interface (github.com/marketcalls/openalgo,
`frontend/`) and for each thing to live in one place.

## Decision

**Six top-level pages, the rest behind Tools.** Dashboard (was Snapshot),
Strategies (was Library), Charts, Options, Live & Risk (was Live and Risk),
Tools. Tools is a page of cards, as OpenAlgo's is: Strategy Builder (was
Build), Instruments, Data Status (previously unreachable). The page is in the
URL hash, so pages can be bookmarked and the back button works.

**Backtests are configured in the Backtest dialog only.** It now takes one
strategy (a row's button) or the whole selection (the selection bar), and
shows the trial-cost preview that only the Run tab used to show. The Run tab,
the Library's universe and instrument pickers, and `InstrumentChooser` are
removed. The Strategy Builder keeps its `BacktestOptions` because what it runs
is not in the registry; it is the same component bound to the same state.

**OpenAlgo's look.** shadcn/ui zinc neutrals, near-black primary, white
bordered cards, 6–12px radii, system font, a 56px sticky bar of icon-and-label
links with the active one filled, sentence-case labels, and a bottom
navigation bar on phones. Icons from `lucide-react`, the set OpenAlgo uses.
Implemented as token changes in `tokens.css` plus one override file,
`app/terminal/shell.css`, so the change reads in one place.

**The backtest report is a page, not a dialog.** `#report/<strategy>` shows
OpenAlgo's results layout: stat cards (net profit, CAGR, max drawdown, Sharpe
against the bar, Sortino, win rate, profit factor, costs) and tabs for the
equity curve, drawdown episodes, a monthly-returns heatmap, the list of
trades, instruments and fills. Trades are round trips matched first in, first
out from the fill ledger, client-side, so no endpoint changed.

**The palette navigates.** Every entry is a page, a tool or a strategy, and
choosing one goes there.

## Cost if wrong

Nothing computed changed: every number on screen comes from the same API call
as before, and only where controls live moved. Reverting the look is removing
one import; reverting the structure is one file, `app/terminal/page.tsx`.
