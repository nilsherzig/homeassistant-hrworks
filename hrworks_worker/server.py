"""JSON-line browser worker intended to run as an SSH child process."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from . import PROTOCOL_VERSION
from .portal import BERLIN, EmployeePortal, PortalError, profile_id

LOGGER = logging.getLogger(__name__)

# Disconnect from the browser between polls so its session ends; the next
# request reconnects and restores the saved cookies.
BROWSER_IDLE_SECONDS = 60
# An abandoned HA setup flow must not leave a remote process running forever.
WORKER_IDLE_SECONDS = 1800
# Closing contexts over CDP can hang on a wedged browser; never block exit on it.
RELEASE_TIMEOUT_SECONDS = 15


def _resolve_browser_daemon_secret() -> str | None:
    """Read browser-daemon cluster secret if available."""
    secret = os.environ.get("BROWSER_DAEMON_SECRET")
    if secret:
        return secret.strip()
    secret_files = [
        os.environ.get("BROWSER_DAEMON_SECRET_FILE"),
        "/run/secrets/browser-daemon/passkey-helper-secret",
        "/run/secrets/browser-daemon/cluster-secret",
    ]
    for path in secret_files:
        if path and os.path.exists(path):
            try:
                with open(path) as f:
                    val = f.read().strip()
                if val:
                    return val
            except OSError:
                continue
    return None


def _authenticated_cdp_url(url: str) -> str:
    """Ensure cdp_url includes authentication if connecting to browser-daemon."""
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    if "auth" in query:
        return url
    secret = _resolve_browser_daemon_secret()
    if secret:
        sep = "&" if parts.query else "?"
        return f"{url}{sep}auth={secret}"
    return url


def _browser_error_detail(error: Exception) -> str:
    """Classify browser errors without returning the exception or its URL."""
    message = str(error).lower()
    match = re.search(r"status\s+(\d{3})", message)
    if match:
        status = int(match.group(1))
        if status in {401, 403, 429}:
            return f"http_{status}"
        if 500 <= status <= 599:
            return "http_5xx"
    if "timeout" in message:
        return "timeout"
    return "connection_failed"


class Worker:
    def __init__(
        self,
        cdp_url: str = "http://127.0.0.1:9222",
        state_dir: Path | None = None,
        enable_writes: bool = False,
        backend: str = "cdp",
        steel_api_url: str = "http://127.0.0.1:3002",
    ) -> None:
        self.cdp_url = _authenticated_cdp_url(cdp_url)
        # browser-daemon persistent profile (`?profile=<name>`): reuse its login.
        self.shared_profile = "profile" in parse_qs(urlsplit(self.cdp_url).query)
        self.state_dir = state_dir or Path.home() / ".local/state/hrworks-worker"
        self.enable_writes = enable_writes
        self.backend = backend
        self.steel_api_url = steel_api_url.rstrip("/")
        self.playwright = None
        self.browser = None
        self.steel_session_id: str | None = None
        self.profiles: dict[str, EmployeePortal] = {}
        # What the last snapshot ran on, for the integration's diagnostic sensors.
        self.connect_seconds: float | None = None
        self.connections = 0
        self._browser_session: tuple[int, str | None] | None = None

    def _steel_request(self, path: str, *, payload: dict | None = None) -> dict:
        data = json.dumps(payload or {}).encode() if payload is not None else None
        request = Request(
            f"{self.steel_api_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=15) as response:
                result = json.load(response)
        except (OSError, TimeoutError, URLError, ValueError):
            raise PortalError("browser_unavailable", 503) from None
        if not isinstance(result, dict):
            raise PortalError("browser_unavailable", 503)
        return result

    async def _create_steel_session(self) -> tuple[str, str]:
        session = await asyncio.to_thread(
            self._steel_request, "/v1/sessions", payload={"timeout": 3600000}
        )
        session_id = session.get("id")
        websocket_url = session.get("websocketUrl") or session.get("websocket_url")
        if not isinstance(session_id, str) or not isinstance(websocket_url, str):
            if isinstance(session_id, str):
                self.steel_session_id = session_id
                await self._release_steel_session()
            raise PortalError("browser_unavailable", 503)
        self.steel_session_id = session_id
        # Steel may report its container wildcard address; dial the same local
        # published API port the worker used to create the session instead.
        if "0.0.0.0" in websocket_url:
            websocket_url = websocket_url.replace("0.0.0.0", "127.0.0.1")
        return session_id, websocket_url

    async def _release_steel_session(self) -> None:
        session_id, self.steel_session_id = self.steel_session_id, None
        if session_id:
            try:
                await asyncio.to_thread(self._steel_request, f"/v1/sessions/{session_id}/release")
            except (PortalError, OSError, TimeoutError):
                LOGGER.warning("Could not release Steel browser session")

    async def connect(self) -> None:
        if self.browser and self.browser.is_connected():
            return
        if self.backend == "steel":
            await self._release_steel_session()
        started = time.monotonic()
        if self.playwright is None:
            self.playwright = await async_playwright().start()
        endpoint = self.cdp_url
        if self.backend == "steel":
            _, endpoint = await self._create_steel_session()
        try:
            self.browser = await self.playwright.chromium.connect_over_cdp(
                endpoint, no_defaults=True, timeout=15000
            )
        except PlaywrightError as err:
            await self._release_steel_session()
            raise PortalError(
                "browser_unavailable",
                503,
                stage="browser_connect",
                detail=_browser_error_detail(err),
            ) from None
        self.connect_seconds = round(time.monotonic() - started, 2)
        self.connections += 1
        for portal in self.profiles.values():
            portal.browser = self.browser
            portal.context = portal.page = None

    def _daemon_tabs(self) -> list[dict]:
        """The browser-daemon's tab list (its `/json/list` names each tab's session)."""
        parts = urlsplit(self.cdp_url)
        scheme = "https" if parts.scheme in {"wss", "https"} else "http"
        query = parse_qs(parts.query)
        auth = query.get("auth", [None])[0]
        url = f"{scheme}://{parts.netloc}/json/list"
        if auth:
            url = f"{url}?auth={auth}"
        try:
            with urlopen(url, timeout=3) as response:
                tabs = json.load(response)
            return tabs if isinstance(tabs, list) else []
        except Exception:
            return []

    async def _browser_session_id(self, portal: EmployeePortal) -> str | None:
        """The session of the browser this connection got (browser-daemon: its session id)."""
        if self.backend == "steel":
            return self.steel_session_id
        key = id(self.browser)
        if self._browser_session and self._browser_session[0] == key:
            return self._browser_session[1]
        session_id = None
        try:
            if portal.page is not None:
                cdp = await portal.page.context.new_cdp_session(portal.page)
                try:
                    info = await cdp.send("Target.getTargetInfo")
                finally:
                    await cdp.detach()
                target = info["targetInfo"]["targetId"]
                for tab in await asyncio.to_thread(self._daemon_tabs):
                    if tab.get("id") == target:
                        session_id = tab.get("sessionId") or tab.get("session_id")
                        break
        except Exception:  # noqa: BLE001 - diagnostics must never fail a snapshot
            LOGGER.debug("Could not identify the browser session", exc_info=True)
        if session_id is not None or portal.page is not None:
            self._browser_session = (key, session_id)
        return session_id

    async def diagnostics(self, portal: EmployeePortal, seconds: float) -> dict:
        """Where and how a snapshot ran: no personal data, no endpoint secrets."""
        parts = urlsplit(self.cdp_url)
        return {
            "worker_seconds": round(seconds, 2),
            "backend": self.backend,
            "browser_version": getattr(self.browser, "version", None),
            "browser_session": await self._browser_session_id(portal),
            "browser_endpoint": parts.netloc or None,
            "connect_seconds": self.connect_seconds,
            "connections": self.connections,
        }

    async def portal(self, identity: str, *, create: bool = False) -> EmployeePortal:
        if not re.fullmatch(r"[a-f0-9]{64}", identity):
            raise PortalError("invalid_request")
        await self.connect()
        if identity not in self.profiles:
            if not create and not (self.state_dir / f"{identity}.json").exists():
                raise PortalError("session_expired", 403)
            if len(self.profiles) >= 16:
                raise PortalError("busy", 503)
            self.profiles[identity] = EmployeePortal(
                self.browser, self.state_dir, identity, shared=self.shared_profile
            )
        return self.profiles[identity]

    @property
    def connected(self) -> bool:
        return self.playwright is not None

    @property
    def mfa_pending(self) -> bool:
        return any(portal.mfa_pending for portal in self.profiles.values())

    async def _release(self) -> None:
        try:
            for portal in self.profiles.values():
                if self.browser and self.browser.is_connected():
                    await portal.release()
        finally:
            # Disconnect our driver; never close Chromium or other users' contexts.
            self.browser = None
            for portal in self.profiles.values():
                portal.context = portal.page = None
            playwright, self.playwright = self.playwright, None
            if playwright:
                await playwright.stop()
            await self._release_steel_session()

    async def close(self) -> None:
        """Release the browser session; the next request connects again."""
        try:
            async with asyncio.timeout(RELEASE_TIMEOUT_SECONDS):
                await self._release()
        except (PlaywrightError, PortalError, OSError, TimeoutError):
            LOGGER.warning("Could not release the browser session cleanly")

    async def dispatch(self, path: str, data: dict | None) -> dict:
        if path == "health":
            await self.connect()
            return {
                "protocol_version": PROTOCOL_VERSION,
                "writes_enabled": self.enable_writes,
                "capabilities": ["fresh_login", "day", "account", "logout"],
            }
        if not isinstance(data, dict):
            raise PortalError("invalid_request")
        if path == "login":
            if any(
                not isinstance(data.get(k), str) or not data[k].strip()
                for k in ("company_id", "username", "password")
            ):
                raise PortalError("invalid_request")
            if type(data.get("force", False)) is not bool:
                raise PortalError("invalid_request")
            identity = profile_id(data["company_id"].strip(), data["username"].strip())
            portal = await self.portal(identity, create=True)
            async with portal.lock:
                return await portal.login(
                    data["company_id"].strip(),
                    data["username"].strip(),
                    data["password"],
                    force=data.get("force", False),
                )
        match = re.fullmatch(
            r"profiles/([a-f0-9]{64})/(mfa|snapshot|record|day|account|logout)", path
        )
        if not match:
            raise PortalError("not_found", 404)
        if match[2] == "logout":
            existing = self.profiles.get(match[1])
            if existing:
                async with existing.lock:
                    if existing.shared:
                        await existing.forget()
                    await existing.close()
                    existing.state_path.unlink(missing_ok=True)
                    self.profiles.pop(match[1], None)
            else:
                (self.state_dir / f"{match[1]}.json").unlink(missing_ok=True)
            return {"logged_out": True}
        portal = await self.portal(match[1])
        async with portal.lock:
            match match[2]:
                case "day":
                    try:
                        day = date.fromisoformat(data["date"])
                    except (KeyError, TypeError, ValueError):
                        raise PortalError("invalid_request") from None
                    if type(data.get("reuse", False)) is not bool:
                        raise PortalError("invalid_request")
                    metrics, entries = await portal.working_day(day, reuse=data.get("reuse", False))
                    return {"date": day.isoformat(), "metrics": metrics, "entries": entries}
                case "account":
                    metrics, account = await portal.account(datetime.now(BERLIN).date())
                    await portal.save_session()
                    return {"metrics": metrics, "account": account}
                case "mfa":
                    if not isinstance(data.get("code"), str):
                        raise PortalError("invalid_request")
                    return await portal.mfa(data["code"].strip())
                case "snapshot":
                    for key in ("calendar_past_days", "calendar_future_days"):
                        if type(data.get(key)) is not int or not 0 <= data[key] <= 730:
                            raise PortalError("invalid_request")
                    for key in ("include_sickness", "include_pending"):
                        if type(data.get(key)) is not bool:
                            raise PortalError("invalid_request")
                    started = time.monotonic()
                    result = await portal.snapshot(data)
                    result["diagnostics"] = await self.diagnostics(
                        portal, time.monotonic() - started
                    )
                    return result
                case "record":
                    if type(data.get("dry_run", True)) is not bool:
                        raise PortalError("invalid_request")
                    if not data.get("dry_run", True) and not self.enable_writes:
                        raise PortalError("writes_disabled", 403)
                    return await portal.record(data)
        raise PortalError("invalid_request")


async def serve(worker: Worker) -> None:
    """Bound requests, sanitize errors and reserve stdout for protocol messages."""
    reader = asyncio.StreamReader(limit=16 * 1024)
    protocol = asyncio.StreamReaderProtocol(reader)
    loop = asyncio.get_running_loop()
    transport, _ = await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    try:
        idle_since = loop.time()
        while True:
            remaining = WORKER_IDLE_SECONDS - (loop.time() - idle_since)
            if remaining <= 0:
                break
            release = worker.connected and not worker.mfa_pending
            try:
                async with asyncio.timeout(
                    min(BROWSER_IDLE_SECONDS, remaining) if release else remaining
                ):
                    line = await reader.readline()
            except ValueError:
                break
            except TimeoutError:
                if release:
                    await worker.close()
                continue
            if not line:
                break
            try:
                async with asyncio.timeout(160):
                    message = json.loads(line)
                    if not isinstance(message, dict) or not isinstance(message.get("path"), str):
                        raise PortalError("invalid_request")
                    result = await worker.dispatch(message["path"], message.get("payload"))
            except PortalError as err:
                result = {"error": err.code}
                if err.stage:
                    result["stage"] = err.stage
                if err.detail:
                    result["detail"] = err.detail
            except (ValueError, TypeError):
                result = {"error": "invalid_request"}
            except (PlaywrightError, TimeoutError) as err:
                result = {
                    "error": "browser_unavailable",
                    "stage": "browser_operation",
                    "detail": (
                        "timeout" if isinstance(err, TimeoutError) else _browser_error_detail(err)
                    ),
                }
            except Exception:
                LOGGER.error("Worker operation failed; portal content omitted")
                result = {"error": "portal_changed"}
            sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
            sys.stdout.flush()
            idle_since = loop.time()
    finally:
        transport.close()
        await worker.close()


def run_worker(
    *,
    cdp_url: str,
    backend: str,
    steel_api_url: str,
    state_dir: Path,
    enable_writes: bool,
) -> None:
    """Run the browser worker's JSON-line protocol."""
    os.umask(0o077)
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    asyncio.run(
        serve(
            Worker(
                cdp_url,
                state_dir,
                enable_writes,
                backend,
                steel_api_url,
            )
        )
    )
