# HOW_TO_ANSWER — the rules for answering about markets, strategies and risk

For the assistant, the market brief's analyst note, the knowledge agent, and anyone writing a note
for the operator. Research 134 records where each rule comes from. The metric pages in this folder
hold the facts each rule needs.

## The order of an answer

1. **The answer first, in one sentence.** What it means, not what the number is. NN/g found 79%
   of readers scan, and many stop after the first sentence (research 134).
2. **The two or three numbers behind it.** Each one against what is normal for it: a percentile,
   a median, a range or a threshold, with its window ("71st percentile of the past year").
   A number without a comparison is not an answer (Few, research 134).
3. **What it does not tell you, if the question invites a wrong reading.** For example, a high
   VIX says moves will be large, not which way.
4. **What would change the answer**, as a number or an event, when there is one.
5. **Where it came from**: the metric page, the tool, the date of the data.

Keep it short. Concise and scannable text was 124% more usable than the same content written
conventionally (Nielsen 1997, research 134).

## Rules

- **Every number from a tool or a metric page.** Never from memory. If it is not held, say so.
- **Every number with its date.** Data from yesterday's close is said to be yesterday's close.
- **Against normal, always.** Use the payload's percentile when it has one; otherwise the "What is
  normal" line on the metric page, with that page's as-of date.
- **Fact, then meaning, then opinion, each labelled.** Rule-based meanings come from the metric
  page's "How to read it". A model's own view is marked as such (CFA Standards: keep fact and
  opinion apart).
- **The outside view when history is used.** Say how many past cases a statement rests on. Under
  30, say it is too few to lean on.
- **No buy or sell advice and no price predictions.** Conditions ("a close above 23,255 would
  flip the trend read") are allowed; instructions ("buy above 23,255") are not.
- **Name the trap if there is one.** Each metric page lists its traps; use the one that applies
  to the question.
- **Say "nothing notable" when nothing is.** Filler is worse than a short answer.
- **Plain words.** Expand jargon the first time: "put-call ratio (open puts over open calls)".

## Words to use and avoid

| Use | Avoid | Why |
|---|---|---|
| "held long", "share of contracts long" | "+11% long" | reads like a change |
| "71st percentile of the past year" | "high" alone | high against what |
| "the gate killed it" | "it failed this time" | killed strategies are not resubmitted |
| "a condition", "would flip the read" | "target", "will reach" | no predictions |
| "our Sharpe (no cash rate subtracted)" | "Sharpe" when comparing with outside figures | A-083 |

## Worked examples

**Q: How is the market today?**

A: Risk-off underneath a steady index. Nifty 50 rose 0.5% but only 16% of stocks are above their
50-day average, near the bottom 5% of the past year (median 39%), with 206 new lows against 26 new
highs. India VIX is 15.3, the 71st percentile of the past year, so swings are expected to be larger
than usual. A Nifty close above its 50-day average (23,255) with breadth back above 30% would change
that read. Data: 30 Oct close.

**Q: Is my strategy good? Sharpe 1.4.**

A: Not proven yet. Against the noise bar for the trials logged (1.88 with the assumed spread), pure
noise would be expected to look better than 1.4 somewhere in the search. Our Sharpe also does not
subtract a cash rate, which flatters it. The gate's deflated Sharpe and PBO decide; ask for those.

**Q: FIIs sold ₹5,000 crore today. Should I worry?**

A: One day is weak evidence. FIIs sold on the median day this past year (−₹1,305 crore), and a
₹5,000 crore sale is inside the usual range (the worst 5% of days were beyond −₹8,692 crore). The
5-day sum and whether the selling continues say more. This is context, not a trading signal
(research 104).
