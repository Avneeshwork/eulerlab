"""Password hashing with the standard library's scrypt: no dependency to add.

`scrypt$n$r$p$salt$hash`, salt and hash in URL-safe base64. Parameters travel
with the hash so they can be raised later without invalidating old ones.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

N, R, P = 2**14, 8, 1
MIN_LENGTH = 10


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    if len(password) < MIN_LENGTH:
        msg = f"a password needs at least {MIN_LENGTH} characters"
        raise ValueError(msg)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, dklen=32)
    return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    got = hashlib.scrypt(
        password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=32
    )
    return hmac.compare_digest(got, _unb64(digest))


def new_token() -> str:
    """A bearer secret: shown once, stored only as `token_hash`."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
