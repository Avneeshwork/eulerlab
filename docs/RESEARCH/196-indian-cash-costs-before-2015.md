# 196 — Indian cash-equity costs before 2015

**Date:** 2026-11-14 · **Confidence:** medium on STT; low on the NSE transaction charge and stamp duty

**Question.** What did a cash-equity trade on NSE cost between 2000 and 2014, so research can run on the 2000-2014 history (T-4613)?

**Sources** (fetched 2026-11-14 by the project's cloud session; not re-fetched from this Mac):
- STT history: MPRA working paper, "Evolution of Security Transaction Tax in India", https://mpra.ub.uni-muenchen.de/40165/1/Evolution_of_Security_Transaction_Tax_in_India.pdf
- STT cut from 1 July 2012: Calcutta Stock Exchange notice of 20 June 2012, https://www.cse-india.com/upload/CSE%20Notices%20&%20Circulars/2012/Notice200612.htm
- NSE cash transaction charge cut from 1 October 2009: Business Standard, 8 Sep 2009, https://www.business-standard.com/article/markets/nse-to-cut-trading-charges-by-10-per-cent-109090800004_1.html
- Stamp duty before July 2020 (state-wise): CSE FAQ, https://www.cse-india.com/upload/FAQ/STAMP%20DUTY%20FAQS.pdf ; Business Standard, 24 Mar 2011 (about 0.0024% on average)
- Service tax rates: Wikipedia, "Service tax (India)"

**Findings.**
- STT, delivery both sides / intraday sell: none before 2004-10-01; 0.075% / 0.015% to 2005-05-31; 0.1% / 0.02% to 2006-05-31; 0.125% / 0.025% to 2012-06-30; 0.1% / 0.025% from 2012-07-01.
- NSE cash transaction charge: Rs 3.5 a lakh (0.0035%) to 2009-09-30, then a Rs 3.0-3.25 slab; 0.00325% used.
- Stamp duty: by state before July 2020. Maharashtra delivery 0.01%, square-up 0.002%, used for every trade.
- Service tax on brokerage and charges: 10.2% from 2004-09-10, 12.24% from 2006-04-18, 12.36% from 2007-05-11, 10.3% from 2009-02-24, 12.36% from 2012-04-01, 14% from 2015-06-01. Before 2004-09-10, 8% used.

**Not found.** The NSE circular for the 2009 change; the SEBI turnover fee before 2015; F&O rates before 2015 (not needed: the scope trades cash stocks and index ETFs only).

**Decision.** `costs/schedule.py` gains dated entries from 2000-01-01. Operator's rule: each rate is the higher of its dated rate and today's, so an old year is never cheaper than trading today. In effect the old years pay today's rates, except STT on delivery at 0.125% from June 2006 to June 2012 and the NSE charge at 0.0035% to September 2009 and 0.00325% after. The cost model has no spread term (STUBS S-025), and spreads before 2010 were wider, so old-year costs are still understated.

**Open questions.** The NSE and SEBI circulars themselves; stamp duty for brokers outside Maharashtra.
