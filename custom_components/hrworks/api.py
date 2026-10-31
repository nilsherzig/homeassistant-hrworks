"""Attach the shared Python client to Home Assistant's lifecycle."""

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import BACKEND_BROWSER_DAEMON, CONF_BACKEND
from .hrworks.client import WorkerClient as SharedWorkerClient
from .hrworks.transport import WorkerError

try:
    from .hrworks.browser_daemon import BrowserDaemonClient
except ImportError:  # browser-daemon-client missing: only the SSH backend works
    BrowserDaemonClient = None

__all__ = ["WorkerClient", "WorkerError", "create_client"]


class WorkerClient(SharedWorkerClient):
    """HA only owns lifecycle; transport and protocol are shared with the CLI."""

    def __init__(self, hass, settings: dict):
        super().__init__(settings)
        self.hass = hass
        self._remove_stop = None

    async def request(self, path: str, payload: dict | None = None) -> dict:
        if self._remove_stop is None:
            self._remove_stop = self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STOP, self.close
            )
        return await super().request(path, payload)

    async def close(self, _event=None):
        remove_stop = self._remove_stop
        self._remove_stop = None
        if remove_stop and _event is None:
            remove_stop()
        await super().close()


def create_client(hass, settings: dict, *, allow_writes: bool = False):
    """The client of the entry's backend: browser-daemon runs, or the SSH worker."""
    if settings.get(CONF_BACKEND) != BACKEND_BROWSER_DAEMON:
        return WorkerClient(hass, settings)
    if BrowserDaemonClient is None:
        raise WorkerError("incompatible_worker")
    return BrowserDaemonClient(
        settings, http=async_get_clientsession(hass), allow_writes=allow_writes
    )
