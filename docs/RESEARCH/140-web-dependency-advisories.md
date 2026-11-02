# 140 — Which `npm audit` findings in `web/` reach this workbench, and what fixes them?

**Date:** 2026-11-02 · **Confidence:** high on versions and counts (read from `npm audit --json` on this machine); high that the three critical Next.js advisories need `sharp` or a Windows host (the advisories say so); not checked: whether any remaining high advisory is reachable through the `/api` rewrite

## Question

T-4362: `npm install` in `web/` reported 19 vulnerabilities, 1 critical. Which can be fixed without a major upgrade, and do the rest apply to how the workbench runs (macOS, `next dev`/`next start`, App Router, one fixed `/api` rewrite to the Python API, no middleware, no `next/image`, no Server Actions)?

## Sources

| Source | URL | Fetched | Read |
|---|---|---|---|
| `npm audit --json` in `web/`, before and after | local | 2026-11-02 | Every advisory's package, range and fix |
| GHSA-2464-fhr4-w9xw (RCE, Image Optimization API, SVG) | https://github.com/advisories/GHSA-2464-fhr4-w9xw | 2026-11-02 | Affected and patched versions, conditions, workaround |
| GHSA-2xp9-vwfh-vxw4 (RCE, Image Optimization API, AVIF) | https://github.com/advisories/GHSA-2xp9-vwfh-vxw4 | 2026-11-02 | Same |
| GHSA-p293-qw3h-jr36 (RCE, Windows-hosted servers) | https://github.com/advisories/GHSA-p293-qw3h-jr36 | 2026-11-02 | Same |

## Findings

1. Next 14.2.5 carried 37 Next.js advisories (4 critical, 13 high). Next 14.2.35, the newest 14.2 release, carries 25 (3 critical, 9 high). `source-map-js` is fixed by `npm audit fix`. Totals: 19 vulnerable packages before, 21 after; the two extra are moderate `@typescript-eslint` packages pulled in by `eslint-config-next` 14.2.35.
2. Every remaining Next.js advisory is fixed only in 15.5.x or 16.x. The SVG one is open through 15.5.27, so a full fix is Next 16.4.1 or later, which needs React 19.
3. SVG (GHSA-2464): a memory bug in an image library "when Next.js runs on glibc-based Linux"; the workaround is `sharp` 0.35.5 or later. AVIF (GHSA-2xp9): a flaw in `libheif`, "which `sharp` uses". Windows (GHSA-p293): RCE "when the server is hosted on machines using a Windows filesystem".
4. `npm ls sharp` in `web/` is empty: `sharp` is not installed. The machine is macOS.
5. Every other remaining finding (16 packages) is in ESLint and its plugins, development tools that never ship in the served page. Their fix is ESLint 9 and a new `eslint-config-next`, both major upgrades.
6. `next dev` on the Mac listens on all interfaces (`*:3000`), so other devices on the same network can reach the workbench.

## Not found

No advisory text says whether the remaining high findings (rewrite SSRF, Server Component DoS) apply to an app whose only rewrite has a fixed destination. I did not test them.

## Decision

Take Next 14.2.35 and the non-breaking `npm audit fix` now (ADR-118). Leave Next 16 and ESLint 9 as their own tasks.

## Open questions

Should the workbench listen only on 127.0.0.1? That would cut every network-reachable advisory, but it would stop the UI working from a phone on the same network if the operator uses it that way.
