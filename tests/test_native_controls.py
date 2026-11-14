"""Native controls use structured reads and preserve the unverified write gate."""

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from markdown_it import MarkdownIt

from wx_clawbot.commands import CommandError, parse_command
from wx_clawbot.controller import HELP
from wx_clawbot.native_controls import NativeControls, fast_state, model_catalog
from wx_clawbot.output import display_segments
from wx_clawbot.routing import Target


def model(name='fixture-model'):
    return {'model': name, 'displayName': name, 'supportedReasoningEfforts': [
        {'reasoningEffort': 'medium'}, {'reasoningEffort': 'high'}],
        'serviceTiers': [{'id': 'fixture-priority', 'name': 'Fast'}], 'defaultServiceTier': None}


def token_value(total=10):
    value = dict(inputTokens=4, outputTokens=6, cachedInputTokens=0,
                 reasoningOutputTokens=0, totalTokens=total)
    return {'last': value.copy(), 'total': value.copy()}


class NativeGrammarTests(unittest.TestCase):
    def test_seven_entries_have_explicit_actions(self):
        cases = {'/model': ('model', 'get', ''), '/model list': ('model', 'list', ''),
                 '/model set auto/fixture': ('model', 'set', 'auto/fixture'),
                 '/model set auto/fixture high': ('model', 'set', 'auto/fixture'),
                 '/fast': ('fast', 'get', ''), '/fast on': ('fast', 'on', ''),
                 '/fast off': ('fast', 'off', ''), '/codex status': ('codex', 'status', '')}
        for text, expected in cases.items():
            with self.subTest(text=text):
                result = parse_command(text)
                self.assertEqual((result.name, result.argument, result.text), expected)
                self.assertEqual(result.reasoning,'high' if text.endswith(' high') else None)
        self.assertEqual(parse_command('/status').name, 'status')

    def test_unapproved_commands_and_compound_options_never_become_tasks(self):
        for text in ('/model --speed=fast', '/model one --reasoning=high', '/model --reasoning=',
                     '/model fixture', '/model --reasoning=high', '/model set',
                     '/model set fixture high extra', '/model set fixture --reasoning=high',
                     '/model set fixture\nhigh', '/model set fixture HIGH',
                     '/model set $(touch BAD)', '/model set '+ 'a'*257,
                     '/model --reasoning=high extra', '/model --reasoning=high\nnext',
                     '/model ' + 'a'*257, '/model $(touch BAD)', '/model "name with spaces"',
                     '/fast toggle', '/fast on off', '/codex help', '/codex', '/codex status extra',
                     '/MODEL list', '/model list;whoami'):
            with self.subTest(text=text), self.assertRaises(CommandError):
                parse_command(text)

    def test_help_native_section_remains_a_bridge_help_and_renders(self):
        self.assertIn('**Codex 原生命令**', HELP)
        for syntax in ('/model list', '/model set <模型名称> [推理强度]',
                       '/fast on', '/fast off', '/codex status'):
            self.assertIn(syntax, HELP)
        self.assertNotIn('/codex help', HELP)
        rendered = ''.join(display_segments(HELP))
        self.assertNotIn('【二级标题】', rendered)
        self.assertIn('<strong>Codex 原生命令</strong>', MarkdownIt().render(rendered))


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    def native(self, pages):
        return SimpleNamespace(server_version='0.167.0', runtime_identity=(1, 2),
                               rpc=SimpleNamespace(request=AsyncMock(side_effect=pages)))

    async def test_pages_are_complete_unique_and_read_only(self):
        native = self.native([{'data': [model('one')], 'nextCursor': 'page-2'}, {'data': [model('two')]}])
        result = await model_catalog(native)
        self.assertEqual(list(result), ['one', 'two'])
        self.assertEqual(result['one']['tiers'][0]['id'], 'fixture-priority')
        self.assertIsNone(result['one']['default_effort'])
        self.assertEqual(native.rpc.request.call_args_list[1].args,
                         ('model/list', {'limit': 100, 'includeHidden': False, 'cursor': 'page-2'}))

    async def test_0169_catalog_uses_selected_provider_without_changing_it(self):
        native=self.native([{'data':[model()]}]);native.server_version='0.169.0'
        await model_catalog(native,provider='selected-provider')
        native.rpc.request.assert_awaited_once_with('model/list',{'limit':100,'includeHidden':False,'modelProvider':'selected-provider'})

    async def test_old_catalog_does_not_send_new_provider_parameter(self):
        native=self.native([{'data':[model()]}]);await model_catalog(native,provider='selected-provider')
        native.rpc.request.assert_awaited_once_with('model/list',{'limit':100,'includeHidden':False})

    async def test_empty_and_optional_metadata_do_not_invent_capabilities(self):
        self.assertEqual(await model_catalog(self.native([{'data': []}])), {})
        result = await model_catalog(self.native([{'data': [{'model': 'one'}]}]))
        self.assertEqual(result['one']['efforts'], [])
        self.assertIsNone(result['one']['tiers'])
        self.assertFalse(result['one']['default_provided'])

    async def test_duplicate_rows_cursors_and_invalid_fields_fail_closed(self):
        bad = [None, {'data': None}, {'data': [model(), model()]},
               {'data': [{'model': 'bad\nidentity'}]}, {'data': [dict(model(), supportedReasoningEfforts=[None])]},
               {'data': [dict(model(), serviceTiers=[{'id': 'tier'}])]},
               {'data': [dict(model(), serviceTiers=[{'id': 'a', 'name': 'Fast'}, {'id': 'a', 'name': 'Other'}])]},
               {'data': [dict(model(), defaultServiceTier=1)]}, {'data': [dict(model(), displayName='\nprivate')]},
               {'data': [dict(model(), defaultReasoningEffort=None)]},
               {'data': [dict(model(), defaultReasoningEffort='bad\nvalue')]},
               {'data': [], 'nextCursor': ''}]
        for page in bad:
            with self.subTest(page=page), self.assertRaises((CommandError, ValueError)):
                await model_catalog(self.native([page]))
        with self.assertRaises(CommandError):
            await model_catalog(self.native([{'data': [], 'nextCursor': 'same'}]*2))

    async def test_pagination_and_byte_bounds_refuse_incomplete_catalog(self):
        with self.assertRaises(CommandError):
            await model_catalog(self.native([{'data': [], 'nextCursor': str(i)} for i in range(10)]))
        with self.assertRaises(CommandError):
            await model_catalog(self.native([{'data': [], 'extra': 'x'*(2*1024*1024)}]))
        with self.assertRaises(CommandError):
            await model_catalog(self.native([{'data': [model(str(i)) for i in range(101)]}]))

    async def test_version_and_generation_are_part_of_query_authority(self):
        native = self.native([]); native.server_version = '0.168.0'
        with self.assertRaises(CommandError):
            await model_catalog(native)
        native.rpc.request.assert_not_awaited()
        native = self.native([])
        async def changed(*args):
            native.runtime_identity = (3, 4)
            return {'data': [model()]}
        native.rpc.request.side_effect = changed
        with self.assertRaises(CommandError):
            await model_catalog(native)

    async def test_fast_uses_catalog_ids_and_distinguishes_unknown_and_unsupported(self):
        rows = await model_catalog(self.native([{'data': [model()]}]));row = rows['fixture-model']
        self.assertEqual(fast_state({'serviceTier': 'fixture-priority'}, row), '已开启')
        self.assertIn('未开启', fast_state({'serviceTier': None}, row))
        self.assertEqual(fast_state({'serviceTier': 'default'}, row), '未开启')
        self.assertIn('无法确认', fast_state({}, row))
        self.assertIn('无法确认', fast_state({'serviceTier': 'unknown'}, row))
        self.assertEqual(fast_state({}, dict(row, tiers=[])), '不支持')
        self.assertIn('无法确认', fast_state({}, dict(row, tiers=None)))
        self.assertIn('无法确认', fast_state({'serviceTier': None}, dict(row, default_provided=False)))
        self.assertIn('无法确认', fast_state({}, None))


class NativeQueryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.target = Target('s-fixture', 'fixture', Path('/fixture/project'))
        self.thread = 'thread-fixture'
        self.native = SimpleNamespace(server_version='0.167.0', runtime_identity=(1, 2),
            read_settings=AsyncMock(return_value={'model': 'fixture-model', 'modelProvider': 'fixture-provider',
                'reasoningEffort': 'high', 'serviceTier': None}),
            inspect=AsyncMock(return_value={'status': {'type': 'idle'}}),
            rpc=SimpleNamespace(request=AsyncMock(return_value={'data': [model()]})))
        self.controller = SimpleNamespace(retired=False, native_ready=True, selection_pending=0,
            routes=SimpleNamespace(revision=1, target=self.target),
            catalog=SimpleNamespace(require=AsyncMock(return_value=SimpleNamespace(binding=SimpleNamespace(thread_id=self.thread)))),
            subscriptions=SimpleNamespace(event_session=Mock(), roles={'s-fixture': {'route'}}))
        self.queue = SimpleNamespace(list=AsyncMock(return_value=[]))
        self.engine = SimpleNamespace(controller=self.controller, native=self.native,
            verified_native=Mock(return_value=(1, (1, 2))), queue=Mock(return_value=self.queue))
        self.controls = NativeControls(self.engine)

    async def execute(self, text, target=True):
        return await self.controls.execute(parse_command(text), self.target if target else None, 1)

    async def test_model_read_has_fresh_snapshot_no_usage_or_catalog_calls(self):
        text = await self.execute('/model')
        self.assertIn('fixture-model', text);self.assertIn('high', text)
        self.native.rpc.request.assert_not_awaited();self.engine.queue.assert_not_called()
        self.assertEqual(self.controller.catalog.require.await_count, 2)
        self.native.read_settings.assert_awaited_once_with(self.thread, self.target.cwd)

    async def test_list_works_without_target_and_never_subscribes(self):
        self.controller.routes.target = None
        text = await self.execute('/model list', target=False)
        self.assertIn('fixture-model', text)
        self.assertIn('默认：未提供', text)
        self.assertIn('不等于', text)
        self.native.read_settings.assert_not_awaited();self.controller.catalog.require.assert_not_awaited()

    async def test_every_write_requires_stable_source_identity_before_native_requests(self):
        for command in ('/model set other', '/model set other high', '/fast on', '/fast off'):
            with self.subTest(command=command), self.assertRaisesRegex(CommandError, '未发送'):
                await self.execute(command)
        self.native.rpc.request.assert_not_awaited();self.native.read_settings.assert_not_awaited()

    async def test_only_input_target_and_live_revision_can_authorize_read(self):
        for field,value in (('revision', 2), ('target', None)):
            before = getattr(self.controller.routes, field);setattr(self.controller.routes, field, value)
            with self.subTest(field=field), self.assertRaises(CommandError):
                await self.execute('/model')
            setattr(self.controller.routes, field, before)
        self.controller.selection_pending = 1
        with self.assertRaises(CommandError):await self.execute('/model')
        self.native.read_settings.assert_not_awaited()

    async def test_observer_role_does_not_substitute_for_input_subscription(self):
        self.controller.subscriptions.roles['s-fixture'] = {'observer'}
        with self.assertRaises(CommandError):await self.execute('/model')
        self.native.read_settings.assert_not_awaited()

    async def test_target_change_while_reading_refuses_old_reply(self):
        async def changed(*args):
            self.controller.routes.revision = 2
            return {'model': 'fixture-model'}
        self.native.read_settings.side_effect = changed
        with self.assertRaisesRegex(CommandError, '目标已变化'):
            await self.execute('/model')

    async def test_read_error_is_bounded_and_never_leaks_native_error_content(self):
        self.native.read_settings.side_effect = ValueError('SENSITIVE-PROVIDER-DETAILS')
        with self.assertRaises(CommandError) as error:await self.execute('/model')
        self.assertNotIn('SENSITIVE', str(error.exception))
        self.assertIn('ValueError', str(error.exception))

    async def test_missing_values_are_not_defaults_or_zero_usage(self):
        self.native.read_settings.return_value = {}
        text = await self.execute('/codex status')
        self.assertIn('模型：原生未提供', text)
        self.assertIn('思考等级：原生未提供', text)
        self.assertNotIn('服务档位', text)
        self.assertIn('无法确认', text)
        self.assertIn('账号额度：暂时无法查询', text)
        self.assertNotIn('token', text)
        self.assertNotIn('%', text)
        self.queue.list.assert_awaited_once()

    async def test_status_reads_account_quota_separately_and_other_queries_do_not(self):
        async def read(method,params,**kwargs):
            if method=='model/list':return {'data':[model()]}
            self.assertEqual((method,params,kwargs),('account/rateLimits/read',{'excludeResetCreditDetails':True},{'timeout':5}))
            return {'rateLimits':{'primary':{'usedPercent':86,'windowDurationMins':300}}}
        self.native.rpc.request.side_effect=read
        text=await self.execute('/codex status')
        self.assertNotIn('token',text)
        self.assertIn('非本会话专属',text)
        self.assertIn('5 小时：剩余 **14%**',text)
        self.native.rpc.request.reset_mock()
        await self.execute('/model');await self.execute('/fast')
        self.assertEqual([call.args[0] for call in self.native.rpc.request.call_args_list],['model/list'])

    async def test_fast_read_is_not_a_toggle_and_unsupported_is_explicit(self):
        self.assertIn('未开启', await self.execute('/fast'))
        self.native.rpc.request.return_value = {'data': [dict(model(), serviceTiers=[])]}
        self.assertIn('不支持', await self.execute('/fast'))
        self.assertEqual(self.native.read_settings.await_count, 2)
        self.assertTrue(all(call.args[0]=='model/list' for call in self.native.rpc.request.call_args_list))

    async def test_usage_remains_scoped_bounded_and_hidden_from_default_status(self):
        c=self.controls
        c.event('turn/started', {'threadId': self.thread, 'turn': {'id': 'turn-new'}})
        c.event('thread/tokenUsage/updated', {'threadId': self.thread, 'turnId': 'turn-old', 'tokenUsage': token_value(99)})
        self.assertNotIn(self.thread,c.usage)
        c.event('thread/tokenUsage/updated', {'threadId': self.thread, 'turnId': 'turn-new', 'tokenUsage': token_value(10)})
        c.event('thread/tokenUsage/updated', {'threadId': self.thread, 'turnId': 'turn-new', 'tokenUsage': token_value(5)})
        text = await self.execute('/codex status')
        self.assertEqual(c.usage[self.thread]['usage']['total']['totalTokens'],10)
        self.assertEqual(c.usage[self.thread]['turn'],'turn-new')
        for hidden in ('token','totalTokens','turn-new','turn-old','上下文上限'):
            self.assertNotIn(hidden,text)
        self.assertNotIn('%',text)
        self.native.runtime_identity=(3,4)
        self.assertNotIn('token',await self.execute('/codex status'))

    async def test_invalid_usage_never_crashes_or_becomes_real_zero(self):
        for payload in (None,{}, {'last':{}},dict(token_value(),modelContextWindow=True)):
            self.controls.event('thread/tokenUsage/updated',{'threadId':self.thread,'turnId':'turn','tokenUsage':payload})
        bad=token_value();bad['last']['totalTokens']=True
        self.controls.event('thread/tokenUsage/updated',{'threadId':self.thread,'turnId':'turn','tokenUsage':bad})
        self.controls.event('turn/started',{'threadId':self.thread,'turn':[]})
        self.assertFalse(self.controls.usage)
        for i in range(257):
            self.controls.event('thread/tokenUsage/updated',{'threadId':f'thread-{i}','turnId':'turn','tokenUsage':token_value()})
        self.assertLessEqual(len(self.controls.usage),256);self.assertLessEqual(len(self.controls.turns),256)
