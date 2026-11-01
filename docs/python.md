# Shared Python library

The installable package imports as `hrworks`. It is the same source bundled under
`custom_components/hrworks/hrworks` for HACS installations. Home Assistant adds
only its native flows, entities and repairs; the browser-daemon client, authentication
and TOTP are shared with the CLI. No Home Assistant or Rich imports are needed to import
the core library.

```python
import asyncio
from hrworks import authenticate
from hrworks.browser_daemon import BrowserDaemonClient


async def main():
    settings = {
        "company_id": "example",
        "username": "employee",
        "password": "...",
        "browser_daemon_url": "http://127.0.0.1:3001",
        "browser_daemon_secret": "...",  # the cluster secret, e.g. read from its file
        "browser_daemon_profile": "hrworks",
    }
    # Resolve secrets from your credential provider, never hardcode production secrets.
    async with BrowserDaemonClient(settings) as client:
        result = await authenticate(client, settings)
        if result.get("mfa_required"):
            await client.mfa(input("Current code: "))
        account = await client.account()
        day = await client.day("2026-09-01")
        proposal = await client.record(
            {
                "start": "2026-09-01T08:00:00+02:00",
                "end": "2026-09-01T12:00:00+02:00",
                "type": "working_time",
                "dry_run": True,
            }
        )
        print(account, day, proposal)


asyncio.run(main())
```

Methods: `health`, `login(force=False)`, `mfa`, `snapshot`, `account`, `day`,
`record`, `logout`, and `close`. `snapshot` takes `calendar_past_days`,
`calendar_future_days`, `include_sickness`, and `include_pending`. `record`
defaults to preview; actual submissions need `dry_run=False` and
`BrowserDaemonClient(..., allow_writes=True)`. Each run is serialized and bounded. No
write is replayed; a write whose outcome is unknown raises
`WorkerError("write_uncertain")`. Fixed error codes omit credentials and portal
captures. CLI and HA separately attach their native authentication UX and permit
one read recovery, never an automatic write retry.

The client keeps one portal tab (the login lives in it) and passes credentials and codes
in the run's `args` only. Helpers include `authenticate`, `complete_mfa`,
`secret_settings` and RFC 6238 `totp_code`. `hrworks.models` provides interval parsing,
numeric-minute formatting, CSV validation and RFC 5545 calendar export. The client can be
tested with a fake `BrowserDaemon` (anything with `run`, `close_tab`, `find_profile` and
`tabs`), see `tests/test_browser_daemon.py`.
