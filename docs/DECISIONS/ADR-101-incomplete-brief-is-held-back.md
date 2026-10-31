# ADR-101: An incomplete Trader's read says so first and is held back from Telegram

- **Context:** On 2026-10-31 the first brief in the new format (ADR-100) ran while the workbench API was down. Breadth, FII futures and options were missing, the read counted 4 signals instead of 7, and it went to Telegram looking like a full read; only a small note said otherwise. The operator agreed it should be fixed.
- **Options:** (a) Leave it; the note is there. (b) Flag the gap in the bottom line only. (c) Flag it in the bottom line, mark each missing row as missing, and hold the brief back from Telegram with one line naming what is missing.
- **Choice:** (c). The bottom line starts "Incomplete: N of 7 signals missing (names)"; each missing row reads MISSING, never neutral; Telegram gets "Brief held back: <names> missing. Full brief in the workbench." The full brief is still written to `data/agents` and shown in the workbench.
- **Why:** A phone reader sees only the message, so a partial read sent there reads as a full one. A held-back line costs nothing, and the next scheduled run, with the data back, changes the fingerprint and sends the full read.
- **Cost if wrong:** A signal that is missing for a long time (a feed down for days) keeps every brief off Telegram until it is fixed. The one line says which signal, so it is visible, not silent.
