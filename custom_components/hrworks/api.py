"""Create the browser-daemon client of a config entry."""

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_BD_SECRET, CONF_BD_URL
from .hrworks.browser_daemon import BrowserDaemonClient
from .hrworks.errors import WorkerError

__all__ = ["WorkerError", "create_client", "shared_browser_daemon"]


def shared_browser_daemon(hass) -> dict:
    """The URL and cluster secret of the Browser Daemon integration, never stored here."""
    try:
        from custom_components.browser_daemon import async_get_client
    except ImportError as err:
        raise WorkerError("cannot_connect") from err
    client = async_get_client(hass)
    url = getattr(client, "base_url", None)
    if not url:
        raise WorkerError("cannot_connect")
    return {CONF_BD_URL: url, CONF_BD_SECRET: getattr(client, "cluster_secret", None)}


def create_client(hass, settings: dict, *, allow_writes: bool = False) -> BrowserDaemonClient:
    """A client for the entry's browser-daemon; an empty URL uses the Browser Daemon integration."""
    if not settings.get(CONF_BD_URL):
        settings = {**settings, **shared_browser_daemon(hass)}
    return BrowserDaemonClient(
        settings, http=async_get_clientsession(hass), allow_writes=allow_writes
    )
