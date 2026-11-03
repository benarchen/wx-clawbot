"""Structured async questions are supplements, never approval or pause primitives."""

import asyncio
import json
import re
import time
import uuid
from dataclasses import asdict

from .agents.rpc import RpcError
from .async_state import digest
from .commands import CommandError
from .controller import target_record
from .output import render_in_worker, render_segments


def questions_from(item):
    questions = item.get('questions')
    if (item.get('type') != 'agentMessage' or item.get('delivery') != 'async'
            or not isinstance(item.get('id'), str) or not 0 < len(item['id']) <= 256
            or not isinstance(questions, list) or not 1 <= len(questions) <= 20):
        raise ValueError('A complete structured async question required')
    result = []
    for index, question in enumerate(questions, 1):
        if not isinstance(question, dict) or not isinstance(question.get('title'), str) or not question['title'].strip():
            raise ValueError('A nonempty question title required')
        options = question.get('options')
        if options is not None and (not isinstance(options, list) or not 1 <= len(options) <= 100
                or any(not isinstance(s, str) or not s.strip() for s in options) or len(set(options)) != len(options)):
            raise ValueError('Distinct nonempty string options required')
        result.append({'id': f'q{index}', 'title': question['title'], 'options': options})
    if len(json.dumps(result, ensure_ascii=False).encode()) > 1024 * 1024:
        raise ValueError('Question record exceeds its bound')
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate answer key')
        result[key] = value
    return result


def answer_text(row, text):
    if not isinstance(text, str) or not text.strip() or len(text) > 32000:
        raise ValueError('A bounded nonempty answer required')
    questions = row['questions']
    if text.lstrip().startswith('{'):
        values = json.loads(text, object_pairs_hook=_unique_object)
    elif len(questions) == 1:
        values = {questions[0]['id']: text}
    else:
        raise ValueError('All question keys required')
    if (not isinstance(values, dict) or set(values) != {q['id'] for q in questions}
            or any(not isinstance(v, str) or not v.strip() or len(v) > 4000 for v in values.values())):
        raise ValueError('Exact question keys and bounded answers required')
    # This is user input to the original turn, not a forged tool result.
    result = ('针对本轮异步问题的本人补充答复；不授予新的执行或审批权限。\n'
              f"请求：{row['public_id']}\n原问题：{row['item_id']}\n"
              f"问题摘要：{row['question_sha256']}\n"
              + json.dumps(values, ensure_ascii=False, separators=(',', ':')))
    if len(result) > 32000:
        raise ValueError('Combined native answer exceeds its bound')
    return result


def binding_record(session):
    # Includes terminal/PID/start/TTY, runtime and native session identity.
    return json.loads(json.dumps(asdict(session.binding), default=str, sort_keys=True))


class AsyncQuestions:
    def __init__(self, engine, *, clock=time.monotonic):
        self.engine, self.state, self.clock = engine, engine.state, clock
        self.deadlines = {}

    async def register(self, thread_id, turn_id, item):
        engine = self.engine
        task_id = engine.turn_tasks.get((thread_id, turn_id))
        task = await self.state.tasks(task_id=task_id) if task_id else await self.state.tasks(native_turn=(thread_id, turn_id))
        observer = engine.observed(thread_id)
        if (task is None or task['state'] in {'completed','failed','interrupted','cancelled'}
                or task['target'].get('source') == 'external' and observer is None):
            return
        from .execution import restore_target
        target = restore_target(task['target'])
        session = engine.controller.subscriptions.event_session(target, thread_id)
        key = digest(json.dumps([thread_id, turn_id, item.get('id')], ensure_ascii=False))
        try:
            if getattr(engine.native, 'server_version', None) != '0.166.0':
                raise ValueError('Async question protocol is not verified on this version')
            if len(json.dumps(item, ensure_ascii=False).encode()) > 1024 * 1024:
                raise ValueError('Async event exceeds the safe record budget')
            if not isinstance(turn_id, str) or not 0 < len(turn_id) <= 256:
                raise ValueError('Exact turn identity required')
            questions = questions_from(item)
            source = json.dumps(session.binding.runtime_identity)
            public_id = 'q-' + uuid.uuid5(uuid.NAMESPACE_URL,
                json.dumps([source, thread_id, turn_id, item['id']])).hex
            encoded = json.dumps(questions, ensure_ascii=False, separators=(',', ':'))
            record = {'public_id': public_id, 'source': source, 'thread_id': thread_id, 'turn_id': turn_id,
                'item_id': item['id'], 'questions': questions, 'question_sha256': digest(encoded),
                'target': {**target_record(session), 'binding': binding_record(session),
                           'native_generation': engine.controller.native_generation},
                'task_id': task['id'], 'generation': engine.generation, 'expires_at': time.time() + 600}
            lines = [f'异步补充问题：{target.project_alias}｜{public_id}',
                '任务可能继续运行；本地答复入口 600 秒有效。电脑与微信可能同时被接受，内容不构成审批授权。']
            literal_lines = []
            for question in questions:
                literal_lines.append(question['id'] + '：' + question['title'])
                literal_lines.extend('选项：' + s for s in question['options'] or [])
            literal = '\n'.join(literal_lines)
            fence = '`' * max(3, max((len(s) + 1 for s in re.findall(r'`+', literal)), default=0))
            lines.append(fence + 'text\n' + literal + '\n' + fence)
            lines.append(f'/answer {public_id} <单题文本，或完整多题 JSON 对象>')
            prompt = '\n\n'.join(lines)
            if len(prompt) > 7000 or len(json.dumps(record, ensure_ascii=False).encode()) > 1024 * 1024:
                raise ValueError('Complete prompt exceeds the safe display budget')
            chunks = await render_in_worker(prompt, renderer=render_segments, slots=self.state.render_slots)
            _, created = await self.state.async_register(record, chunks)
            if created:
                self.deadlines[public_id] = self.clock() + 600
        except ValueError:
            await self.state.queue_reply('async-unsupported-' + key,
                '本次结构化异步问题无法完整处理或已达容量上限，请在原终端处理；没有发送自动答复。', priority=0)

    async def expire(self):
        for row in await self.state.async_rows(active=True):
            if row['state'] == 'pending' and (time.time() >= row['expires_at']
                    or self.clock() >= self.deadlines.get(row['public_id'], float('-inf'))):
                await self.state.async_close(public_id=row['public_id'], reason='local_expiry')
        active = {r['public_id'] for r in await self.state.async_rows(active=True)}
        self.deadlines = {k: v for k, v in self.deadlines.items() if k in active}

    async def answer(self, public_id, text):
        engine = self.engine
        rows = await self.state.async_rows(public_id=public_id)
        if len(rows) != 1:
            raise CommandError('异步问题不存在；没有提交答案。')
        row = rows[0]
        if (row['state'] != 'pending' or row['closed_at'] is not None or row['generation'] != engine.generation
                or time.time() >= row['expires_at'] or self.clock() >= self.deadlines.get(public_id, float('-inf'))):
            raise CommandError('异步问题已失效或已有提交意图；不会重试或另开任务。')
        try:
            text = answer_text(row, text)
        except (ValueError, TypeError) as exc:
            raise CommandError('单题请提供非空文本；多题须为全部 q 题键到答案文本的 JSON 对象，每题最多 4000 字符。') from exc
        from .execution import restore_target
        target = restore_target(row['target'])
        try:
            generation = engine.generation
            host = engine.verified_host()
            if not engine.controller.native_ready:
                raise ValueError('Native connection unavailable')
            if (engine.controller.engine is not engine
                    or engine.controller.native_generation != row['target']['native_generation']):
                raise ValueError('Native controller generation changed')
            session = await engine.catalog.require(target)
            if (session.binding.thread_id != row['thread_id'] or binding_record(session) != row['target']['binding']
                    or json.dumps(session.binding.runtime_identity) != row['source']):
                raise ValueError('Frozen async endpoint changed')
            turn = await engine.read_turn(row['thread_id'], row['turn_id'])
            if turn.get('status') != 'inProgress':
                raise ValueError('Original turn ended')
            for user in (i for i in turn['items'] if i.get('type') == 'userMessage'):
                await self.state.async_user(row['thread_id'], row['turn_id'], user)
            engine.verified_host(host)
            if generation != engine.generation or not engine.controller.native_ready:
                raise ValueError('Native generation changed')
            if self.clock() >= self.deadlines.get(public_id, float('-inf')):
                raise ValueError('Local answer window ended')
            intent = await self.state.async_intent(public_id, generation, row['revision'], text)
        except asyncio.CancelledError:
            # The serialized intent writer may commit after its waiter cancels.
            # A queued follow-up sees that outcome; never reopen an accepted intent.
            await asyncio.shield(self.state.async_result(public_id, 'unknown'))
            raise
        except (ValueError, ConnectionError, TimeoutError, RpcError) as exc:
            await self.state.async_close(public_id=public_id, reason='preflight_failed', pending_only=True)
            raise CommandError('原问题／会话／连接或有效期已改变，答案未提交；请在原终端核对。') from exc
        # Once the intent commits, cancellation or uncertain transport must never reopen it.
        try:
            engine.verified_host(host)
            if (not engine.controller.native_ready or engine.controller.engine is not engine
                    or engine.controller.native_generation != row['target']['native_generation']):
                raise ValueError('Native generation changed after intent commit')
            reply = await engine.native.rpc.request('turn/steer', {'threadId': row['thread_id'],
                'expectedTurnId': row['turn_id'], 'clientUserMessageId': intent['answer_client'],
                'input': [{'type': 'text', 'text': intent['answer_text']}]})
            if not isinstance(reply, dict) or reply.get('turnId') != row['turn_id']:
                raise ValueError('Native reply did not prove the original turn')
        except RpcError:
            result = await self.state.async_result(public_id, 'refused')
        except BaseException as exc:
            await asyncio.shield(self.state.async_result(public_id, 'unknown'))
            if isinstance(exc, asyncio.CancelledError):
                raise
            return f'异步答复接收结果未知：{public_id}；不会自动重发，请在原终端核对。'
        else:
            result = await self.state.async_result(public_id, 'accepted')
        labels = {'accepted': '原生已接受补充，尚未证明模型采用', 'observed': '原轮次已出现准确补充输入，尚未证明模型采用',
            'refused': '原生已拒绝，未重试', 'conflict': '观察到跨端输入冲突，请在原终端核对',
            'unknown': '接收结果未知，不会重试'}
        return f"异步答复：{public_id}；{labels.get(result['state'], '入口已关闭，请在原终端核对')}。"

    async def status(self, task_id=None):
        rows = await self.state.async_rows(task_id=task_id) if task_id else await self.state.async_rows(active=True)
        if not rows:
            return ''
        pending = sum(r['state'] == 'pending' and r['closed_at'] is None for r in rows)
        lines = [f'异步待答：{pending} 条；任务可能继续运行。']
        for row in rows[:20]:
            remaining = max(0, min(600, int(row['expires_at'] - time.time())))
            lines.append(f"{row['public_id']}：{row['state']}；本地剩余 {remaining} 秒；{row['reason']}。")
            if task_id:
                lines.extend(q['id'] + '：' + q['title'][:100] for q in row['questions'])
        return '\n'.join(lines)
