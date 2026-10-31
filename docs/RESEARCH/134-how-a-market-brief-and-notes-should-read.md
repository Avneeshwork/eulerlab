# 134 — How should the market brief and the agents' notes read?

**Date:** 2026-10-31 · **Confidence:** high on how readers take in a page (NN/g's measurements) and on the shape of professional notes (several real examples agree); medium on the trader-specific parts (vendor templates and practitioner blogs, no study); low on the right base-rate design, which nobody publishes a method for.

## Question

On 2026-10-31 the operator said the Trader's read (ADR-100) still isn't readable: the agent card shows it as one block of text. They also said the brief has "not much information... just data". They asked for research on how a market brief and notes should read before any more building.

## Sources

| Source | URL | Fetched | Read |
|---|---|---|---|
| Nielsen, How Users Read on the Web (NN/g, 1997) | https://www.nngroup.com/articles/how-users-read-on-the-web/ | 2026-10-31 | Whole article |
| Schade, Inverted Pyramid: Writing for Comprehension (NN/g, 2018) | https://www.nngroup.com/articles/inverted-pyramid/ | 2026-10-31 | Whole article |
| Few, Why Most Dashboards Fail (Perceptual Edge, 2007) | https://blogs.ischool.berkeley.edu/i247s13/files/2013/02/WhyMostDashboardsFail.pdf | 2026-10-31 | First 4 pages |
| Reuters Morning Bid Americas, 7 Oct 2025 (Mike Dolan), republished by Tiger Brokers | https://www.itiger.com/news/2573951870 | 2026-10-31 | Whole note, for structure |
| "Morning note" template for sell-side analysts (financecontext.com; no author or date) | https://financecontext.com/en/equity-research/skills/morning-note | 2026-10-31 | Whole page |
| BLUF (Wikipedia, citing US Army Regulation 25-50) | https://en.wikipedia.org/wiki/BLUF_(communication) | 2026-10-31 | Search summary only |
| Lovallo & Kahneman on the outside view (Management Science 1993; HBR 2003) | https://corporate.jasoncollins.blog/outside-view | 2026-10-31 | Secondary summaries only |
| SentimenTrader precedent studies (blog) | https://sentimentrader.com/blog/small-persistent-losses | 2026-10-31 | Search summaries of several posts |
| Bespoke Morning Lineup (product description) | https://www.bespokepremium.com/bespoke-member-plans/ | 2026-10-31 | Search summary only |
| Edelweiss morning note quoted in Business Standard (2012) | https://www.business-standard.com/article/markets/pre-market-markets-likely-to-open-on-a-cautious-note-112010900110_1.html | 2026-10-31 | Search summary only |
| Motilal Oswal "Morning India" PDFs (archived on dsij.in) | https://www.dsij.in/productAttachment/premarketreports/MORNING_INDIA-20250603-MOSL-MI-PG018.pdf | 2026-10-31 | **Not read.** The link returns DSIJ's home page, not the PDF. |

**Not found:**
- No published study of how traders read a morning note.
- No CFA Institute text that requires the conclusion first. Its Standards require a reasonable basis and a clear line between fact and opinion, which is a different point.
- No primary text from an Indian broker's daily note. The Motilal Oswal PDF would not download; Kotak and HDFC Securities notes did not turn up.
- No published method for "when this happened before" studies. SentimenTrader shows its practice, not its method.

## Findings

**1. People scan; the conclusion has to come first.** In Nielsen's tests, 79% of users scanned a new page and 16% read it word by word. On the same content, concise text was 58% more usable, scannable text 47%, objective text 27%, and all three together 124%. Schade (2018): readers often stop after a paragraph or a sentence, so the one thing they must take away goes first, then supporting points in falling order of importance. The military calls this BLUF, from AR 25-50.
→ Our brief opens with a conclusion, but the agent card puts the whole brief into one paragraph, so it can't be scanned. That is a rendering failure, not a writing one.

**2. A number needs a comparison to mean anything.** Few (2007): a value on its own says little until you ask "compared to what?" A monitoring display should give an overview first, show what needs attention, and offer detail only on request.
→ The scorecard's "normal" column is right. The detail sections are not: they put 40 lines of raw numbers, with no comparison, right below the read.

**3. Professional notes give a view on every item, ranked by materiality.** The sell-side template and the Reuters note agree on the shape:
- a "top call" headline;
- a few items, each "what happened → why it matters";
- today's events with exact times;
- optional trade ideas, each with a thesis, catalyst, risk and exit;
- under two minutes to read, one page;
- "no news" is a valid note, and filler is not;
- data is timestamped;
- past calls that were wrong are owned.

The Reuters note ends with "Today's events to watch" and a chart of the day. Bespoke's pre-open note covers news, market internals, charts and the day ahead. The Indian notes we found centre on levels relative to moving averages, global cues, the expected opening, and FII/DII flows.
→ We have the levels and flows. We are missing four things:
- (a) **Ranked items that each say what they mean.** The "just data" complaint.
- (b) **A calendar of what's coming.** Ours says "no event held" when NSE expiry, results and the ban list are all on disk.
- (c) **Anything about individual stocks or sectors.** Movers, new highs, deals and delivery spikes are held but not used.
- (d) **A look back.** No check of yesterday's read against what happened.

**4. Use the outside view, and always say how many cases it rests on.** Lovallo and Kahneman argue that a forecast based only on the case in front of you tends to be over-confident. They recommend taking a reference class of similar past cases and looking at the spread of their outcomes. They also say choosing that class "involves both art and science". SentimenTrader's precedent studies report:
- how many past cases there were;
- results over several horizons;
- win rates against a random baseline;
- the worst drawdown along the way;
- a warning when the sample is small.

They also merge signals that fall close together, so one episode isn't counted many times.
→ A "what history says" section is supported, if it shows how many cases it is based on, merges cases from the same episode, uses several horizons, and states plainly that it is history, not a forecast.

**5. Keep fact and opinion apart.** CFA Standards require a clear line between fact and opinion. The sell-side template asks for an opinion on every item, so both are needed, but labelled.
→ Each item should state the fact, then a rule-based "what it means", then the model's note under its own label. That is the split we already use; it should apply per item, not only at the end.

## Decision (proposed; needs the operator's approval before building)

Three separate outputs, each answer-first and built as structured data so the page and Telegram can each lay it out properly:

**A. Pre-open brief** (target: readable in two minutes, one phone screen before any expanding)
1. **Headline:** the view in one sentence, plus a regime tag, the data's as-of time and a completeness flag.
2. **Three things that matter today**, ranked by how much they matter. Each is a fact with its number against normal, then "what it means" from rules. If nothing matters, it says so.
3. **Levels and scenarios:** the expected range; above X it means this, below Y it means that, and what would change the read.
4. **What history says:** past days with the same conditions, Nifty over the next 1, 5 and 20 sessions (median, share up, worst 10%), the number of cases, and a warning below 30 cases.
5. **Coming up:** expiry, results due, the ban list, economic releases, each with its time.
6. **Your books:** anything that needs you, such as near a loss limit, a rebalance due, a holding on the ban list, or results due on a held stock. Then each book's day.
7. **Under the hood** (collapsed): the scorecard, sectors, movers, flows, deals.
8. **Detail** (collapsed): the raw numbers.

**B. After-close note**
1. Headline: what the day was.
2. **Yesterday's read against what happened:** each trigger hit or not, and whether the range held. This is the "own your mistakes" part.
3. **Why it moved:** sectors, breadth, flows, deals and the biggest movers.
4. **What changed in the read**, if anything.
5. **Your books:** day P&L and what each will do tomorrow.
6. Tomorrow's calendar.

**C. Agent notes (the cards and alerts)**
- The title is the conclusion, not a label: "india_sharpe_momentum_opt is 9.4% below its peak, near its 10% reduce-only level", not "Note".
- One line on why, then one action or link.
- Never the full text of a report. A brief shows as its headline and chips, with "Open brief".
- Line breaks kept; the same note is not repeated.

**Telegram:** the headline, the three items, levels and books in at most 8 lines, with a link to the workbench for the rest.

**Rendering:** the page draws the structure (cards, chips, tables, collapsed sections) from the data, never from parsing the text.

## Open questions for the operator

1. Should the brief carry scenario lines like "above 23,255 the trend read flips"? They are conditions, not orders. Or should it stop at levels?
2. Should "What history says" go in the first version, or come later after its own check? It needs care: merging overlapping cases, a minimum case count, no look-ahead.
3. After-close note: keep the 12:00 IST cut-off between "pre-open" and "after-close", or tie it to the market's actual close?
4. Which notes should reach Telegram: only alerts that need action, or every brief as well?
