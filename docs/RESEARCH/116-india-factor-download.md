# 116 — IIMA Indian factor data download

**Date:** 2026-10-21 · **Source release:** 2025-12 · **Status:** landed

## Source and selection

Downloaded the survivorship-bias-adjusted daily and monthly four-factor plus
market-return files from IIMA's Indian Fama-French and Momentum Data Library.
The library labels this its recommended series and says it is built from CMIE
Prowess DX. The published release covers October 1993 through December 2025.
IIMA notes that historical values can change between releases when the source
database changes, so each source release must remain a separate immutable
snapshot.

The files are direct CSV downloads linked by IIMA; the fetcher does not scrape
HTML tables. Raw bytes are stored under `data/landing/india_factors/` and
recorded in that tree's append-only landing manifest. The three tree objects
(two CSVs and the manifest) were mirrored to B2; a subsequent dry-run found
three matching remote objects and zero pending uploads.

## Landed files

| Frequency | Rows | Coverage | SHA-256 |
|---|---:|---|---|
| Daily | 8,004 | 1993-10-01 to 2025-12-31 | `32af19e5c55f493ee15c794cae145be5381762bbb4b1615227e7c9fc7f5a6f10` |
| Monthly | 387 | 1993-10 to 2025-12 | `c07a12d1c04630c18a7f87a96c91db6a7c4ebfc1e37f888e41fe8469fe234c44` |

Columns are `Date`, `SMB`, `HML`, `WML`, `MF`, and `RF`. Values are percentage
returns, not decimal returns. The initial October 1993 observations have
missing market and risk-free values. The file passed the landing-zone checksum
audit after download.

## Use and limits

Use daily factors for rolling stock exposure estimates and monthly factors for
long-run premium estimates and monthly validation. Convert percentage points to
decimal returns at the parser boundary. `MF` is the library's market premium;
`RF` is its risk-free series, which the IIMA FAQ says is based on RBI 91-day
Treasury bill yields. This is not the 10-year government yield proposed as a
separate risk-free input in the fair-value roadmap; the model must choose and
document one convention before computing cost of equity.

IIMA provides downloadable research data and a citation, but this download does
not establish rights to redistribute the data or derived investor-facing
outputs. Keep use internal pending a separate licensing review.

## Reproduction

Run `uv run python -m eulerlab.ingest.india_factors`. The fetcher validates the
CSV schema, retains raw bytes, writes atomically, and is idempotent for the
2025-12 release. Source page: <https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/>.

## References

- IIMA, [Indian Fama-French and Momentum Data Library](https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/).
- IIMA, [FAQ](https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/FAQ.php).
- Agarwalla, Jacob and Varma (2013), [Four factor model in Indian equities market](https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/four-factors-India-90s-onwards-IIM-WP-Version.pdf).
