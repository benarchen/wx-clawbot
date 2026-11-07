"""Exercise receive routing with real catalog/verification and isolated state."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from wx_clawbot.agents.base import Capabilities
from wx_clawbot.catalog import SessionCatalog
from wx_clawbot.channels.wechat import Credentials
from wx_clawbot.config import Project
from wx_clawbot.controller import Controller
from wx_clawbot.execution import Execution
from wx_clawbot.hosts.discovery import TerminalEndpoint
from wx_clawbot.hosts.process import ProcessIdentity
from wx_clawbot.hosts.visible import LaunchRegistry
from wx_clawbot.runtime_state import RuntimeState
from test_wechat_state import message


class IndependentTargetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        parent = Path(__file__).resolve().parents[1] / '.tmp' / 'independent-target-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = Project('fixture', self.root)
        self.endpoint = TerminalEndpoint('terminal', ProcessIdentity(123, (1, 2), '/fixture/codex', 101), 'codex_candidate')
        self.directory = SimpleNamespace(discover=AsyncMock(return_value=[self.endpoint]),
            validate=AsyncMock(return_value=True), cwd=AsyncMock(return_value=self.root),
            current_thread_id=AsyncMock(return_value='thread-a'))
        self.threads = {key: {'id': key, 'sessionId': 'session-' + key, 'cwd': str(self.root),
                              'status': {'type': 'idle'}, 'name': key} for key in ('thread-a', 'thread-b')}
        self.agent = SimpleNamespace(runtime_identity=(1, 2),
            capabilities=Capabilities(observe=True, queue=True),
            list_project_threads=AsyncMock(return_value={'data': [self.threads['thread-a']]}),
            inspect=AsyncMock(side_effect=lambda key: self.threads[key]), observe_loaded=AsyncMock(),
            unsubscribe=AsyncMock(return_value='unsubscribed'))
        self.catalog = SessionCatalog((self.project,), self.directory, self.agent)
        self.catalog.managed_threads.add('thread-a')
        self.state = await RuntimeState.open(self.root / 'private/runtime.sqlite3',
            Credentials('fixture-bot', 'fixture-owner', 'https://ilinkai.weixin.qq.com/', 'synthetic'))
        self.addAsyncCleanup(self.state.close)
        self.starter = SimpleNamespace(registry=LaunchRegistry(self.root / 'launches'), start=AsyncMock())
        self.controller = Controller((self.project,), self.catalog, self.state, self.starter,
                                     Path('/fixture/codex'), Path('/fixture/home'))
        self.engine = Execution(self.controller)
        self.addAsyncCleanup(self.engine.close)
        self.queues = {key: SimpleNamespace(add=AsyncMock(return_value={'id': 'queue-' + key})) for key in self.threads}
        self.engine.queue = lambda key, _: self.queues[key]
        self.counter = 0
        await self.command('/sessions')
        await self.command('/focus 1')
        self.a = self.controller.routes.target

    async def command(self, text):
        self.counter += 1
        incoming = (await self.state.accept_batch({'ret': 0, 'msgs': [message(self.counter, text=text)]},
                                                phase='runtime'))['accepted'][0]
        await self.controller.prepare(incoming)

    def desktop_switch(self):
        self.agent.list_project_threads.return_value = {'data': list(self.threads.values())}
        self.directory.current_thread_id.return_value = 'thread-b'

    async def test_desktop_switch_preserves_focus_and_submits_only_to_original_thread(self):
        self.desktop_switch()
        await self.command('Continue the architecture discussion')
        self.assertEqual(self.controller.routes.target, self.a)
        task = (await self.state.tasks())[0]
        self.assertEqual(task['thread_id'], 'thread-a')
        self.queues['thread-a'].add.assert_awaited_once()
        self.queues['thread-b'].add.assert_not_called()
        await self.command('/sessions')
        targets = self.controller.routes.list.targets
        number = next(i for i, target in enumerate(targets, 1)
                      if self.catalog.sessions[target.session_id].binding.thread_id == 'thread-b')
        await self.command('/focus ' + str(number))
        self.assertEqual(self.catalog.sessions[self.controller.routes.target.session_id].binding.thread_id, 'thread-b')
        self.assertEqual((await self.state.tasks())[0]['thread_id'], 'thread-a')

    async def test_closed_terminal_refuses_message_notifies_and_preserves_selected_target(self):
        self.desktop_switch()
        self.directory.discover.return_value = []
        self.directory.validate.return_value = False
        await self.command('Must not reach B')
        self.assertEqual(self.controller.routes.target, self.a)
        self.assertEqual(await self.state.tasks(), [])
        for queue in self.queues.values():
            queue.add.assert_not_called()
        texts = await self.state._call(lambda: [row[0] for row in self.state.db.execute('SELECT text FROM outbox')])
        self.assertTrue(any('所选会话无法可靠接入' in text and '不会自动切换' in text for text in texts))

    async def test_cd_reuses_managed_a_after_desktop_switch_without_creating_replacement(self):
        self.desktop_switch()
        await self.command('/cd fixture')
        self.assertEqual(self.controller.routes.target, self.a)
        self.starter.start.assert_not_called()

    async def test_unloaded_original_is_refused_instead_of_redirected_to_b(self):
        self.desktop_switch()
        self.threads['thread-a']['status'] = {'type': 'notLoaded'}
        await self.command('Must not restore A or send to B')
        self.assertEqual(self.controller.routes.target, self.a)
        self.assertEqual(await self.state.tasks(), [])
        self.queues['thread-b'].add.assert_not_called()
        self.agent.observe_loaded.assert_awaited_once_with('thread-a', self.root)
