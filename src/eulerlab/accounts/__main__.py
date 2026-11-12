"""`make account-*`: add a workspace, a user, a membership or an API token (ADR-168).

python -m eulerlab.accounts workspace NAME
python -m eulerlab.accounts user EMAIL WORKSPACE ROLE     (asks for the password)
python -m eulerlab.accounts token EMAIL WORKSPACE NAME    (prints the token once)
"""

from __future__ import annotations

import getpass
import sys

from eulerlab import accounts, db
from eulerlab.accounts import store


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args == ["secret-key"]:
        from eulerlab.accounts import secrets

        print(f"{secrets.KEY_VAR}={secrets.new_key()}")
        print("Put that line in .env. Keep a copy: without it stored keys cannot be opened.")
        return 0
    if not db.configured():
        print(f"accounts live in the database: set {db.ENV_VAR} first")
        return 2
    db.migrate()
    match args:
        case ["workspace", name]:
            print(f"workspace {store.add_workspace(name)}")
        case ["user", email, workspace_id, role] if role in accounts.ROLES:
            try:
                user_id = store.user_id_for(email)
            except LookupError:
                password = getpass.getpass(f"password for {email}: ")
                user_id = store.add_user(email, password)
            store.grant(user_id, workspace_id, role)
            print(f"{email} is {role} of {workspace_id}")
        case ["token", email, workspace_id, name]:
            token = store.create_token(store.user_id_for(email), workspace_id, name)
            print(f"API token (shown once; send as 'Authorization: Bearer ...'):\n{token}")
        case _:
            print(__doc__)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
