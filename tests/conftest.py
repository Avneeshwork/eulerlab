"""Test-wide defaults.

The suite runs offline. Tests reached the bucket only transitively — calling
`catalog.search` listed 34,000 remote keys — and one stalled connection hung a
run for 33 minutes instead of failing it. A hang is worse than a failure: it
looks the same as slow work, so it blocked every commit behind it without ever
saying why.

Offline is enforced at the socket, not only by the cloud switch. Two news
tests passed for months on the operator's machine because NSE's company list
was already on disk there, and failed on any machine without it because they
quietly downloaded it. Any connection to a host other than this machine now
raises, and the test that attempted it fails naming the host, whether or not
the code under test swallowed the error.

The real `data/` tree is checked too. `indices.land` appended a fake DOLLAR
INDEX reading to the day's `data/landing/macro/` file on every run, which is
raw data the mirror then copied to B2. The session now fingerprints `data/`
before the first test and fails if any file in it was created, changed or
removed by the end.

Set `EULERLAB_NO_CLOUD=0` to run a test against the real bucket deliberately,
and `EULERLAB_ALLOW_NETWORK=1` to let a test reach the internet at all.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from eulerlab.ingest import landing_reader

ALLOW_NETWORK_ENV = "EULERLAB_ALLOW_NETWORK"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", ""})
PROXY_ENV = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
"""Cleared for each test. A proxy on this machine is a local socket that
forwards anywhere, so leaving it set would let every request through."""


DATA = Path(__file__).resolve().parents[1] / "data"
_DATA_BEFORE = pytest.StashKey[dict[str, tuple[int, int]]]()


class NetworkBlockedError(OSError):
    """A test tried to reach a remote host. Raised as the OS would raise it."""


@pytest.fixture(autouse=True, scope="session")
def _offline() -> None:
    os.environ.setdefault(landing_reader.OFFLINE_ENV, "1")


def _host(address: Any) -> str:
    if isinstance(address, tuple) and address:
        return str(address[0])
    return str(address)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    if os.environ.get(ALLOW_NETWORK_ENV) == "1":
        yield
        return
    attempts: list[str] = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def remote(sock: socket.socket, address: Any) -> bool:
        if sock.family == getattr(socket, "AF_UNIX", None):
            return False
        return _host(address) not in LOCAL_HOSTS

    def refuse(host: str) -> NetworkBlockedError:
        attempts.append(host)
        return NetworkBlockedError(f"tests run offline; refused a connection to {host}")

    def connect(sock: socket.socket, address: Any) -> None:
        if remote(sock, address):
            raise refuse(_host(address))
        real_connect(sock, address)

    def connect_ex(sock: socket.socket, address: Any) -> int:
        if remote(sock, address):
            raise refuse(_host(address))
        return real_connect_ex(sock, address)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        name = host.decode() if isinstance(host, bytes) else str(host or "")
        if name not in LOCAL_HOSTS:
            raise refuse(name)
        return real_getaddrinfo(host, *args, **kwargs)

    for name in PROXY_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    yield
    if attempts:
        hosts = ", ".join(sorted(set(attempts)))
        pytest.fail(f"test reached for the network ({hosts}); the suite runs offline")


def _fingerprint(root: Path) -> dict[str, tuple[int, int]]:
    """(size, mtime) of every file under `root`. Stat only, never a read."""
    out: dict[str, tuple[int, int]] = {}
    for folder, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(folder, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            out[path] = (stat.st_size, stat.st_mtime_ns)
    return out


def pytest_sessionstart(session: pytest.Session) -> None:
    session.config.stash[_DATA_BEFORE] = _fingerprint(DATA)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    before = session.config.stash.get(_DATA_BEFORE, None)
    if before is None:
        return
    after = _fingerprint(DATA)
    touched = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
    if not touched:
        return
    shown = "\n  ".join(os.path.relpath(p, DATA.parent) for p in touched[:20])
    more = f"\n  ... and {len(touched) - 20} more" if len(touched) > 20 else ""
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    message = (
        f"tests changed {len(touched)} file(s) under data/, which no test may touch "
        f"(a concurrent `make daily` would also show here):\n  {shown}{more}"
    )
    if reporter is not None:
        reporter.ensure_newline()
        reporter.write_line(message, red=True)
    session.exitstatus = pytest.ExitCode.TESTS_FAILED
