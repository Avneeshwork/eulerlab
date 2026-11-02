# ADR-118: The workbench moves from Next 14.2.5 to Next 15.5.28

- **Context:** `npm audit` in `web/` (2026-11-02, T-4362) listed 19 advisories, 1 critical. Every Next.js advisory against 14.x is fixed only in 15.5.x or later; no 14.2 release fixes them (14.2.35, the last, still has them). The worst were remote code execution in the image optimiser (GHSA-2464-fhr4-w9xw, fixed in 15.5.28) and server-side request forgery in rewrites (GHSA-p9j2-gv94-2wf4); the workbench proxies `/api/*` through a rewrite.
- **Options:** (a) Stay on 14.2.x and rely on the UI being local. (b) Next 15.5.28, the first release with no critical or high Next advisory, still on React 18. (c) Next 16, which also clears the remaining moderates but is a second major step.
- **Choice:** (b), with `eslint-config-next` at the same version. The one code change: the company page reads its symbol with `useParams`, because Next 15 passes a page's `params` as a promise.
- **Why:** It removes the critical and every high Next advisory with one page changed; `npm run build`, typecheck, lint and the web tests pass, and both pages render in a browser with no page errors.
- **Cost if wrong:** Left open (T-4379): one high in the PostCSS copy Next bundles for building our own CSS, one moderate in Next itself, and 18 moderates in the ESLint 8 toolchain, which is never shipped. Clearing them needs Next 16 and ESLint 9.
