"""Backend choice in the config flow and in create_client, with fake clients only."""

import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.hrworks import api, config_flow
from custom_components.hrworks.api import WorkerError, create_client
from custom_components.hrworks.config_flow import HrworksConfigFlow

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


if __name__ == "__main__":
    unittest.main()
