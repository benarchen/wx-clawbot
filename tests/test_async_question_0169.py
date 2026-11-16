"""Regression for async notices, final-result separation and 0.169.0 supplements."""

import unittest

import test_async_questions as fixtures
from wx_clawbot.output import native_output
from wx_clawbot.commands import CommandError


class AsyncQuestion0169Tests(fixtures.AsyncQuestionTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.agent.server_version = '0.169.0'

    async def check_closed_revision(self, mutation):
        row = await self.question()
        await self.emit({**self.item, 'id': 'unrelated'})
        await self.emit({**self.item, **mutation})
        saved = await self.row(row['public_id'])
        self.assertEqual((saved['state'], saved['reason']), ('stale', 'unsupported_question'))
        with self.assertRaises(CommandError):
            await self.answer(saved)
        other = [r for r in await self.state.async_rows(thread_turn=(self.thread, self.turn))
                 if r['item_id'] == 'unrelated'][0]
        self.assertEqual(other['state'], 'pending')
        self.agent.rpc.request.assert_not_awaited()

    async def test_invalid_revision_closes_only_exact_old_card(self):
        await self.check_closed_revision({'questions': []})

    async def test_moderated_revision_closes_only_exact_old_card(self):
        await self.check_closed_revision({'moderation': {'moderated': True}})

    async def test_oversized_revision_closes_only_exact_old_card(self):
        await self.check_closed_revision({'questions': [{'title': 'x' * 7000, 'options': None}]})

    async def test_changed_refusal_reason_preserves_frozen_notices_and_never_revives_old_card(self):
        row = await self.question()
        for mutation in ({'questions': []}, {'moderation': {'moderated': True}},
                         {'moderation': {'moderated': True}}):
            await self.emit({**self.item, **mutation})
        saved = await self.row(row['public_id'])
        self.assertEqual(saved['state'], 'stale')
        rows = await self.state._call(lambda: list(self.state.db.execute(
            "SELECT text FROM outbox WHERE id LIKE 'async-unsupported-%'")))
        self.assertEqual(len(rows), 2)
        self.assertTrue(any('结构' in row[0] for row in rows))
        self.assertTrue(any('展示／审核' in row[0] for row in rows))


class AsyncFailureNoticeTests(fixtures.AsyncFixture):
    async def notices(self):
        return await self.state._call(lambda: list(self.state.db.execute(
            "SELECT text,task_id FROM outbox WHERE id LIKE 'async-unsupported-%' ORDER BY rowid")))

    async def check_notice(self, cause):
        rows = await self.notices()
        self.assertEqual(len(rows), 1)
        text, task_id = rows[0]
        self.assertEqual(task_id, self.task['id'])
        for value in (self.task['id'], self.task['target']['project_alias'], cause,
                      '原任务可能继续执行', '没有发送自动答复'):
            self.assertIn(value, text)
        self.assertNotIn('/answer', text)
        self.assertEqual((await self.state.tasks(task_id=self.task['id']))['state'], 'running')
        self.agent.rpc.request.assert_not_awaited()

    async def test_version_refusal_is_specific_bound_deduplicated_and_task_still_completes(self):
        self.agent.server_version = '0.167.0'
        self.assertIsNone(await self.question())
        await self.emit(self.item)
        await self.check_notice('当前原生版本尚未开放微信异步答复')
        self.assertNotIn('容量', (await self.notices())[0][0])
        await self.engine.complete(self.thread, {**self.native_turn, 'status': 'completed',
            'items': self.native_turn['items'] + [self.item,
                {'type': 'agentMessage', 'phase': 'final_answer', 'text': 'FINAL_ONLY'}]})
        self.assertEqual((await self.state.tasks(task_id=self.task['id']))['state'], 'completed')
        rows = await self.state._call(lambda: list(self.state.db.execute(
            "SELECT text FROM outbox WHERE kind='final'")))
        self.assertEqual(len(rows), 1)
        self.assertIn('FINAL_ONLY', rows[0][0])
        self.assertNotIn(self.item['text'], rows[0][0])

    async def test_invalid_structure_is_not_reported_as_capacity(self):
        self.assertIsNone(await self.question(questions=[{'title': '', 'options': None}]))
        await self.check_notice('问题结构不完整或不受支持')
        self.assertNotIn('容量', (await self.notices())[0][0])

    async def test_content_limit_has_specific_reason(self):
        self.assertIsNone(await self.question(questions=[{'title': 'x' * 7000, 'options': None}]))
        await self.check_notice('问题内容超过完整展示或安全处理上限')

    async def test_shared_capacity_retains_existing_interactions_and_explains_reason(self):
        await self.state._call(lambda: self.state.db.executemany(
            """INSERT INTO interactions VALUES(?,?,'generation','thread','turn',
            'item/tool/requestUserInput','{}','{}',600,'pending',1,1)""",
            [(f'r-fixture-{i}', str(i)) for i in range(256)]))
        self.assertIsNone(await self.question())
        await self.check_notice('交互记录已达容量上限')
        self.assertEqual(await self.state.async_budget(), (256, 512))

    async def test_0169_presentation_directive_never_exposes_question_or_creates_answer(self):
        self.agent.server_version = '0.169.0'
        # Set up an active task without opening a first question.
        self.agent.server_version = '0.167.0'
        await self.question()
        self.agent.server_version = '0.169.0'
        for index, moderation in enumerate(({'moderated': True}, {'moderated': False,
                'display': {'action': 'unknown'}}, {}, True)):
            await self.emit({**self.item, 'id': f'moderated-{index}', 'text': 'PRIVATE_BODY',
                'questions': [{'title': 'PRIVATE_QUESTION', 'options': None}],
                'moderation': moderation})
        self.assertEqual(await self.state.async_rows(active=True), [])
        rows = await self.notices()
        self.assertEqual(len(rows), 5)
        for text, task_id in rows[1:]:
            self.assertIn('展示／审核指令', text)
            self.assertNotIn('PRIVATE', text)
            self.assertEqual(task_id, self.task['id'])


class AsyncFinalOutputTests(unittest.TestCase):
    def test_async_question_is_separate_from_final_and_legacy_answers(self):
        items = [{'type': 'agentMessage', 'delivery': 'async', 'phase': 'final_answer',
                  'questions': [{'title': 'PRIVATE_QUESTION'}], 'text': 'PRIVATE_QUESTION'},
                 {'type': 'agentMessage', 'phase': 'final_answer', 'text': 'FINAL'},
                 {'type': 'agentMessage', 'text': 'LEGACY'}]
        self.assertEqual(native_output({'status': 'completed', 'items': items}), 'FINAL\nLEGACY')

    def test_async_only_never_looks_like_a_final_answer_and_failed_error_survives(self):
        turn = {'status': 'completed', 'items': [
            {'type': 'agentMessage', 'delivery': 'async', 'text': 'QUESTION'}]}
        self.assertEqual(native_output(turn), '原生任务已结束，仅有异步补充问题，没有最终文本答案。')
        failed = native_output({**turn, 'status': 'failed', 'error': {'message': 'EXACT_ERROR'}})
        self.assertEqual(failed, '原生错误：EXACT_ERROR')

    def test_filtered_async_directive_still_blocks_complete_result(self):
        turn = {'items': [{'type': 'agentMessage', 'delivery': 'async', 'text': 'PRIVATE_QUESTION',
                          'moderation': {'moderated': True}},
                         {'type': 'agentMessage', 'text': 'PRIVATE_ANSWER'}]}
        self.assertNotIn('PRIVATE', native_output(turn))
        self.assertIn('原生客户端', native_output(turn))
