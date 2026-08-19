# "X is not set" when it plainly is set in .env

## Symptom

```
kite-login: ZERODHA_API_KEY is not set. Put it in .env (never .env.example).
make: *** [kite-login] Error 2
```

…while `.env` visibly contains a real value for that variable. The same shape
of failure appeared for `B2_KEY_ID` and `B2_APP_KEY` on the sync and build
commands.

## Diagnosis

Two distinct causes, both fixed in code on 2026-08-19. If either recurs, this
is what to look for.

**1. An empty variable exported in the shell shadows the file.**
`python-dotenv`'s `load_dotenv` does not replace a variable that already
exists in the environment, and an exported-but-*empty* variable still counts
as existing. A terminal that once ran `source .env` while the file held blank
placeholders — which it did during the credential rotation on 2026-08-18 —
keeps exporting those blanks for the life of that shell. Every later command
in that terminal sees the blank and never reads the file.

Confirm it without printing the secret:

```bash
python3 -c "import os; v=os.environ.get('ZERODHA_API_KEY'); print('exported:', v is not None, '| empty:', not (v or '').strip())"
```

If that prints `exported: True | empty: True`, this is the cause.

**2. Most entry points never loaded `.env` at all.** Only `kite_login` did.
`sync-cloud`, `build-master` and `build-factors` read `os.environ` directly,
so they worked only if the operator had run `set -a; source .env; set +a`
first — an undocumented step whose absence looked like missing credentials.

## Fix

The code now loads `.env` through `eulerlab.env.load_env()` in every entry
point, and treats an **empty** variable as unset so the file fills it. A
variable with a real value is still left alone, so `B2_KEY_ID=other uv run …`
keeps working for pointing at a different account.

Nothing needs doing for new shells. To clear a shell that is already polluted:

```bash
unset ZERODHA_API_KEY ZERODHA_API_SECRET B2_KEY_ID B2_APP_KEY
```

Opening a new terminal does the same thing.

## Prevention

- **Never read `os.environ` directly for a credential.** Use
  `eulerlab.env.require(name)`, which loads `.env` first and whose failure
  message names the shadowing case explicitly rather than just saying "not
  set".
- **Do not compute the repo root by counting `.parents[N]`.** The old
  `kite_login` used `parents[3]`, which is correct when running from `src/`
  and silently wrong once the package is installed non-editable into a venv —
  and the failure is a `.env` that is never found rather than an error.
  `find_repo_root()` searches upward for `pyproject.toml` instead.
- If an error message could describe two very different causes, say both. The
  original message was accurate about the environment and actively misleading
  about the cause.
