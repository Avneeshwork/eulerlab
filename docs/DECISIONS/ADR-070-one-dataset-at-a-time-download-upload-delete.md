# ADR-070 — The nightly job handles one dataset at a time: download, upload, delete

**Context.** Operator, 2026-10-13: "data 1 download, upload it, delete from
local, then data 2", and "make fundamental data weekly or on demand". `make
daily` downloaded from every source, then uploaded and pruned once, as its
last steps, behind a fundamentals fetch that took over ten hours on 8 October.
The run of 13 October was stopped after 74 minutes with nothing uploaded, and
the whole time it held the `feed` lock that the Instruments button needs.

**Options.** (a) Leave the order and move only fundamentals. (b) Upload after
each download, delete at the end. (c) Download, upload and delete each dataset
before the next, and move fundamentals to its own job.

**Choice.** (c). `sync_cloud --only TREE... --then-delete`
(`make upload-tree TREES="..." DELETE=1`) uploads one landing folder, listing
only that folder's part of the bucket, then removes the local files a fresh
listing shows there at the same size (`prune_local.prune_tree`). `daily-run`
calls it after every download. Fundamentals left the nightly job:
`make fundamentals-update` runs it, uploads and deletes, under its own lock;
launchd runs that on Sunday at 10:00 (`make schedule JOB=fundamentals`).

**Why.** Disk is the scarce thing here (1.5 GB free on 13 October) and a run
can be stopped at any point; with (c) what is on disk is never more than one
dataset, and whatever was fetched is already in B2. Two folders are deleted a
few steps after their upload, not straight after it: the NSE files, which
market history, the price panel, Nifty options and the paper books read, and
the US files, which the US panel reads. Deleting them first would make each
build fetch them back from B2, and a network failure would then leave the
paper books a day behind, which is the failure of 8 October (T-4030).
Fundamentals change quarterly; a nightly ten-hour walk bought nothing.

**Cost if wrong.** Anything that reads landed files after the nightly job
fetches them back from B2 on demand: the minute-bar studies re-download about
1.9 GB, and the workbench re-fetches the calendar and fund files it shows
(seen within a minute of deleting them). That was already true after every
`prune-local`. The deletion rule is unchanged, so a wrong delete needs the
bucket's own listing to be wrong. The full `sync-cloud` and `prune-local`
still run last and catch whatever a step missed.
