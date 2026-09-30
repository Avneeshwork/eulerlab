# 021 — The trader snapshot, designed against Finviz, Benzinga Pro and Koyfin

**Question.** What should a trader's first screen be, if it were designed
rather than accumulated?

## What the references each get right

| Product | Its one contribution |
|---|---|
| **Finviz** | The **map**. Size and colour encode two variables at once, so the eye reads a cluster — "the whole of IT is red, and it is big" — in a single glance. A ranked table cannot do that, because it forces the reader to reconstruct the grouping from names |
| **Benzinga Pro** | The **why**. Real-time news tagged to tickers. A mover without a catalyst is noise; the same mover with an earnings beat behind it is information, and the difference decides whether anyone should act |
| **Koyfin** | The **context**. Cross-asset dashboards, so equities are never read in isolation from rates, FX and crypto — and customisable, because a macro scan and a deep dive are different jobs |

## The design

Five bands, in the order a person actually needs them. The ordering is the
design: most dashboards open with a price, and a price without regime is nearly
useless — +0.4% in a calm uptrend and +0.4% inside a volatility spike are
different facts about different markets.

### 1. Regime — what kind of day is this

Before any number, the shape of the session. Trend direction and age,
realised volatility and whether it is expanding or contracting, and **breadth
against the index**.

Breadth is the honest index. A cap-weighted index can be carried by five names
while most of the market falls, so advancers-versus-decliners is what actually
happened. **Divergence is the headline**: index up on negative breadth is the
single most useful thing a snapshot can say, and almost no retail tool says it.

### 2. The map — what moved

Finviz's contribution, and the band that earns the most screen area. Grouped by
sector, sized by market capitalisation, coloured by return.

Sector grouping is what makes it readable: an individually red tile is one
company's problem, a red *block* is a rotation, and only the grouping lets the
eye tell them apart.

### 3. Movers — the extremes, with reasons

Gainers, losers and unusual volume. **Unusual volume is the most useful of the
three** and the most often buried: a stock up 2% on ten times its normal volume
is a different event from one up 8% on nothing.

Every row needs a *why* column. Without it this is a list of noise wearing a
ranking.

### 4. Cross-asset — what else is happening

Equity, crypto, FX, funds, rates, commodities on one strip. Koyfin's
contribution and the one most Indian retail tools skip entirely.

### 5. Your book, and whether any of it is evidence

Two bands no reference has.

**The book**: positions, exposure, P&L, risk. A snapshot that does not know
what you own makes you do the join in your head, every time.

**The evidence**: the noise bar, what is clearing it, and how much search has
been spent getting there. Every other terminal shows patterns. This platform
exists to say when a pattern is indistinguishable from luck, and that belongs
on the first screen rather than three clicks in.

## What this needs that does not exist here

Listed so the gap is a decision rather than a discovery.

| Needed | For | Status |
|---|---|---|
| Sector / industry classification | The map's grouping — without it the map is a bag of tiles | **Missing.** The instrument master carries ISIN and symbol, no sector |
| Market capitalisation | The map's sizing. Turnover is a usable proxy and a different statement — it sizes by *attention* rather than by *size* | **Missing.** Turnover is available |
| Index levels (NIFTY, BANKNIFTY) | The regime band's headline, and the breadth divergence | **Missing.** Constituents are landed, the index is not |
| India VIX | Implied volatility against realised | **Missing.** Realised is computable from the panel |
| News with ticker tagging | The *why* column, and band 3 generally | **Missing entirely.** This is the largest gap and the one that most changes the product |
| Earnings and corporate-action calendar | Forward catalysts | Partially — actions are landed, an earnings calendar is not |
| Live or delayed quotes | Anything described as "now" | **Missing.** The panel is end-of-day; minute bars are historical |

## Decision

Build the five bands with honest empty states rather than a smaller product
that hides its gaps. A band that says "no news source is connected" is more
useful than a band quietly omitted, because the first is a shopping list and the
second is invisible.

Where a proxy exists it is used and labelled as a proxy — turnover for market
cap sizes the map by attention rather than by size, which is a different and
occasionally more useful view, but it is not what Finviz shows and must not
claim to be.

**Confidence.** High on the design, which is a synthesis of three products
whose choices are visible. Low on any claim that this is what *this* platform
can show today; the table above is the distance.
