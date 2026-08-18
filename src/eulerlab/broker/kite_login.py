"""`make kite-login` — walk the operator through obtaining an access token."""

from __future__ import annotations

import os
from pathlib import Path

from eulerlab.broker.kite_session import (
    SESSION_FILE,
    SessionError,
    exchange,
    extract_request_token,
    login_url,
    save,
)


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"kite-login: {name} is not set. Put it in .env (never .env.example).")
        raise SystemExit(2)
    return value


def main() -> int:
    api_key = _env("ZERODHA_API_KEY")
    api_secret = _env("ZERODHA_API_SECRET")

    print("Kite login\n")
    print("1. Open this URL and log in:\n")
    print(f"   {login_url(api_key)}\n")
    print("2. You will be redirected to your registered redirect URL, which will")
    print("   carry ?request_token=... in the address bar.")
    print("3. Paste that whole URL below (or just the token).\n")

    try:
        pasted = input("redirect URL: ")
    except (EOFError, KeyboardInterrupt):
        print("\ncancelled")
        return 130

    try:
        request_token = extract_request_token(pasted)
        session = exchange(api_key=api_key, api_secret=api_secret, request_token=request_token)
    except SessionError as exc:
        print(f"\nkite-login failed: {exc}")
        return 1
    except Exception as exc:  # network, TLS, malformed response
        print(f"\nkite-login failed: {exc}")
        return 1

    path = save(session, Path(SESSION_FILE))
    print(f"\nlogged in as {session.user_id}")
    print(f"token written to {path} (gitignored, mode 0600)")
    print("It expires at 06:00 IST tomorrow. Re-run this then.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
