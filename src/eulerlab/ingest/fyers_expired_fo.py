"""Fetch and preserve FYERS expired NSE futures candles after approved use.

The Standard plan limits expired-F&O intraday requests. This fetcher counts
every request to FYERS' expired-F&O endpoints against a conservative shared
daily budget of ten, records attempts before sending them, and stores raw JSON
once with its query and knowledge time. It never logs credentials or tokens.

Run ``make fyers-auth`` to complete FYERS' interactive individual-app login,
then ``make fyers-expired-fo UNDERLYING=NSE:RELIANCE-EQ FROM=2026-03-01
TO=2026-08-03``. The configured redirect URI must match the app dashboard.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import stat
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from getpass import getpass
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from eulerlab.env import load_env
from eulerlab.ingest.cloud import S3ObjectStore, load_storage_config, sync_directory

API_BASE = "https://api-t1.fyers.in"
EXPIRED_PREFIX = "/data/history/fno/expired/"
DEFAULT_REDIRECT_URI = "https://trade.fyers.in/api-login/redirect-uri/index.html"
LANDING_ROOT = Path("data/landing/fyers_expired_fo")
SESSION_META_PATH = Path("data/cache/fyers_session.json")
MAX_EXPIRED_REQUESTS_PER_DAY = 10
MAX_CANDLE_DAYS = 100
MAX_EXPIRY_QUERY_DAYS = 366
MIN_REQUEST_INTERVAL_SECONDS = 0.35
IST = ZoneInfo("Asia/Kolkata")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


class FyersAPIError(RuntimeError):
    """FYERS refused a request or returned an unusable response."""


class FyersCredentials(BaseModel):
    """Only the credentials required for market-data reads."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    app_id: str = Field(min_length=1)
    access_token: str = Field(min_length=1)


class FyersSettings(BaseModel):
    """Private login settings loaded from the local ignored .env file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    app_id: str = Field(min_length=1)
    secret_key: str = Field(min_length=1)
    redirect_uri: str = Field(min_length=1)


class RawEntry(BaseModel):
    """Manifest record for one immutable raw API response."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str
    endpoint: str
    params: dict[str, str]
    path: str
    sha256: str
    size_bytes: int
    rows: int
    knowledge_time: datetime


def _setting(*names: str, default: str = "") -> str:
    load_env()
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def _app_id() -> str:
    value = _setting("FYERS_APP_ID", "Fyer_APP_ID", "FYER_APP_ID", "FYERS_CLIENT_ID")
    if not value:
        raise FyersAPIError("No FYERS app ID found in .env.")
    return value


def _secret_key() -> str:
    value = _setting("FYERS_SECRET_KEY", "Fyer_Secret", "FYER_SECRET_KEY")
    if not value:
        raise FyersAPIError("No FYERS app secret found in .env.")
    return value


def credentials() -> FyersCredentials:
    """Load the active daily token, without ever printing it."""
    token = _setting("FYERS_ACCESS_TOKEN", "Fyer_ACCESS_TOKEN")
    if not token:
        raise FyersAPIError("No active FYERS access token. Run `make fyers-auth` first.")
    return FyersCredentials(app_id=_app_id(), access_token=token)


def _settings() -> FyersSettings:
    return FyersSettings(
        app_id=_app_id(),
        secret_key=_secret_key(),
        redirect_uri=_setting(
            "FYERS_REDIRECT_URI", "Fyer_REDIRECT_URI", default=DEFAULT_REDIRECT_URI
        ),
    )


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _request_id(endpoint: str, params: Mapping[str, str]) -> str:
    return hashlib.sha256(_canonical({"endpoint": endpoint, "params": dict(params)})).hexdigest()


def _json_from_bytes(payload: bytes, *, source: str) -> dict[str, Any]:
    try:
        parsed = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FyersAPIError(f"FYERS {source} response was not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise FyersAPIError(f"FYERS {source} response was not a JSON object.")
    return cast(dict[str, Any], parsed)


class RawLanding:
    """Append-only raw response store with a bitemporal manifest."""

    def __init__(self, root: Path = LANDING_ROOT) -> None:
        self.root = root
        self.manifest_path = root / "manifest.jsonl"
        self.attempts_path = root / "requests.jsonl"
        self._entries = self._read_manifest()

    def _read_manifest(self) -> dict[str, RawEntry]:
        found: dict[str, RawEntry] = {}
        if not self.manifest_path.exists():
            return found
        with self.manifest_path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    entry = RawEntry.model_validate_json(line)
                    found[entry.request_id] = entry
        return found

    def cached(self, request_id: str) -> dict[str, Any] | None:
        entry = self._entries.get(request_id)
        if entry is None:
            return None
        path = self.root / entry.path
        if not path.is_file():
            raise FyersAPIError(f"Raw landing file is missing for request {request_id[:12]}.")
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != entry.sha256:
            raise FyersAPIError(f"Raw landing checksum failed for request {request_id[:12]}.")
        return _json_from_bytes(payload, source="cached")

    def expired_requests_today(self) -> int:
        today = datetime.now(IST).date()
        if not self.attempts_path.exists():
            return 0
        count = 0
        with self.attempts_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                requested_at = datetime.fromisoformat(str(row["requested_at"]))
                if requested_at.astimezone(IST).date() == today:
                    count += 1
        return count

    def record_attempt(self, request_id: str, endpoint: str, params: Mapping[str, str]) -> None:
        self.attempts_path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "request_id": request_id,
            "endpoint": endpoint,
            "params": dict(params),
            "requested_at": datetime.now(UTC).isoformat(),
        }
        with self.attempts_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    def write(
        self,
        request_id: str,
        endpoint: str,
        params: Mapping[str, str],
        payload: bytes,
        rows: int,
    ) -> RawEntry:
        slug = endpoint.rstrip("/").rsplit("/", 1)[-1]
        relative = Path(slug, request_id[:2], f"{request_id}.json")
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FyersAPIError(f"Refusing to overwrite raw response {target}.")
        fd, temp_name = tempfile.mkstemp(dir=target.parent, suffix=".part")
        temporary = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(payload)
                out.flush()
                os.fsync(out.fileno())
            temporary.chmod(0o444)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        entry = RawEntry(
            request_id=request_id,
            endpoint=endpoint,
            params=dict(params),
            path=str(relative),
            sha256=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
            rows=rows,
            knowledge_time=datetime.now(UTC),
        )
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(entry.model_dump_json() + "\n")
        self._entries[request_id] = entry
        return entry


class FyersTransport:
    """Small HTTPS transport. Authorization is never included in output."""

    def __init__(self, app_id: str, token: str) -> None:
        self._authorization = f"{app_id}:{token}"
        self._last_request = 0.0

    def get(self, endpoint: str, params: Mapping[str, str]) -> tuple[int, bytes]:
        delay = MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - self._last_request)
        if delay > 0:
            time.sleep(delay)
        query = urllib.parse.urlencode(params)
        url = f"{API_BASE}{endpoint}?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": self._authorization,
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="GET",
        )
        self._last_request = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise FyersAPIError(f"FYERS request failed: {type(exc).__name__}.") from exc


class FyersExpiredFO:
    """Authenticated expired-contract discovery and candle requests."""

    def __init__(self, token: FyersCredentials, landing: RawLanding | None = None) -> None:
        self.landing = landing or RawLanding()
        self.transport = FyersTransport(token.app_id, token.access_token)

    def get_json(
        self, endpoint: str, params: Mapping[str, str], *, rows_field: str | None = None
    ) -> dict[str, Any]:
        normalized = {str(key): str(value) for key, value in params.items()}
        request_id = _request_id(endpoint, normalized)
        cached = self.landing.cached(request_id)
        if cached is not None:
            return cached

        is_expired_endpoint = endpoint.startswith(EXPIRED_PREFIX)
        if is_expired_endpoint:
            count = self.landing.expired_requests_today()
            if count >= MAX_EXPIRED_REQUESTS_PER_DAY:
                raise FyersAPIError(
                    f"The local FYERS expired-F&O request budget is {count}/"
                    f"{MAX_EXPIRED_REQUESTS_PER_DAY} today; rerun tomorrow."
                )
            self.landing.record_attempt(request_id, endpoint, normalized)

        status, payload = self.transport.get(endpoint, normalized)
        if status != 200:
            detail = _json_from_bytes(payload, source="error") if payload else {}
            code = detail.get("code", status)
            message = detail.get("message", "request was rejected")
            raise FyersAPIError(f"FYERS HTTP {status}, code {code}: {message}")
        response = _json_from_bytes(payload, source="API")
        state = response.get("s")
        if state not in ("ok", "no_data"):
            code = response.get("code", "unknown")
            message = response.get("message", "request was rejected")
            raise FyersAPIError(f"FYERS code {code}: {message}")
        values = response.get(rows_field, []) if rows_field else []
        row_count = len(values) if isinstance(values, list) else 0
        self.landing.write(request_id, endpoint, normalized, payload, row_count)
        return response

    def expiry_dates(self, symbol: str, start: date, end: date) -> list[date]:
        endpoint = f"{EXPIRED_PREFIX}expiry-dates"
        dates: set[date] = set()
        for lower, upper in _date_chunks(start, end, MAX_EXPIRY_QUERY_DAYS):
            response = self.get_json(
                endpoint,
                {
                    "symbol": symbol,
                    "range_from": lower.isoformat(),
                    "range_to": upper.isoformat(),
                    "date_format": "1",
                },
            )
            data = response.get("data", {})
            expiry_dates = data.get("expiry_dates", {}).get("futures", [])
            if not isinstance(expiry_dates, list):
                raise FyersAPIError("FYERS expiry response has no futures expiry list.")
            dates.update(_parse_date(value) for value in expiry_dates)
        return sorted(dates)

    def future_symbols(self, symbol: str, expiry: date) -> list[str]:
        response = self.get_json(
            f"{EXPIRED_PREFIX}underlying-symbols",
            {"symbol": symbol, "expiry_date": expiry.isoformat()},
        )
        data = response.get("data", {})
        contracts = data.get("contracts", {}).get("futures", [])
        if not isinstance(contracts, list) or any(not isinstance(item, str) for item in contracts):
            raise FyersAPIError("FYERS expired-contract response has an invalid futures list.")
        return sorted(set(contracts))

    def candles(self, symbol: str, start: date, end: date) -> dict[str, Any]:
        if (end - start).days >= MAX_CANDLE_DAYS:
            raise ValueError(f"FYERS permits at most {MAX_CANDLE_DAYS} days per candle request.")
        return self.get_json(
            f"{EXPIRED_PREFIX}historical-data",
            {
                "symbol": symbol,
                "resolution": "1",
                "date_format": "1",
                "range_from": start.isoformat(),
                "range_to": end.isoformat(),
                "include_oi": "0",
                "include_greeks": "0",
            },
            rows_field="candles",
        )

    def _mirror_landing_to_b2(self) -> None:
        """Mirror this raw source tree under the configured B2 prefix."""
        if not self.landing.root.is_dir() or not any(self.landing.root.iterdir()):
            return
        try:
            config = load_storage_config(Path("config/storage.yaml"))
            store = S3ObjectStore(config)
            prefix = f"{config.prefix}{self.landing.root.name}/"
            result = sync_directory(self.landing.root, store, prefix=prefix, verify=True, workers=1)
        except Exception as exc:
            raise FyersAPIError(
                f"B2 raw mirror could not run ({type(exc).__name__}); "
                "the immutable local landing is retained for retry."
            ) from exc
        if result.failed:
            details = "; ".join(result.failed[:3])
            raise FyersAPIError(
                f"B2 mirror failed for {len(result.failed)} raw FYERS file(s): {details}. "
                "The immutable local landing is retained; rerun the fetch command to retry."
            )
        print(
            f"B2 raw mirror: uploaded {result.uploaded}, already present {result.skipped} "
            f"under {config.bucket}/{prefix}"
        )

    def fetch_underlying(self, underlying: str, start: date, end: date) -> dict[str, int | str]:
        """Fetch expired futures with expiry through 100 days after the data end.

        The extra expiry window identifies the next contract after the data
        end, so front-contract selection stays valid in the final sessions.
        Only expiries through that first next expiry are downloaded; older raw
        requests remain immutable and cached.
        """
        fetch_error: Exception | None = None
        try:
            return self._fetch_underlying(underlying, start, end)
        except Exception as exc:
            fetch_error = exc
            raise
        finally:
            try:
                self._mirror_landing_to_b2()
            except Exception as sync_error:
                if fetch_error is None:
                    if isinstance(sync_error, FyersAPIError):
                        raise
                    raise FyersAPIError(
                        f"B2 raw mirror failed ({type(sync_error).__name__}); "
                        "the immutable local landing is retained for retry."
                    ) from sync_error
                print(f"B2 mirror also failed; local raw files remain: {sync_error}")

    def _fetch_underlying(self, underlying: str, start: date, end: date) -> dict[str, int | str]:
        if end < start:
            raise ValueError("end date must not be before start date")
        latest_expiry = min(end + timedelta(days=100), datetime.now(IST).date() - timedelta(days=1))
        if latest_expiry < start:
            raise ValueError("requested range is not within FYERS' expired-contract availability")
        discovered = self.expiry_dates(underlying, start, latest_expiry)
        in_range = [expiry for expiry in discovered if start <= expiry <= end]
        next_expiry = next((expiry for expiry in discovered if expiry > end), None)
        expiries = in_range + ([next_expiry] if next_expiry is not None else [])
        result: dict[str, int | str] = {
            "underlying": underlying,
            "expiry_dates": len(expiries),
            "contracts_found": 0,
            "candle_requests": 0,
            "candles": 0,
            "cached_responses": 0,
        }
        for expiry in expiries:
            symbols = self.future_symbols(underlying, expiry)
            result["contracts_found"] = int(result["contracts_found"]) + len(symbols)
            lower = max(start, expiry - timedelta(days=MAX_CANDLE_DAYS - 1))
            upper = min(end, expiry)
            if upper < lower:
                continue
            for contract_symbol in symbols:
                request_id = _request_id(
                    f"{EXPIRED_PREFIX}historical-data",
                    {
                        "symbol": contract_symbol,
                        "resolution": "1",
                        "date_format": "1",
                        "range_from": lower.isoformat(),
                        "range_to": upper.isoformat(),
                        "include_oi": "0",
                        "include_greeks": "0",
                    },
                )
                had_cache = request_id in self.landing._entries
                response = self.candles(contract_symbol, lower, upper)
                candles = response.get("candles", [])
                result["candle_requests"] = int(result["candle_requests"]) + 1
                result["candles"] = int(result["candles"]) + len(candles)
                result["cached_responses"] = int(result["cached_responses"]) + int(had_cache)
                print(
                    f"{contract_symbol} {lower}..{upper}: {len(candles):,} bars"
                    f"{' (cached)' if had_cache else ''}"
                )
        return result


def _date_chunks(start: date, end: date, max_days: int) -> list[tuple[date, date]]:
    out: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        last = min(cursor + timedelta(days=max_days - 1), end)
        out.append((cursor, last))
        cursor = last + timedelta(days=1)
    return out


def _parse_date(value: object) -> date:
    if not isinstance(value, str):
        raise FyersAPIError("FYERS returned an expiry date that was not a string.")
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise FyersAPIError("FYERS returned an expiry date in an unknown format.") from exc


def _save_token(token: str, env_path: Path = Path(".env")) -> None:
    resolved = env_path.resolve(strict=True)
    content = resolved.read_text(encoding="utf-8")
    lines = content.splitlines()
    replacement = "FYERS_ACCESS_TOKEN=" + token
    found = False
    for index, line in enumerate(lines):
        if line.partition("=")[0].strip() == "FYERS_ACCESS_TOKEN":
            lines[index] = replacement
            found = True
            break
    if not found:
        lines.append(replacement)
    output = "\n".join(lines).rstrip("\n") + "\n"
    original_mode = stat.S_IMODE(resolved.stat().st_mode)
    fd, temporary_name = tempfile.mkstemp(dir=resolved.parent, prefix=".env.", suffix=".part")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(output)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(original_mode & 0o600)
        os.replace(temporary, resolved)
        os.environ["FYERS_ACCESS_TOKEN"] = token
    finally:
        temporary.unlink(missing_ok=True)


def auth_url(state: str) -> str:
    """Build FYERS' login URL for a single-use, caller-generated state."""
    settings = _settings()
    query = urllib.parse.urlencode(
        {
            "client_id": settings.app_id,
            "redirect_uri": settings.redirect_uri,
            "response_type": "code",
            "state": state,
        }
    )
    return f"{API_BASE}/api/v3/generate-authcode?{query}"


def _token_expiry(minted_at: datetime) -> datetime:
    local = minted_at.astimezone(IST)
    cutoff = local.replace(hour=6, minute=30, second=0, microsecond=0)
    if cutoff <= local:
        cutoff += timedelta(days=1)
    return cutoff.astimezone(UTC)


def _save_session_metadata(*, user: str, minted_at: datetime) -> datetime:
    expires_at = _token_expiry(minted_at)
    payload = json.dumps(
        {
            "user": user,
            "minted_at": minted_at.isoformat(),
            "expires_at": expires_at.isoformat(),
        },
        sort_keys=True,
        indent=2,
    )
    SESSION_META_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(dir=SESSION_META_PATH.parent, suffix=".part")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, SESSION_META_PATH)
    finally:
        temporary.unlink(missing_ok=True)
    return expires_at


def token_status() -> dict[str, str | bool]:
    """Return token presence/freshness without returning the token itself."""
    token = _setting("FYERS_ACCESS_TOKEN", "Fyer_ACCESS_TOKEN")
    metadata: dict[str, Any] = {}
    try:
        raw = json.loads(SESSION_META_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            metadata = raw
    except (OSError, json.JSONDecodeError):
        pass
    expires_at = str(metadata.get("expires_at", ""))
    expiry_known = False
    try:
        expires = datetime.fromisoformat(expires_at)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        expiry_known = True
        fresh = bool(token) and datetime.now(UTC) < expires
    except ValueError:
        fresh = False
    configured = bool(
        _setting("FYERS_APP_ID", "Fyer_APP_ID", "FYER_APP_ID", "FYERS_CLIENT_ID")
        and _setting("FYERS_SECRET_KEY", "Fyer_Secret", "FYER_SECRET_KEY")
    )
    reason = (
        ""
        if fresh
        else "FYERS app ID and secret are not both set in .env"
        if not configured
        else "no FYERS token minted today"
        if not token
        else "FYERS token has expired; log in again"
        if expiry_known
        else "token freshness is unknown; log in again"
    )
    return {
        "configured": configured,
        "fresh": fresh,
        "user": str(metadata.get("user", "")) if fresh else "",
        "expires_at": expires.isoformat() if fresh else "",
        "reason": reason,
    }


def exchange_auth_code(auth_code: str) -> dict[str, str]:
    """Exchange the one-time code and save the daily token locally."""
    settings = _settings()
    if not auth_code:
        raise FyersAPIError("The redirect URL did not contain an auth_code.")
    app_hash = hashlib.sha256(f"{settings.app_id}:{settings.secret_key}".encode()).hexdigest()
    body = _canonical(
        {"grant_type": "authorization_code", "appIdHash": app_hash, "code": auth_code}
    )
    request = urllib.request.Request(
        f"{API_BASE}/api/v3/validate-authcode",
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = _json_from_bytes(exc.read(), source="auth error")
        code = detail.get("code", exc.code)
        message = detail.get("message", "token exchange failed")
        raise FyersAPIError(f"FYERS token exchange failed, code {code}: {message}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FyersAPIError(f"FYERS token exchange failed: {type(exc).__name__}.") from exc
    result = _json_from_bytes(payload, source="auth")
    access_token = result.get("access_token")
    if result.get("s") != "ok" or not isinstance(access_token, str) or not access_token:
        code = result.get("code", "unknown")
        message = result.get("message", "token response did not contain an access token")
        raise FyersAPIError(f"FYERS token exchange failed, code {code}: {message}")
    _save_token(access_token)
    minted_at = datetime.now(UTC)
    user = str(result.get("user_id") or result.get("fy_id") or "FYERS user")
    expires_at = _save_session_metadata(user=user, minted_at=minted_at)
    return {"user": user, "expires_at": expires_at.isoformat()}


def login() -> None:
    """Run FYERS' documented auth-code flow locally; never print the token."""
    state = secrets.token_urlsafe(24)
    url = auth_url(state)
    print("Opening FYERS login. Complete it in your browser.")
    if not webbrowser.open(url):
        print(f"Open this FYERS login URL manually:\n{url}")
    callback = getpass("Paste the full final redirect URL (input is hidden): ").strip()
    parsed = urllib.parse.urlparse(callback)
    query_values = urllib.parse.parse_qs(parsed.query)
    returned_state = next(iter(query_values.get("state", [])), "")
    auth_code = next(iter(query_values.get("auth_code", [])), "")
    if returned_state != state:
        raise FyersAPIError("FYERS login state did not match; token was not requested.")
    outcome = exchange_auth_code(auth_code)
    expires = datetime.fromisoformat(outcome["expires_at"]).astimezone(IST)
    print("FYERS access token stored in the ignored .env file. Token not displayed.")
    print(f"Session expires at {expires:%Y-%m-%d %H:%M} IST.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fyers-expired-fo")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("auth", help="log into FYERS and store today's access token")
    fetch = commands.add_parser("fetch", help="fetch expired futures candles for one underlying")
    fetch.add_argument("--underlying", required=True, help="FYERS underlying, e.g. NSE:RELIANCE-EQ")
    fetch.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    fetch.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    fetch.add_argument("--root", type=Path, default=LANDING_ROOT)
    args = parser.parse_args(argv)
    try:
        if args.command == "auth":
            login()
            return 0
        token = credentials()
        client = FyersExpiredFO(token, RawLanding(args.root))
        report = client.fetch_underlying(args.underlying, args.start, args.end)
        report["local_expired_api_calls_today"] = client.landing.expired_requests_today()
        print(json.dumps(report, indent=2))
        return 0
    except FyersAPIError as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
