# ADR-119: The workbench listens on 127.0.0.1 only

- **Context:** `next dev` on the Mac listened on every interface (`*:3000`, Next's default 0.0.0.0). Any device on the same network could open the workbench and, through its `/api` rewrite, every API route, including deploy, kill switch and broker login, with no authentication; on 2026-11-02 `/terminal` and `/api/mode` both answered 200 at the Mac's LAN address. The API itself already bound 127.0.0.1 (uvicorn's default). On 2026-11-02 the operator said they use the workbench "mac only".
- **Options:** (a) Bind the UI to 127.0.0.1. (b) Keep 0.0.0.0 and add a login. (c) Leave it as it is.
- **Choice:** (a). `-H 127.0.0.1` on `next dev` and `next start` in `web/package.json`, which `make ui`, `make ui-fast`, `make workbench` and `.claude/launch.json` all run.
- **Why:** One flag removes the exposure. A login would be new code to get right, for a use the operator does not have.
- **Cost if wrong:** Opening the workbench from a phone or another machine stops working; it would need an SSH tunnel or a login (option b). `http://localhost:3000` (the Kite callback) still works: tested with curl against a 127.0.0.1-only listener on the Mac (localhost 200, `[::1]` refused, the LAN address refused). Browsers were not tested; they fall back from `::1` the same way.
