# Architecture — what exists, as of 2026-08-18

A picture of the system as built, not as planned. Everything here runs today;
nothing in this document is aspirational. For what is *not* built, see
`STATE.md` and `docs/AI_BUILD_PLAN.md`.

---

## The whole system

```mermaid
flowchart TB
    subgraph SRC["External sources"]
        NSE["NSE archives<br/>bhavcopy + participant OI"]
        KITE["Kite Connect API<br/>minute candles, instruments"]
        SCR["screener.in<br/>fundamentals"]
    end

    subgraph FETCH["Fetch layer — polite, bounded, resumable"]
        F1["fetch.py<br/>rate limit, retries, never HEAD"]
        F2["kite_minute.py<br/>60-day chunks, 3 req/s"]
        F3["screener_fetch.py<br/>2.5s gap, stops on 403"]
    end

    subgraph LAND["Landing zone — immutable"]
        L1["landing.py<br/>atomic write, chmod 444, SHA-256"]
        MAN[("manifest.jsonl<br/>append-only ledger")]
        DISK[("data/landing/<br/>local working copy")]
    end

    subgraph CLOUD["Durability"]
        B2[("Backblaze B2<br/>bucket: eulerdata")]
        SY["sync_cloud.py"]
        PR["prune_local.py"]
        RS["restore_local.py"]
    end

    subgraph DERIVE["Derived"]
        UNI["universe.py<br/>point-in-time liquidity ranking"]
        VER["verify_landing.py<br/>checksum audit"]
    end

    NSE --> F1
    KITE --> F2
    SCR --> F3
    F1 --> L1
    F2 --> L1
    F3 --> L1
    L1 --> MAN
    L1 --> DISK
    DISK --> SY --> B2
    B2 -.confirms.-> PR
    PR -.deletes local.-> DISK
    B2 --> RS --> DISK
    MAN --> UNI
    DISK --> UNI
    MAN --> VER
    B2 -.pruned-file check.-> VER

    style LAND fill:#1a1a2e,stroke:#4a4a8a,color:#fff
    style CLOUD fill:#16213e,stroke:#4a4a8a,color:#fff
    style SRC fill:#2d1b2e,stroke:#8a4a6a,color:#fff
```

---

## Datasets

```mermaid
flowchart LR
    subgraph DONE["Complete"]
        D1["EOD bhavcopy<br/>5,736 files<br/>2015-01-01 → 2026-08-17"]
        D2["Participant-wise OI<br/>1,632 weekdays<br/>2020 → today"]
        D3["Kite 1-minute bars<br/>12,755 chunks · 411 symbols<br/>173M bars · 5 years"]
    end
    subgraph WIP["In progress"]
        W1["screener.in fundamentals<br/>~471 of 2,702 companies"]
    end
    subgraph NOT["Not started"]
        N1["Options chain recorder"]
        N2["Tick / second-level data"]
        N3["Trendlyne FII-DII archive"]
    end

    style DONE fill:#1b2e1b,stroke:#4a8a4a,color:#fff
    style WIP fill:#2e2a1b,stroke:#8a7a4a,color:#fff
    style NOT fill:#2e1b1b,stroke:#8a4a4a,color:#fff
```

---

## The write path — why a crash cannot corrupt anything

This is the most important invariant in the system. It survived a `SIGKILL`
mid-run and an out-of-disk crash, in both cases leaving zero partial files.

```mermaid
sequenceDiagram
    participant F as Fetcher
    participant T as temp file
    participant D as final path
    participant M as manifest.jsonl

    F->>T: write bytes
    F->>T: fsync
    F->>T: chmod 0444 (read-only)
    T->>D: os.replace (atomic)
    Note over D: file is now complete or absent<br/>never half-written
    F->>M: append row (after file is safe)
    Note over M: crash here = file with no row<br/>harmless, refetched next run<br/>never a row with no file
```

The ordering is deliberate. A manifest row without a file would make a re-run
*skip* data it does not have — silent loss. The reverse is harmless.

---

## The prune / restore loop

Local disk is a working copy, not the archive. B2 is the archive.

```mermaid
stateDiagram-v2
    [*] --> Landed: downloader writes
    Landed --> Uploaded: sync-cloud (size + SHA-256)
    Uploaded --> PrunedLocally: prune-local<br/>only if exact size match
    PrunedLocally --> Landed: restore-local<br/>verifies SHA-256 on the way back
    Landed --> Landed: check-landing re-hashes
    note right of PrunedLocally
        Manifest is never edited.
        A pruned file is still
        recorded as landed.
    end note
```

**The trap this created:** `verify_landing` originally treated any locally
absent file as data loss, and `universe.py` silently ranked on whatever
remained on disk — producing a confident, wrong answer. Both now check B2 or
raise. See ADR-010.

---

## Module map

```mermaid
flowchart TB
    subgraph shared["Shared foundations"]
        landing["landing.py<br/><i>immutability, manifest</i>"]
        fetch["fetch.py<br/><i>politeness, retries</i>"]
        cloud["cloud.py<br/><i>S3 protocol, sync_directory</i>"]
        config["config.py<br/><i>frozen Pydantic, extra=forbid</i>"]
    end

    subgraph nse["NSE ingest"]
        nse_urls["nse_urls.py<br/><i>legacy + UDiFF formats</i>"]
        nse_eod["nse_eod.py<br/><i>holiday vs failure logic</i>"]
        poi["participant_oi.py"]
        hol["holidays.py"]
    end

    subgraph kite["Kite"]
        ks["kite_session.py<br/><i>token exchange</i>"]
        km["kite_minute.py<br/><i>60-day chunking</i>"]
    end

    subgraph fund["Fundamentals"]
        sp["screener_parse.py<br/><i>6 sections + profile</i>"]
        sf["screener_fetch.py<br/><i>dated snapshots</i>"]
    end

    nse_urls --> nse_eod
    hol --> nse_eod
    fetch --> nse_eod
    fetch --> poi
    landing --> nse_eod
    landing --> poi
    ks --> km
    sp --> sf
    cloud --> landing
    config -.validates.-> cloud
```

---

## Operator commands

```mermaid
flowchart LR
    daily["make daily<br/><b>the one to schedule</b>"]
    daily --> e1["ingest-eod"]
    daily --> e2["ingest-oi"]
    daily --> e3["ingest-fundamentals"]
    daily --> e4["sync-cloud"]
    daily --> e5["prune-local"]

    verify["make verify<br/><b>the one to trust</b>"]
    verify --> v1["lint"]
    verify --> v2["types"]
    verify --> v3["tests"]
    verify --> v4["docs-check"]
    verify --> v5["state"]
```

Every ingest step is idempotent, so `make daily` is safe to run repeatedly and
a missed day self-heals on the next run. That property is what makes it
schedulable at all.

---

## Design rules the diagrams encode

1. **Raw bytes are never modified.** What lands is exactly what the source
   served — not re-compressed, not normalised. The landing zone is what makes a
   full rebuild possible when a parsing bug is found, and one will be.
2. **The manifest is the memory.** Idempotency and resumability come from an
   append-only ledger, never from in-process state, which is why any job
   resumes correctly after any kind of death.
3. **Failure and absence are different facts.** A 404 is `ABSENT`, a network
   error is `FAILED`. Conflating them is how data loss gets recorded as a
   holiday.
4. **Confirmed, not assumed.** Files are pruned only on an exact size match
   against the bucket, and restored only if the SHA-256 matches the manifest.
   "The sync command exited zero" is not evidence.
5. **Politeness is not optional.** Every fetcher is rate limited, retries are
   bounded, and a 403 stops the run rather than provoking harder retries.

---

## Known architectural gaps

| Gap | Consequence | Fixed by |
|---|---|---|
| No security master | Renamed and demerged tickers unresolved (ZOMATO→ETERNAL, TATAMOTORS→TMPV) | Sprint 3 |
| No bitemporal read API | Nothing yet prevents a backtest reading data it could not have had | Sprint 4 |
| Disk watchdog lives in the scratchpad | Dies with the session, not version controlled | should move into the repo |
| No DuckDB/query layer | Parquet files are queried ad hoc rather than through a curated store | ADR-003 defers this deliberately |
