# Runbook — `make kite-login` problems

**What it does.** Walks the operator through exchanging a Zerodha
`request_token` for an `access_token`, per `src/eulerlab/broker/kite_session.py`.

---

## "ZERODHA_API_KEY is not set" even though `.env` has it

**Symptom.** `make kite-login` exits immediately with that message, even
though `ZERODHA_API_KEY` and `ZERODHA_API_SECRET` are both filled in `.env`.

**Cause.** Nothing in the repo ever loaded `.env` into the process
environment. The Makefile runs `uv run python -m eulerlab.broker.kite_login`
directly, with no `source .env` step, and `kite_login.py` read `os.environ`
straight — so unless your shell happened to have those vars exported already,
they were simply never there.

**Fix.** `kite_login.py` now calls `load_dotenv(REPO_ROOT / ".env")` at the
top of `main()`, using `python-dotenv`. No shell setup required; running
`make kite-login` from a clean shell is enough.

## Login URL uses the wrong API key / Kite rejects the checksum

**Symptom.** Login proceeds, but the printed `api_key=` in the login URL
looks wrong, or the token exchange fails with a Kite-side rejection.

**Cause.** `.env` values were quoted, e.g. `ZERODHA_API_KEY="rbg8fp2..."`.
`python-dotenv` (like most `.env` readers) treats the quotes as literal
characters when they don't wrap the *entire* unescaped value the way a shell
would strip them, so the key ended up with `"` characters baked into it —
19 characters instead of 16, and rejected by Zerodha.

**Fix.** No quotes around values in `.env`. Plain
`ZERODHA_API_KEY=your_key_here`.

**Prevention.** `.env.example` documents every key but must stay empty
(enforced by `tests/test_no_secrets.py`); it gives no example of formatting.
When adding a new secret to `.env`, write it unquoted.
