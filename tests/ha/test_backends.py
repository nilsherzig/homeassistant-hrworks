"""Backend choice in the config flow and in create_client, with fake clients only."""

import sys
import unittest
from datetime import timedelta
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from browser_daemon_client import RunError, RunResult

from custom_components.hrworks import api, config_flow
from custom_components.hrworks.api import WorkerError, create_client
from custom_components.hrworks.config_flow import HrworksConfigFlow
from custom_components.hrworks.coordinator import HrworksCoordinator
from custom_components.hrworks.hrworks.browser_daemon import BrowserDaemonClient, script

SSH = {
    "ssh_host": "host",
    "ssh_port": 22,
    "ssh_username": "user",
    "ssh_key_path": "/key",
    "ssh_known_hosts": "host ssh-ed25519 AAAA",
    "worker_command": "hrworks worker",
}
ACCOUNT = {
    "company_id": "example",
    "username": "employee",
    "password": "test-password",
    "totp_uri": "otpauth://totp/Example:test?secret=JBSWY3DPEHPK3PXP",
    "profile_id": "a" * 64,
}


def flow(data):
    result = HrworksConfigFlow()
    result.hass = MagicMock()
    result.context = {"source": "reconfigure"}
    result._entry = SimpleNamespace(data=dict(data), title="HR WORKS")
    result._get_reconfigure_entry = lambda: result._entry
    result._data = dict(data)  # what the reconfigure menu step loads
    result.async_step_account = AsyncMock(return_value={"type": "account"})
    return result


def fake_client():
    return SimpleNamespace(health=AsyncMock(return_value={}), close=AsyncMock())


class ReconfigureTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconfigure_offers_both_backends(self):
        result = await flow({**ACCOUNT, **SSH}).async_step_reconfigure()
        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["menu_options"], ["reconfigure_browser_daemon", "reconfigure_ssh"])

    async def test_ssh_entry_switches_to_browser_daemon_keeping_the_account(self):
        flow_ = flow({**ACCOUNT, **SSH, "backend": "ssh"})
        await flow_.async_step_reconfigure()
        form = await flow_.async_step_reconfigure_browser_daemon()
        self.assertEqual(form["step_id"], "reconfigure_browser_daemon")
        client = fake_client()
        with patch.object(config_flow, "create_client", return_value=client) as create:
            await flow_.async_step_reconfigure_browser_daemon(
                {
                    "browser_daemon_url": "https://bd.example",
                    "browser_daemon_secret": "cluster",
                    "browser_daemon_profile": "hrworks",
                    "name": "Work",
                }
            )
        self.assertEqual(create.call_args.args[1]["browser_daemon_url"], "https://bd.example")
        client.health.assert_awaited_once()
        data = flow_._data
        self.assertEqual(data["backend"], "browser_daemon")
        for key in ("company_id", "username", "password", "totp_uri", "profile_id"):
            self.assertEqual(data[key], ACCOUNT[key])
        self.assertEqual(data["browser_daemon_secret"], "cluster")
        self.assertEqual(flow_._title, "Work")
        flow_.async_step_account.assert_awaited_once()

    async def test_blank_secret_keeps_the_saved_one(self):
        flow_ = flow({**ACCOUNT, "backend": "browser_daemon", "browser_daemon_secret": "kept"})
        with patch.object(config_flow, "create_client", return_value=fake_client()):
            await flow_.async_step_reconfigure_browser_daemon(
                {"browser_daemon_url": "http://bd", "browser_daemon_profile": "p"}
            )
        self.assertEqual(flow_._data["browser_daemon_secret"], "kept")

    async def test_switching_back_to_ssh_drops_the_cluster_secret(self):
        flow_ = flow(
            {
                **ACCOUNT,
                "backend": "browser_daemon",
                "browser_daemon_url": "https://bd.example",
                "browser_daemon_secret": "cluster",
                "browser_daemon_profile": "hrworks",
            }
        )
        with patch.object(config_flow, "create_client", return_value=fake_client()):
            await flow_.async_step_reconfigure_ssh({**SSH, "name": "HR WORKS"})
        data = flow_._data
        self.assertEqual(data["backend"], "ssh")
        self.assertEqual(data["ssh_host"], "host")
        self.assertEqual(data["password"], "test-password")
        self.assertEqual(data["totp_uri"], ACCOUNT["totp_uri"])
        for key in ("browser_daemon_url", "browser_daemon_secret", "browser_daemon_profile"):
            self.assertNotIn(key, data)

    async def test_empty_url_stores_no_secret(self):
        flow_ = flow({**ACCOUNT, "backend": "browser_daemon", "browser_daemon_secret": "old"})
        with patch.object(config_flow, "create_client", return_value=fake_client()):
            await flow_.async_step_reconfigure_browser_daemon(
                {
                    "browser_daemon_url": "",
                    "browser_daemon_secret": "typed",
                    "browser_daemon_profile": "p",
                }
            )
        self.assertEqual(flow_._data["browser_daemon_url"], "")
        self.assertIsNone(flow_._data["browser_daemon_secret"])

    async def test_url_without_secret_is_invalid(self):
        flow_ = flow({**ACCOUNT, **SSH})
        with patch.object(config_flow, "create_client") as create:
            result = await flow_.async_step_reconfigure_browser_daemon(
                {"browser_daemon_url": "https://bd.example", "browser_daemon_profile": "p"}
            )
        self.assertEqual(result["errors"], {"base": "invalid_request"})
        create.assert_not_called()

    async def test_url_needs_a_web_scheme(self):
        flow_ = flow({**ACCOUNT, **SSH})
        result = await flow_.async_step_reconfigure_browser_daemon(
            {
                "browser_daemon_url": "ftp://bd",
                "browser_daemon_secret": "s",
                "browser_daemon_profile": "p",
            }
        )
        self.assertEqual(result["errors"], {"base": "invalid_request"})

    async def test_missing_browser_daemon_integration_is_cannot_connect(self):
        flow_ = flow({**ACCOUNT, **SSH})
        with patch.dict(sys.modules, {"custom_components.browser_daemon": None}):
            result = await flow_.async_step_reconfigure_browser_daemon(
                {"browser_daemon_url": "", "browser_daemon_profile": "p"}
            )
        self.assertEqual(result["errors"], {"base": "cannot_connect"})

    async def test_ssh_form_marks_the_backend(self):
        flow_ = flow({**ACCOUNT, "backend": "browser_daemon"})
        with patch.object(config_flow, "create_client", return_value=fake_client()):
            await flow_.async_step_reconfigure_ssh({**SSH})
        self.assertEqual(flow_._data["backend"], "ssh")


class CreateClientTests(unittest.TestCase):
    def shared(self, **attributes):
        module = ModuleType("custom_components.browser_daemon")
        module.async_get_client = MagicMock(return_value=SimpleNamespace(**attributes))
        return patch.dict(sys.modules, {"custom_components.browser_daemon": module}), module

    def settings(self, **extra):
        return {"backend": "browser_daemon", "browser_daemon_profile": "hrworks", **extra}

    def test_empty_url_uses_the_shared_connection_without_storing_it(self):
        patcher, module = self.shared(base_url="http://shared:3001", cluster_secret="shared-secret")
        settings = self.settings(browser_daemon_url="", browser_daemon_secret=None)
        hass = MagicMock()
        with patcher, patch.object(api, "async_get_clientsession", return_value="http"):
            client = create_client(hass, settings)
        module.async_get_client.assert_called_once_with(hass)
        self.assertEqual(client.settings["browser_daemon_url"], "http://shared:3001")
        self.assertEqual(client.settings["browser_daemon_secret"], "shared-secret")
        self.assertEqual(settings["browser_daemon_url"], "")
        self.assertIsNone(settings["browser_daemon_secret"])

    def test_an_explicit_url_ignores_the_shared_connection(self):
        patcher, module = self.shared(base_url="http://shared", cluster_secret="x")
        settings = self.settings(browser_daemon_url="https://own", browser_daemon_secret="own")
        with patcher, patch.object(api, "async_get_clientsession", return_value="http"):
            client = create_client(MagicMock(), settings)
        module.async_get_client.assert_not_called()
        self.assertEqual(client.settings["browser_daemon_secret"], "own")

    def test_missing_integration_is_cannot_connect(self):
        with patch.dict(sys.modules, {"custom_components.browser_daemon": None}):
            with self.assertRaises(WorkerError) as err:
                create_client(MagicMock(), self.settings())
        self.assertEqual(err.exception.code, "cannot_connect")

    def test_unconfigured_integration_is_cannot_connect(self):
        patcher, _ = self.shared(base_url=None, cluster_secret=None)
        with patcher, self.assertRaises(WorkerError) as err:
            create_client(MagicMock(), self.settings())
        self.assertEqual(err.exception.code, "cannot_connect")


class FakeDaemon:
    """Answers runs by operation: snapshots first fail as expired, then succeed."""

    def __init__(self):
        self.operations = []
        self.snapshots = 0
        self.args = {}

    async def run(self, **kwargs):
        from custom_components.hrworks.hrworks import browser_daemon

        operation = next(n for n in browser_daemon.OPERATIONS if script(n) == kwargs["script"])
        self.operations.append(operation)
        self.args[operation] = kwargs["args"]
        if operation == "snapshot":
            self.snapshots += 1
            if self.snapshots == 1:
                raise RunError(RunResult(ok=False, error="hrworks:session_expired"), 422)
            return RunResult(
                ok=True,
                result={
                    "account": {"metrics": {}, "period": None, "balance_basis": None},
                    "lists": [],
                    "today": {"metrics": {}, "entries": []},
                    "clock": None,
                    "timings": {},
                },
            )
        if operation == "login":
            return RunResult(ok=True, result={"mfa_required": True}, page="TAB")
        return RunResult(ok=True, result={"authenticated": True})

    async def close_tab(self, _tab):
        pass

    async def find_profile(self, _name):
        return {"session_id": "s-1"}


class RecoveryWithBrowserDaemonTests(unittest.IsolatedAsyncioTestCase):
    async def test_expired_session_logs_in_again_with_the_saved_login_and_totp(self):
        data = {**ACCOUNT, "backend": "browser_daemon", "browser_daemon_profile": "hrworks"}
        daemon = FakeDaemon()
        client = BrowserDaemonClient(data, daemon=daemon)
        coordinator = object.__new__(HrworksCoordinator)
        coordinator.entry = SimpleNamespace(entry_id="e", options={}, data=data)
        coordinator.client = client
        coordinator.hass = MagicMock()
        coordinator.hass.data = {}
        coordinator.last_error = coordinator.last_error_stage = coordinator.last_error_detail = None
        coordinator._auth_recovery_blocked = False
        coordinator._normal_update_interval = timedelta(minutes=15)
        coordinator.update_interval = coordinator._normal_update_interval
        coordinator._work_days = AsyncMock(return_value=[])
        coordinator.update_count = coordinator.failed_updates = 0
        coordinator.consecutive_failures = coordinator.reauthentications = 0
        coordinator.last_duration = coordinator.last_finished = None
        with patch("custom_components.hrworks.coordinator.clear_issues"):
            result = await coordinator._async_update_data()
        self.assertEqual(daemon.operations, ["snapshot", "login", "mfa", "snapshot"])
        self.assertEqual(daemon.args["login"]["password"], "test-password")
        self.assertTrue(daemon.args["login"]["force"])
        self.assertRegex(daemon.args["mfa"]["code"], r"^\d{6}$")
        self.assertEqual(coordinator.reauthentications, 1)
        self.assertEqual(result["work_days"], [])
        self.assertEqual(result["diagnostics"]["backend"], "browser-daemon")

    async def test_login_timeout_keeps_its_stage_for_diagnostics(self):
        daemon = FakeDaemon()

        async def run(**_kwargs):
            raise RunError(RunResult(ok=False, error="hrworks:login_timeout"), 422)

        daemon.run = run
        client = BrowserDaemonClient({**ACCOUNT, "backend": "browser_daemon"}, daemon=daemon)
        with self.assertRaises(WorkerError) as err:
            await client.login("example", "employee", "pw")
        self.assertEqual(
            (err.exception.code, err.exception.stage, err.exception.detail),
            ("login_timeout", "browser_operation", "timeout"),
        )


if __name__ == "__main__":
    unittest.main()
