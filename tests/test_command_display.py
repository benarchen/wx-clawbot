"""Readable command output retains actionable identities and literal data."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from markdown_it import MarkdownIt

from wx_clawbot.commands import parse_command
from wx_clawbot.native_controls import NativeControls, rate_limit_lines
from wx_clawbot.output import display_segments, inline_literal, target_description, task_state
from wx_clawbot.routing import Target


class CommandDisplayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.target = Target('s-0123456789abcdef0123456789abcdef', 'fixture', Path('/fixture/phone-a'))
        self.native = SimpleNamespace(server_version='0.169.0', runtime_identity=(1, 2),
            read_settings=AsyncMock(return_value={'model': 'fixture-model', 'reasoningEffort': 'high', 'serviceTier': 'default'}),
            inspect=AsyncMock(return_value={'status': {'type': 'idle'}}),
            rpc=SimpleNamespace(request=AsyncMock(side_effect=self.read)))
        self.models = [{'model': 'fixture-model', 'displayName': 'DUPLICATE DISPLAY',
            'supportedReasoningEfforts': [{'reasoningEffort': v} for v in ('low', 'high')],
            'defaultReasoningEffort': 'low', 'serviceTiers': [{'name': 'Fast', 'id': 'priority'}]}]
        self.queue = SimpleNamespace(list=AsyncMock(return_value=[]))
        controller = SimpleNamespace(retired=False, selection_pending=0,
            routes=SimpleNamespace(revision=1, target=self.target),
            catalog=SimpleNamespace(require=AsyncMock(return_value=SimpleNamespace(binding=SimpleNamespace(thread_id='thread')))),
            subscriptions=SimpleNamespace(event_session=Mock(), roles={self.target.session_id: {'route'}}))
        self.controls = NativeControls(SimpleNamespace(controller=controller, native=self.native,
            verified_native=Mock(return_value=(1, (1, 2))), queue=Mock(return_value=self.queue)))

    async def read(self, method, params, **kwargs):
        if method == 'model/list': return {'data': self.models}
        return {'rateLimits': {'primary': {'usedPercent': 46, 'windowDurationMins': 300}},
                'rateLimitsByLimitId': {'codex': {'primary': {'usedPercent': 46, 'windowDurationMins': 300},
                                                'secondary': {'usedPercent': 7, 'windowDurationMins': 10080}}}}

    async def execute(self, command):
        return await self.controls.execute(parse_command(command), self.target, 1)

    def rendered(self, text):
        return ''.join(MarkdownIt().render(v) for v in display_segments(text))

    async def test_default_status_is_compact_and_has_no_debug_fields(self):
        text = await self.execute('/codex status')
        for value in ('思考等级：高（high）', 'Fast：未开启', '会话：空闲', '54%', '93%', '北京时间', 'phone-a'):
            self.assertIn(value, text)
        for value in ('totalTokens', 'token', 'turn ', '上下文上限', '服务档位', '原生状态', '原生队列', self.target.session_id):
            self.assertNotIn(value, text)
        self.assertLess(len(text), 420)
        html = self.rendered(text)
        self.assertIn('<strong>54%</strong>', html)
        self.assertIn('<p>会话：空闲</p>', html)
        self.assertEqual(text.count('查询时间'), 1)

    async def test_busy_queue_and_unknown_never_look_idle_or_empty(self):
        self.native.inspect.return_value = {'status': {'type': 'active'}}
        self.queue.list.return_value = [{}, {}]
        self.assertIn('会话：忙碌 · 等待 2 项任务', await self.execute('/codex status'))
        self.native.inspect.return_value = {'status': {}}
        text = await self.execute('/codex status')
        self.assertIn('会话：暂时无法确认', text)
        self.assertNotIn('会话：空闲', text)

    async def test_model_catalog_has_separate_literal_names_and_no_duplicate_display(self):
        self.models *= 0
        self.models.extend({'model': f'auto/model_{i}', 'displayName': 'DUPLICATE DISPLAY',
            'supportedReasoningEfforts': [{'reasoningEffort': 'high'}], 'defaultReasoningEffort': 'high'} for i in range(8))
        text = await self.execute('/model list'); html = self.rendered(text)
        for i in range(8):
            self.assertIn(f'<p><strong>auto/model_{i}</strong></p>', html)
        self.assertNotIn('DUPLICATE DISPLAY', html)
        self.assertEqual(html.count('思考等级：high（默认：high）</p>'), 8)
        self.assertIn('/model set', html)

    async def test_catalog_unknown_labels_cannot_inject_markdown_or_html(self):
        self.models[0]['supportedReasoningEfforts'] = [{'reasoningEffort': '**fake**<img>'}]
        self.models[0]['defaultReasoningEffort'] = '**fake**<img>'
        html = self.rendered(await self.execute('/model list'))
        self.assertNotIn('<strong>fake</strong>', html)
        self.assertNotIn('<img>', html)
        self.assertIn('**fake**&lt;img&gt;', html)

    async def test_empty_catalog_is_explicit(self):
        self.models.clear()
        self.assertIn('当前运行时未提供可选模型', await self.execute('/model list'))

    def test_both_quota_windows_keep_reset_times_and_unmapped_scope(self):
        text='\n\n'.join(rate_limit_lines({'rateLimits': {'primary': {
            'usedPercent': 100, 'windowDurationMins': 300, 'resetsAt': 0}}}))
        self.assertIn('剩余 **0%**',text)
        self.assertIn('1970-01-01 08:00',text)
        self.assertIn('非本会话专属',text)
        self.assertIn('未标注模型时不作推断',text)

    def test_compact_target_and_actionable_id_do_not_change_identifier(self):
        self.assertNotIn(self.target.session_id, target_description(self.target))
        task='t-'+ 'a'*32
        self.assertIn(task,self.rendered('任务：'+inline_literal(task)))
        self.assertEqual(task_state('waiting_interaction'),'等待答复')
        self.assertEqual(task_state('unknown'),'结果待核对')
        self.assertEqual(task_state('future-state'),'future-state')

    def test_target_label_omits_identical_project_directory_name_only(self):
        same=Target(self.target.session_id,'phone-a',Path('/fixture/phone-a'))
        text=target_description(same)
        self.assertEqual(text.count('phone-a'),1)
        self.assertIn(same.session_id[-8:],text)
        distinct=target_description(self.target)
        self.assertIn('fixture',distinct)
        self.assertIn('phone-a',distinct)
        case=Target(self.target.session_id,'Phone-A',Path('/fixture/phone-a'))
        self.assertIn('Phone-A',target_description(case))
        self.assertIn('phone-a',target_description(case))
