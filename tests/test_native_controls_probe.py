"""Offline guards for the explicitly authorized, otherwise unrun native probe."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch


spec = importlib.util.spec_from_file_location(
    'native_controls_probe', Path(__file__).parent/'integration/native_controls_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
bridge_spec=importlib.util.spec_from_file_location('native_control_bridge',Path(__file__).parent/'integration/native_control_bridge.py')
bridge=importlib.util.module_from_spec(bridge_spec);bridge_spec.loader.exec_module(bridge)


class ProbeGuards(unittest.IsolatedAsyncioTestCase):
    async def test_bridge_idle_poll_timeout_does_not_end_event_consumer(self):
        import asyncio
        event={'method':'fixture','params':{}}
        native=SimpleNamespace(rpc=SimpleNamespace(next_event=AsyncMock(side_effect=[TimeoutError(),event,asyncio.CancelledError()])))
        engine=SimpleNamespace(event=AsyncMock())
        with self.assertRaises(asyncio.CancelledError):await bridge.consume_events(native,engine)
        engine.event.assert_awaited_once_with(event)

    def test_sleep_accepts_native_shell_wrapper_without_extra_commands(self):
        for command in ('/bin/sleep 30', "/bin/zsh -c '/bin/sleep 30'", "/bin/bash -lc '/bin/sleep 30'"):
            self.assertTrue(probe.is_single_sleep(command))
        for command in ('sleep 30', "/bin/zsh -c '/bin/sleep 30; pwd'", '/bin/sleep 30 30', None, "'"):
            self.assertFalse(probe.is_single_sleep(command))

    async def test_stale_generation_never_sends_settings(self):
        for identity in (None, (1, 3)):
            native = SimpleNamespace(runtime_identity=identity,
                                     rpc=SimpleNamespace(request=AsyncMock()))
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                await probe.settings_request(native, [1, 2], {'threadId': 'owned'})
            native.rpc.request.assert_not_awaited()

    async def test_generation_change_during_rpc_cannot_be_accepted_as_ack(self):
        native = SimpleNamespace(runtime_identity=(1, 2))
        async def replaced(*args):
            native.runtime_identity = None
            return {}
        native.rpc = SimpleNamespace(request=AsyncMock(side_effect=replaced))
        with self.assertRaises(ValueError):
            await probe.settings_request(native, [1, 2], {'threadId': 'owned'})
        native.rpc.request.assert_awaited_once()

    async def test_existing_case_is_rejected_before_host_or_discovery(self):
        for phase in ('running', 'probe_complete', 'cleaned'):
            for action in ('run','bridge-run'):
                with self.subTest(phase=phase,action=action), \
                        patch.object(probe, 'read_json', return_value={'phase': phase}), \
                        patch.object(probe, 'HostLifecycle') as host, \
                        patch.object(probe, 'discover_runtime') as discover:
                    with self.assertRaises(ValueError):
                        await probe.run(Path('/unused'), action)
                    host.assert_not_called()
                    discover.assert_not_called()
