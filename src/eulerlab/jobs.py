"""The scheduled jobs: what runs, when, and why then.

One table, read by two schedulers. `tools/schedule_daily.py` writes each job
as a macOS launchd plist, which is how the operator's Mac has run them since
2026-11-01. `eulerlab.scheduler` runs the same table as a long-lived process,
which is how a server or a container runs them (ADR-164). The table lives
here, in `src/`, so neither copy can drift from the other.

Times are IST wall-clock. `weekdays` uses launchd's numbering, 1 is Monday and
7 is Sunday, which is also Python's `isoweekday()`. Empty means every day.
`hours` lists several runs a day at `minute` past each hour.

`catch_up` says what to do when the scheduler was down at the appointed
minute. A data pull is worth running late: a gap in market history cannot be
bought back. A message tied to a clock, or a sweep of live prices at 09:16, is
not: run hours late it would mislead, so it is skipped and reported instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

WEEKDAYS = (1, 2, 3, 4, 5)
"""launchd's numbering: 1 is Monday."""
SUNDAY = 7
"""launchd takes 0 or 7 for Sunday; 7 keeps `if weekday` true in `_when`."""


@dataclass(frozen=True)
class Job:
    name: str
    label: str
    command: str
    """Run by a login shell in the repo. `{repo}` is filled in."""
    hour: int
    minute: int
    weekdays: tuple[int, ...]
    """Empty means every day."""
    log: str
    what: str
    why_then: str
    hours: tuple[int, ...] = ()
    """When set, one run at `minute` past each of these hours, every day."""
    catch_up: bool = True
    """Run a missed slot late (within `scheduler.GRACE`), or skip it and say so."""

    @property
    def plist_path(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{self.label}.plist"


JOBS = {
    "daily": Job(
        name="daily",
        label="com.eulerlab.daily",
        command="{repo}/tools/daily_guard.sh",
        hour=19,
        minute=30,
        weekdays=(),
        log="daily",
        what="make daily, every day",
        why_then=(
            "19:30 IST is the default because NSE bhavcopy and the AMFI NAV file are\n"
            "both published in the evening. Running earlier fetches yesterday."
        ),
    ),
    "india-live": Job(
        name="india-live",
        label="com.eulerlab.indialive",
        command="cd {repo} && make india-live",
        hour=15,
        minute=31,
        weekdays=WEEKDAYS,
        log="india_live",
        what="make india-live, Monday to Friday",
        why_then=(
            "15:31 IST is one minute after the NSE close. It retries every 10 minutes until\n"
            "the bhavcopy and the minute bars are in, or 21:00, using minute bars as\n"
            "provisional daily bars meanwhile (ADR-079). It exits at once on an NSE holiday."
        ),
    ),
    "depth": Job(
        name="depth",
        label="com.eulerlab.depth",
        command="cd {repo} && make depth-day",
        hour=9,
        minute=10,
        weekdays=WEEKDAYS,
        log="depth",
        what="make depth-day, Monday to Friday",
        why_then=(
            "09:10 IST is five minutes before the open. It records Kite's five-level depth\n"
            "for the Nifty 50 until 15:31, then uploads the day to B2 and deletes the local\n"
            "copy only after the size and SHA-256 match (ADR-095). It needs a Kite token\n"
            "made that morning; without one it says so and exits."
        ),
        catch_up=False,
    ),
    "gap-signal": Job(
        name="gap-signal",
        label="com.eulerlab.gapsignal",
        command="cd {repo} && make gap-signal SCHEDULED=1",
        hour=15,
        minute=20,
        weekdays=WEEKDAYS,
        log="gap_signal",
        what="make gap-signal SCHEDULED=1, Monday to Friday",
        why_then=(
            "15:20 IST is ten minutes before the close: late enough that the day's candle\n"
            "and VIX are nearly final, early enough to act. It needs a Kite token made that\n"
            "day; without one the message says so."
        ),
        catch_up=False,
    ),
    "fundamentals": Job(
        name="fundamentals",
        label="com.eulerlab.fundamentals",
        command="cd {repo} && make fundamentals-update",
        hour=10,
        minute=0,
        weekdays=(SUNDAY,),
        log="fundamentals",
        what="make fundamentals-update, every Sunday",
        why_then=(
            "Company fundamentals change quarterly and the fetch walks every company for\n"
            "hours, so it left the nightly job on 2026-10-13. Sunday morning keeps it clear\n"
            "of the 19:30 daily run and of market hours. It can also be run by hand."
        ),
    ),
    "agents-preopen": Job(
        name="agents-preopen",
        label="com.eulerlab.agentspreopen",
        command="cd {repo} && make agents-preopen",
        hour=8,
        minute=45,
        weekdays=WEEKDAYS,
        log="agents_preopen",
        what="make agents-preopen, Monday to Friday",
        why_then=(
            "08:45 IST is 15 minutes before the pre-open session: the data and operations\n"
            "agents check last night's run and the market brief goes out before 09:00 (ADR-085).\n"
            "Then the three heads split and check tasks and plan the day, and the\n"
            "work runner starts the tasks that may run by themselves (ADR-124)."
        ),
    ),
    "brief-weekend": Job(
        name="brief-weekend",
        label="com.eulerlab.briefweekend",
        command="cd {repo} && make agent NAME=market_brief",
        hour=9,
        minute=30,
        weekdays=(6, SUNDAY),
        log="brief_weekend",
        what="the market brief agent, Saturday and Sunday",
        why_then=(
            "On a closed day the brief is a markets-closed note: the last session's read,\n"
            "the week in review and the week ahead (ADR-105). One per break: Sunday's run\n"
            "finds Saturday's note and stops. Weekday holidays get theirs from the 08:45 run."
        ),
    ),
    "agents-close": Job(
        name="agents-close",
        label="com.eulerlab.agentsclose",
        command="cd {repo} && make agents-close",
        hour=16,
        minute=15,
        weekdays=WEEKDAYS,
        log="agents_close",
        what="make agents-close, Monday to Friday",
        why_then=(
            "16:15 IST is 45 minutes after the close, once india-live has its first pass:\n"
            "the after-close brief, book drift and step timings for the day."
        ),
    ),
    "factors-weekly": Job(
        name="factors-weekly",
        label="com.eulerlab.factorsweekly",
        command="cd {repo} && make factors-weekly",
        hour=6,
        minute=0,
        weekdays=(SUNDAY,),
        log="factors_weekly",
        what="make factors-weekly, every Sunday",
        why_then=(
            "Sunday 06:00 IST, no session and before agents-weekly at 07:00: this year's\n"
            "corporate actions landed again and both factor files rebuilt, swapped in only\n"
            "if no earlier row changes (T-4615). They were stale from 2026-08-19 to 11-14."
        ),
    ),
    "agents-weekly": Job(
        name="agents-weekly",
        label="com.eulerlab.agentsweekly",
        command="cd {repo} && make agents-weekly",
        hour=7,
        minute=0,
        weekdays=(SUNDAY,),
        log="agents_weekly",
        what="make agents-weekly, every Sunday",
        why_then=(
            "Sunday 07:00 IST, before the 10:00 fundamentals job: the Quantpedia sync, the\n"
            "knowledge index and the code review. Research and the idea lab moved to the\n"
            "daily agents-ideas job (ADR-111)."
        ),
    ),
    "agents-ideas": Job(
        name="agents-ideas",
        label="com.eulerlab.agentsideas",
        command="cd {repo} && make agents-ideas",
        hour=17,
        minute=0,
        weekdays=(),
        log="agents_ideas",
        what="make agents-ideas, every day",
        why_then=(
            "17:00 IST, after india-live (15:31) and agents-close (16:15) have the day's prices,\n"
            "and with the idea lab's 90-minute limit, done before the 19:30 daily run.\n"
            "Research first, so the lab tests the day's drafts; the lab's feedback steers\n"
            "the next day's research (ADR-111). Weekends too: ideas do not need a session.\n"
            "The heads and the work runner go first, so the day's tasks are done (ADR-124)."
        ),
    ),
    "live-shadow-open": Job(
        name="live-shadow-open",
        label="com.eulerlab.liveshadowopen",
        command="cd {repo} && make live-shadow-open",
        hour=9,
        minute=16,
        weekdays=WEEKDAYS,
        log="live_shadow",
        what="make live-shadow-open, Monday to Friday",
        why_then=(
            "09:16 IST, a minute after the open: the official open is set and the book has\n"
            "quotes. It prices the evening plan's candidates on Kite and sends nothing (ADR-153).\n"
            "A holiday has no plan for the day, so the run records that and stops."
        ),
        catch_up=False,
    ),
    "live-shadow-close": Job(
        name="live-shadow-close",
        label="com.eulerlab.liveshadowclose",
        command="cd {repo} && make live-shadow-close",
        hour=15,
        minute=10,
        weekdays=WEEKDAYS,
        log="live_shadow",
        what="make live-shadow-close, Monday to Friday",
        why_then=(
            "15:10 IST: an MIS position must be closed before the broker squares it off\n"
            "from 15:12, so this is the last price a real intraday book could exit at."
        ),
        catch_up=False,
    ),
    "live-shadow-evening": Job(
        name="live-shadow-evening",
        label="com.eulerlab.liveshadowevening",
        command="cd {repo} && make live-shadow-evening",
        hour=22,
        minute=30,
        weekdays=(),
        log="live_shadow",
        what="make live-shadow-evening, every day",
        why_then=(
            "22:30 IST, after the 19:30 daily run and the 22:00 data agent have the day's\n"
            "bhavcopy and delivery: reconcile today's sweeps, then plan the next session.\n"
            "Every day, so Friday's and Sunday's runs both leave a plan for Monday."
        ),
    ),
    "data-watch": Job(
        name="data-watch",
        label="com.eulerlab.datawatch",
        command="cd {repo} && make agent NAME=data",
        hour=6,
        minute=0,
        weekdays=(),
        hours=(6, 8, 10, 12, 14, 16, 18, 20, 22),
        log="data_watch",
        what="the data agent, every two hours from 06:00 to 20:00 IST, and at 22:00",
        why_then=(
            "Every two hours from 06:00 to 20:00 IST, as the operator asked (2026-11-04): grade,\n"
            "re-run what is behind, upload and clear local copies, merge what differs. The 20:00\n"
            "run usually finds make daily holding the feed lock and leaves upkeep to the next.\n"
            "22:00 added the same day (HISTORY #77): NSE sometimes publishes the F&O bhavcopy\n"
            "after the 19:30 nightly run, and the 22:00 run, past the 21:00 'due tonight' cut,\n"
            "re-runs it the same night instead of waiting for 06:00."
        ),
    ),
}
