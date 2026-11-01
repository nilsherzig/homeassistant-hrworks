"""HR WORKS employee library: browser-daemon run scripts, TOTP and shared models."""

from importlib.metadata import PackageNotFoundError, version

from .auth import authenticate, complete_mfa, secret_settings
from .errors import WorkerError
from .totp import InvalidTotp, totp_code

try:
    __version__ = version("hrworks-employee")
except PackageNotFoundError:
    # Home Assistant bundles the library without installing the CLI distribution.
    __version__ = "uninstalled"
__all__ = [
    "WorkerError",
    "InvalidTotp",
    "authenticate",
    "complete_mfa",
    "secret_settings",
    "totp_code",
]
