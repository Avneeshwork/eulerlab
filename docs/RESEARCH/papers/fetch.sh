#!/usr/bin/env bash
# Populate this folder from the sources named in README.md.
#
# The PDFs are NOT committed. arXiv is a permanent public archive, so a 1.1 MB
# binary in git buys nothing that one request does not — and the pre-commit
# large-file guard is right to refuse it. Retrievability is the property worth
# having, so this script is the artifact and the PDFs are its output.
set -euo pipefail
cd "$(dirname "$0")"

fetch() {  # url, filename
  if [ -f "$2" ]; then echo "have $2"; return; fi
  echo "fetching $2"
  curl -sSL -A "Mozilla/5.0" "$1" -o "$2"
}

fetch "https://arxiv.org/pdf/2605.04004" "mesfin-2026-arxiv-2605.04004-intraday-falsification.pdf"
# Research 071. A third-party copy of the working paper, and the authors' university repository.
fetch "https://c.mql5.com/forextsd/forum/173/intraday_momentum_-_the_first_half-hour_return_predicts_the_last_half-hour_return.pdf" "gao-2015-intraday-momentum-first-half-hour.pdf"
fetch "https://alexandria.unisg.ch/server/api/core/bitstreams/a99aba00-f967-49b3-aceb-f544dc386e0b/content" "zarattini-2025-beat-the-market-spy.pdf"

echo
echo "Not fetchable — SSRN returns 403 to scripts. Drop these in by hand if you have access:"
echo "  Zarattini, Barbon & Aziz (2024)  SSRN 4729284  — orb_in_play is coded from summaries"
echo "  Maroy (2025)                     SSRN 5095349  — not coded"
