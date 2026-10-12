"""Worker lifecycle: idle browser release and bounded shutdown."""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from hrworks_worker import server
from hrworks_worker.server import Worker


class WorkerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.worker = Worker(state_dir=Path(self.directory.name))

    def tearDown(self):
        self.directory.cleanup()

    def connect(self):
        self.worker.playwright = MagicMock(stop=AsyncMock())
        self.worker.browser = MagicMock(is_connected=MagicMock(return_value=True))

    async def test_close_does_not_hang_on_a_wedged_context(self):
        self.connect()
        playwright = self.worker.playwright
        portal = MagicMock(release=AsyncMock(side_effect=asyncio.Event().wait))
        self.worker.profiles["a" * 64] = portal
        with patch.object(server, "RELEASE_TIMEOUT_SECONDS", 0.05):
            await asyncio.wait_for(self.worker.close(), 1)
        self.assertFalse(self.worker.connected)
        self.assertIsNone(self.worker.browser)
        self.assertIsNone(portal.page)
        playwright.stop.assert_awaited()

    async def test_idle_worker_releases_browser_but_keeps_running(self):
        self.connect()
        read_fd, write_fd = os.pipe()
        stdin = os.fdopen(read_fd, "rb", buffering=0)
        self.worker.close = AsyncMock(side_effect=self.worker.close)
        with (
            patch.object(server, "BROWSER_IDLE_SECONDS", 0.05),
            patch.object(server.sys, "stdin", stdin),
        ):
            serving = asyncio.create_task(server.serve(self.worker))
            await asyncio.sleep(0.3)
            self.assertFalse(serving.done())
            self.assertFalse(self.worker.connected)
            os.close(write_fd)
            await asyncio.wait_for(serving, 1)
        # Released once while idle, closed once more on EOF; no idle loop.
        self.assertEqual(self.worker.close.await_count, 2)

    async def test_pending_mfa_keeps_browser(self):
        self.connect()
        self.worker.profiles["a" * 64] = MagicMock(mfa_pending=True, release=AsyncMock())
        read_fd, write_fd = os.pipe()
        stdin = os.fdopen(read_fd, "rb", buffering=0)
        with (
            patch.object(server, "BROWSER_IDLE_SECONDS", 0.05),
            patch.object(server.sys, "stdin", stdin),
        ):
            serving = asyncio.create_task(server.serve(self.worker))
            await asyncio.sleep(0.3)
            self.assertTrue(self.worker.connected)
            os.close(write_fd)
            await asyncio.wait_for(serving, 1)


if __name__ == "__main__":
    unittest.main()
