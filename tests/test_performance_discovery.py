import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from wx_clawbot.catalog import SessionCatalog
from wx_clawbot.config import Project
from wx_clawbot.hosts.discovery import ItermDirectory, TerminalEndpoint
from wx_clawbot.hosts.process import ProcessIdentity
from wx_clawbot.hosts.lifecycle import HostUnavailable


async def discovery_counts(root, count):
    endpoints = {f'terminal-{i}': TerminalEndpoint(f'terminal-{i}',
        ProcessIdentity(i+1, (1, i), '/synthetic/codex', i+1), 'codex_candidate') for i in range(count)}
    sessions = [SimpleNamespace(session_id=key) for key in endpoints]
    app = SimpleNamespace(windows=[SimpleNamespace(tabs=[SimpleNamespace(sessions=sessions)])],
        get_session_by_id=lambda key: next((s for s in sessions if s.session_id==key), None))
    checks = []
    async def inspect(session):
        checks.append(session.session_id)
        return endpoints[session.session_id]
    directory = ItermDirectory(None)
    threads = {'thread-'+key: {'id':'thread-'+key, 'sessionId':'session-'+key,
        'cwd':str(root), 'status':{'type':'idle'}} for key in endpoints}
    agent = SimpleNamespace(runtime_identity=(1,1),
        loaded_threads=AsyncMock(return_value=frozenset(threads)),
        list_project_threads=AsyncMock(return_value={'data':list(threads.values())}),
        inspect=AsyncMock(side_effect=lambda key: threads[key]))
    catalog = SessionCatalog((Project('synthetic',root),),directory,agent)
    with patch('iterm2.async_get_app', new=AsyncMock(return_value=app)) as get_app, \
            patch('wx_clawbot.hosts.discovery.inspect_terminal', side_effect=inspect), \
            patch.object(ItermDirectory,'cwd',new=AsyncMock(return_value=root)), \
            patch.object(ItermDirectory,'current_thread_id',new=AsyncMock(side_effect=lambda e:'thread-'+e.terminal_id)):
        found = await catalog.discover()
        discovery_checks = len(checks)
        enumerations = get_app.await_count
        checks.clear()
        get_app.reset_mock()
        await catalog.require(found[0].target)
    return {'endpoints':count,'found':len(found),'discovery_endpoint_checks':discovery_checks,
            'discovery_full_enumerations':enumerations,'require_fresh_enumerations':get_app.await_count,
            'require_endpoint_checks':len(checks),'require_no_host_identity':not checks}


class PerformanceDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_is_linear_and_require_reads_only_the_target(self):
        root = Path(__file__).resolve().parents[1]
        for count in (2,10,30,100):
            with self.subTest(count=count):
                result = await discovery_counts(root,count)
                self.assertEqual(result['found'],count)
                self.assertLessEqual(result['discovery_endpoint_checks'],8*count+8)
                self.assertLessEqual(result['discovery_full_enumerations'],2)
                self.assertEqual(result['require_fresh_enumerations'],0)
                self.assertLessEqual(result['require_endpoint_checks'],6)
                self.assertTrue(result['require_no_host_identity'])

    async def test_discovery_view_cannot_cross_host_connection_generation(self):
        original,replacement=object(),object()
        lifecycle=SimpleNamespace()
        async def call(work):
            return await work(original)
        lifecycle.call=call
        app=SimpleNamespace(windows=[])
        with patch('iterm2.async_get_app',new=AsyncMock(return_value=app)) as get_app:
            directory=ItermDirectory(lifecycle=lifecycle)
            view=await directory.discovery_view()
            self.assertEqual(await view.discover(),[])
            self.assertEqual(get_app.await_count,1)
            async def changed(work):
                return await work(replacement)
            lifecycle.call=changed
            with self.assertRaises(HostUnavailable):
                await view.discover()
            self.assertEqual(get_app.await_count,1)

    async def test_new_discovery_view_refreshes_list_instead_of_reusing_previous_view(self):
        with patch('iterm2.async_get_app',new=AsyncMock(return_value=SimpleNamespace(windows=[]))) as get_app:
            directory=ItermDirectory(object())
            first=await directory.discovery_view()
            second=await directory.discovery_view()
            self.assertIsNot(first,second)
            self.assertEqual(get_app.await_count,2)
