# ADR-105: The market brief reads like a morning note, and only on trading days

- **Context:** The operator found the brief unreadable ("is this readable?", 2026-10-31): the agent card squashed it into one paragraph. They also found it "just data". Research 134 found professional notes lead with a view, rank a few items by how much they matter, say what each means, list what is coming with times, and flag what needs the reader. The brief also ran when nothing was trading: the 31 Oct Saturday brief repeated Friday's numbers. And the 16:15 after-close brief ran before the 19:30 data job, so it reported the previous day's close.
- **Options:** (a) Restyle the text. (b) Build the brief as data in the reading order research 134 found, draw it in the workbench from the data, and send a short form to Telegram. (c) Let a model write the whole note.
- **Choice:** (b). `agents/brief_content.py` builds, by rule and from held data only:
  - the three things that matter, ranked by how far each signal is from its own history, each with what it means;
  - coming up: expiry, the F&O ban list, IPOs, results due from NSE board-meeting intimations, economic releases;
  - what in the books needs the operator;
  - what is moving underneath;
  - after the close, this morning's read against what happened.

  `market_brief.build_brief` saves it as `data.brief`. The AI tab's Market brief view (`MarketBriefView.tsx`) draws it with folded sections. The agent card shows the headline, three titles and "Open the brief". Telegram gets at most eight lines. No brief runs on a weekend or an NSE holiday (`make holidays`) unless forced. Pre-open versus after-close follows the 15:30 close. The after-close note now runs in `make daily` after the closes, flows and calendar are in. The analyst note answers three fixed questions, as before.
- **Why:** (c) cannot be checked line by line, and the model would write the facts the reader relies on. With (b), every number has a rule and a date, and the model only comments under its own label. Drawing from data, not parsed text, is what lets the page fold, colour and link.
- **Cost if wrong:** The ranking weights are ours (25-point cut-off, valuation halved, PCR change capped at 50), not measured (A-086). A wrongly ranked item still shows its number against normal. The results calendar is only as complete as the days captured since 2026-10-31, and the brief says so.
