# ADR-119: The workbench moves to Next 16, React 19 and ESLint 9

- **Context:** After ADR-118 (Next 15.5.28), `npm audit` still listed 1 high (the PostCSS Next bundles) and 19 moderate, one in Next itself. The operator asked for every audit task left (2026-11-02), which includes T-4379.
- **Options:** (a) Stay on Next 15. (b) Next 16.4.3 with React 19.3.1, and ESLint 9 with `eslint-config-next` 16, which drops `next lint`.
- **Choice:** (b). ESLint moves to a flat config (`web/eslint.config.mjs`, the same `next/core-web-vitals` set) and `npm run lint` runs `eslint .`. Three React Compiler rules new in `eslint-plugin-react-hooks` 7 are off (48 findings in code ESLint 8 passed), to adopt later (T-4393). The command palette opens a company page with `router.push`, as the new Next rule asks.
- **Why:** 0 critical and 0 high; the 16 moderates left are one minimatch advisory inside the ESLint toolchain, fixed only in minimatch 11, which the plugins cannot load. Build, typecheck, lint and web tests pass; both pages render in a browser with no page errors.
- **Cost if wrong:** React 19 changes some behaviour (stricter effects in development, ref handling). Screens not opened against live data after this upgrade may misbehave until checked on the Mac.
