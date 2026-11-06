"""A response body cut short is a retryable transport error, not a crash."""

from __future__ import annotations

import http.client
from typing import Any

import pytest

from eulerlab.ingest.fetch import TransportError, UrllibTransport


class _Short:
    status = 200

    def __enter__(self) -> _Short:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        raise http.client.IncompleteRead(b"partial", 1)


class _Opener:
    def open(self, *_: Any, **__: Any) -> _Short:
        return _Short()


def test_incomplete_read_becomes_a_transport_error() -> None:
    transport = UrllibTransport()
    transport._opener = _Opener()  # type: ignore[assignment]
    with pytest.raises(TransportError):
        transport.get("https://example.invalid/x", timeout=1.0)
