"""Exact-thread queries and explicit controls with durable non-replay intents."""

import asyncio
from collections import OrderedDict
from pathlib import Path
import json
import hashlib
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .agents.rpc import RpcError
from .commands import CommandError, MODEL_ID
from .output import RESULT_LIMIT, inline_literal as literal, bold_literal, markdown_literal, target_description
from .admission import repository_key
from .channels.http import ChannelError
from .control_journal import ControlJournal


VERSIONS = frozenset({'0.167.0', '0.169.0'})
RACE_NOTICE = '桌面并发操作仍可能影响排队任务。'


def beijing_time(stamp=None):
    return datetime.fromtimestamp(time.time() if stamp is None else stamp, ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')


def reasoning_label(value):
    label = {'minimal': '最少', 'low': '低', 'medium': '中', 'high': '高',
             'xhigh': '更高', 'max': '最高', 'ultra': '极高'}.get(value)
    return label + '（' + value + '）' if label else literal(value)


def identifier(value, *, limit=256):
    return isinstance(value, str) and 0 < len(value) <= limit and bool(value.strip()) and all(c.isprintable() for c in value)


def rate_limit_lines(value):
    """Account quota is separate from thread tokens; never infer model routing."""
    if (not isinstance(value,dict) or len(json.dumps(value,allow_nan=False).encode())>65536
            or not isinstance(value.get('rateLimits'),dict)):
        raise ValueError('Invalid account quota snapshot')
    buckets=value.get('rateLimitsByLimitId')
    if buckets is None:
        buckets={'原生默认桶':value['rateLimits']}
    if not isinstance(buckets,dict) or len(buckets)>16:
        raise ValueError('Invalid account quota buckets')
    lines=['**账号额度**']
    for bucket,row in buckets.items():
        if not identifier(bucket,limit=128) or not isinstance(row,dict):
            raise ValueError('Invalid account quota bucket')
        name=row.get('limitName') or bucket
        model=row.get('normalModelSlug')
        if not identifier(name) or model is not None and not identifier(model):
            raise ValueError('Invalid account quota label')
        lines.append('额度来源：'+literal(name)+((' · 模型：'+literal(model)) if model else ''))
        windows=0
        for key,label in (('primary','主窗口'),('secondary','次窗口')):
            window=row.get(key)
            if window is None:continue
            if not isinstance(window,dict) or type(window.get('usedPercent')) is not int or not 0<=window['usedPercent']<=100:
                raise ValueError('Invalid account quota percentage')
            duration=window.get('windowDurationMins');reset=window.get('resetsAt')
            if duration is not None and (type(duration) is not int or not 0<duration<2**31):
                raise ValueError('Invalid account quota duration')
            if reset is not None and (type(reset) is not int or not 0<=reset<=253402300799):
                raise ValueError('Invalid account quota reset time')
            if duration is None:period=label+'（时长未提供）'
            elif duration%10080==0:period=str(duration//10080)+' 周'
            elif duration%1440==0:period=str(duration//1440)+' 天'
            elif duration%60==0:period=str(duration//60)+' 小时'
            else:period=str(duration)+' 分钟'
            when=beijing_time(reset) if reset is not None else '未提供'
            lines.append(period+'：剩余 **'+str(100-window['usedPercent'])+'%** · 重置 '+when)
            windows+=1
        if not windows:lines.append('额度窗口：原生未提供。')
    if not buckets:lines.append('额度桶：原生未提供。')
    lines.append('账号共享额度，非本会话专属；未标注模型时不作推断。')
    return lines


async def account_quota(native):
    generation=native.runtime_identity
    try:
        if native.server_version not in VERSIONS or generation is None:
            return ['账号额度：当前原生版本或连接未核验。']
        value=await native.rpc.request('account/rateLimits/read',{'excludeResetCreditDetails':True},timeout=5)
        if native.runtime_identity!=generation:
            raise CommandError('原生连接已变化，账号额度未确认。')
        return rate_limit_lines(value)
    except CommandError:
        raise
    except (ValueError,OSError,RpcError,TypeError,OverflowError,TimeoutError) as exc:
        return ['账号额度：暂时无法查询，请稍后重试。']


async def model_catalog(native, *, provider=None):
    if getattr(native, 'server_version', None) not in VERSIONS:
        raise CommandError('当前原生版本尚未核验模型目录能力。')
    models, cursors, size, cursor = {}, set(), 0, None
    generation = native.runtime_identity
    if generation is None:
        raise CommandError('原生连接不可用，未查询模型目录。')
    async with asyncio.timeout(25):
        for _ in range(10):
            params = {'limit': 100, 'includeHidden': False}
            if native.server_version == '0.169.0' and provider is not None:
                if not identifier(provider):
                    raise CommandError('原生模型 provider 无效，未查询目录。')
                params['modelProvider'] = provider
            if cursor is not None:
                params['cursor'] = cursor
            page = await native.rpc.request('model/list', params)
            rows = page.get('data') if isinstance(page, dict) else None
            if not isinstance(rows, list) or len(rows) > 100:
                raise CommandError('原生模型目录形态无效。')
            size += len(json.dumps(page, ensure_ascii=False, allow_nan=False).encode())
            if size > 2 * 1024 * 1024:
                raise CommandError('原生模型目录超过字节上限，未返回不完整清单。')
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get('model'), str) or not MODEL_ID.fullmatch(row['model']):
                    raise CommandError('原生模型标识无效。')
                name = row['model']
                if name in models or len(models) >= 1000:
                    raise CommandError('原生模型重复或超过上限。')
                efforts = row.get('supportedReasoningEfforts', [])
                if not isinstance(efforts, list) or len(efforts) > 32 or any(
                        not isinstance(v, dict) or not identifier(v.get('reasoningEffort'), limit=32) for v in efforts):
                    raise CommandError('原生推理选项无效。')
                default_effort = row.get('defaultReasoningEffort')
                if 'defaultReasoningEffort' in row and not identifier(default_effort,limit=32):
                    raise CommandError('原生模型默认推理强度无效。')
                tiers = row.get('serviceTiers')
                if tiers is not None and (not isinstance(tiers, list) or len(tiers) > 32 or any(
                        not isinstance(v, dict) or not identifier(v.get('id'), limit=128)
                        or not identifier(v.get('name'), limit=128) for v in tiers)
                        or len({v['id'] for v in tiers}) != len(tiers)):
                    raise CommandError('原生服务档位无效。')
                default = row.get('defaultServiceTier')
                if default is not None and not identifier(default, limit=128):
                    raise CommandError('原生默认档位无效。')
                display = row.get('displayName', name)
                if not identifier(display):
                    raise CommandError('原生模型名称无效。')
                models[name] = {'model': name, 'display': display, 'efforts': [v['reasoningEffort'] for v in efforts],
                                'default_effort':default_effort,
                                'tiers': tiers, 'default': default,
                                'default_provided': 'defaultServiceTier' in row}
            cursor = page.get('nextCursor')
            if native.runtime_identity != generation:
                raise CommandError('原生连接已变化，模型目录未确认。')
            if cursor is None:
                return models
            if not identifier(cursor, limit=4096) or cursor in cursors:
                raise CommandError('原生模型分页游标无效。')
            cursors.add(cursor)
    raise CommandError('原生模型目录超过分页上限，未返回不完整清单。')


def fast_state(settings, model):
    if model is None or model['tiers'] is None:
        return '无法确认（目录未提供档位信息）'
    choices = [v for v in model['tiers'] if v['name'].casefold() == 'fast']
    if not choices:
        return '不支持'
    if len(choices) != 1 or 'serviceTier' not in settings:
        return '无法确认（当前档位缺失或目录歧义）'
    tier = settings['serviceTier']
    if tier is None:
        if not model['default_provided']:
            return '无法确认（默认档位未提供）'
        tier = model['default']
    if tier == choices[0]['id']:
        return '已开启'
    # 0.167.0 owned probe confirms explicit standard tier and null normalization.
    if tier == 'default':
        return '未开启'
    if tier is None:
        return '未开启'
    return '无法确认（当前为其他档位）'


class NativeControls:
    def __init__(self, engine):
        self.engine = engine
        self.usage, self.turns = OrderedDict(), OrderedDict()
        self.settings_windows = {}
        self.confirm_seconds = 5

    def journal(self):
        return ControlJournal(self.engine.state.path.parent / 'native-controls')

    @staticmethod
    def is_write(command):
        return command.name == 'model' and command.argument == 'set' or command.name == 'fast' and command.argument in {'on','off'}

    def event(self, method, params):
        if not isinstance(params, dict):
            return
        thread, turn = params.get('threadId'), params.get('turnId')
        window = self.settings_windows.get(thread) if isinstance(thread, str) else None
        if window is not None and method in {'thread/settings/updated', 'turn/started'}:
            try:
                self.engine.verified_native(window['generation'])
            except CommandError:
                window['conflict'] = True
            if method == 'turn/started':
                window['conflict'] = True
            else:
                value = params.get('threadSettings')
                if not isinstance(value, dict) or value.get('cwd') != str(window['cwd']):
                    window['conflict'] = True
                else:
                    sample = {'model':value.get('model'), 'modelProvider':value.get('modelProvider'),
                              'reasoningEffort':value.get('effort'), 'serviceTier':value.get('serviceTier')}
                    if (any(k not in value for k in ('model','modelProvider','effort','serviceTier'))
                            or sample != window['expected'] or len(window['events']) >= 8):
                        window['conflict'] = True
                    else:
                        window['events'].append(sample)
            window['ready'].set()
            if method == 'thread/settings/updated':
                return
        if method == 'turn/started':
            turn = params.get('turn', {}).get('id') if isinstance(params.get('turn'), dict) else None
        if not identifier(thread) or not identifier(turn):
            return
        if method == 'turn/started':
            self.turns[thread] = turn
            self.turns.move_to_end(thread)
            while len(self.turns) > 256:
                old, _ = self.turns.popitem(last=False)
                self.usage.pop(old, None)
            return
        if method != 'thread/tokenUsage/updated' or self.turns.get(thread, turn) != turn:
            return
        value = params.get('tokenUsage')
        if not isinstance(value, dict):
            return
        cleaned = {}
        for scope in ('last', 'total'):
            row = value.get(scope)
            fields = ('inputTokens', 'outputTokens', 'totalTokens', 'cachedInputTokens', 'reasoningOutputTokens')
            if not isinstance(row, dict) or any(type(row.get(k)) is not int or not 0 <= row[k] < 2**63 for k in fields):
                return
            cleaned[scope] = {k: row[k] for k in fields}
        window = value.get('modelContextWindow')
        if window is not None and (type(window) is not int or not 0 < window < 2**63):
            return
        previous = self.usage.get(thread)
        if previous and previous['turn'] == turn and previous['usage']['total']['totalTokens'] > cleaned['total']['totalTokens']:
            return
        self.turns[thread] = turn
        self.turns.move_to_end(thread)
        self.usage[thread] = {'turn': turn, 'usage': cleaned, 'window': window, 'at': time.time(),
                              'generation': self.engine.native.runtime_identity}
        self.usage.move_to_end(thread)
        while len(self.turns) > 256:
            old, _ = self.turns.popitem(last=False)
            self.usage.pop(old, None)
        while len(self.usage) > 256:
            self.usage.popitem(last=False)

    async def execute(self, command, target, revision, *, message_id=None):
        controller, native = self.engine.controller, self.engine.native
        expected = self.engine.verified_native()
        def validate():
            self.engine.verified_native(expected)
            if controller.retired or controller.routes.revision != revision or controller.selection_pending:
                raise CommandError('输入目标已变化，本条原生命令未执行；请核对选择后重试。')
            if target is not None and controller.routes.target != target:
                raise CommandError('输入目标已变化，本条原生命令未执行。')
        try:
            validate()
            if self.is_write(command):
                return await self.write(command, target, validate, message_id, expected)
            async with asyncio.timeout(25):
                if command.name == 'model' and command.argument == 'list':
                    models = await model_catalog(native)
                    validate()
                    lines = ['**可用模型 · ' + str(len(models)) + ' 个**']
                    for item in models.values():
                        lines.append(bold_literal(item['model']))
                        options = ' / '.join(item['efforts']) or '未提供'
                        default = item['default_effort'] or '未提供'
                        lines.append('思考等级：'+markdown_literal(options)+'（默认：'+markdown_literal(default)+'）')
                    if not models:
                        lines.append('当前运行时未提供可选模型。')
                    lines.append('使用：`/model set <模型名称> [推理强度]`')
                    lines.append('省略等级时使用该模型默认值；目录可见不等于账号一定可调用。')
                    text = '\n\n'.join(lines)
                    if len(text) > RESULT_LIMIT:
                        raise CommandError('模型目录展示超过回执上限，未返回不完整清单。')
                    return text
                if target is None:
                    raise CommandError('请先用 /sessions 和 /focus 选择输入目标。')
                session = await controller.catalog.require(target)
                controller.subscriptions.event_session(target, session.binding.thread_id)
                if 'route' not in controller.subscriptions.roles.get(target.session_id, set()):
                    raise CommandError('原输入订阅尚未核验，请重新选择会话。')
                settings = await native.read_settings(session.binding.thread_id, target.cwd)
                for key in ('model', 'modelProvider', 'reasoningEffort', 'serviceTier'):
                    if key in settings and settings[key] is not None and not identifier(settings[key]):
                        raise CommandError('原生设置值无效，未使用旧缓存替代。')
                heading = {'model': '当前模型', 'fast': '快速模式', 'codex': 'Codex 状态'}[command.name]
                header = '**'+heading+'**'
                def field(key):
                    if key not in settings or key == 'model' and settings[key] is None:
                        return '原生未提供'
                    return literal(settings[key]) if settings[key] is not None else '原生默认（未覆盖）'
                effort = settings.get('reasoningEffort')
                effort_text = reasoning_label(effort) if effort is not None else field('reasoningEffort')
                lines = [header, target_description(target), '模型：' + field('model'), '思考等级：' + effort_text]
                if command.name != 'model':
                    models = await model_catalog(native, provider=settings.get('modelProvider'))
                    lines += ['Fast：' + fast_state(settings, models.get(settings.get('model')))]
                if command.name == 'codex':
                    metadata = await native.inspect(session.binding.thread_id)
                    queue = await self.engine.queue(session.binding.thread_id, target.cwd).list()
                    state = metadata.get('status', {}).get('type')
                    state_text = {'idle': '空闲', 'active': '忙碌', 'systemError': '异常',
                                  'notLoaded': '未加载'}.get(state, '暂时无法确认')
                    lines += ['会话：' + state_text + (f' · 等待 {len(queue)} 项任务' if queue else '')]
                    lines += await account_quota(native)
                await controller.catalog.require(target)
                validate()
                lines.append('查询时间：'+beijing_time()+'（北京时间）')
                if command.name == 'model':
                    lines.append('思考等级越高，通常思考更充分、等待更久；可用等级见 `/model list`。')
                return '\n\n'.join(lines)
        except (CommandError, asyncio.CancelledError):
            raise
        except (ValueError, OSError, RpcError, KeyError, TypeError, TimeoutError) as exc:
            raise CommandError('原生查询未确认（' + type(exc).__name__ + '）；未修改设置或重放，请核对原生状态。') from None

    async def idle(self, target, session, *, reservations=True):
        """Bridge-owned gate is held by caller; native clients remain autonomous."""
        engine, controller = self.engine, self.engine.controller
        if reservations and any(t.project_alias == target.project_alias or t.session_id == target.session_id
                                for t in controller.task_reservations.values()):
            raise CommandError('已有接收中的任务，未修改设置；请等待任务结束。')
        thread_id = session.binding.thread_id
        if not (await engine.state.admission_budget())['allowed']:
            raise CommandError('待核对回执已达容量上限，未修改设置。')
        metadata = await engine.native.inspect(thread_id)
        if metadata.get('status', {}).get('type') != 'idle' or metadata.get('canAcceptDirectInput') is not True:
            raise CommandError('原生会话忙碌或不可输入，未修改设置。')
        if await engine.queue(thread_id, target.cwd).list():
            raise CommandError('原生队列尚有任务，未修改设置。')
        project = controller.routes.projects[target.project_alias]
        key = await repository_key(target.cwd, project.root)
        async def related(record):
            if record.get('project_alias') == target.project_alias or record.get('thread_id') == thread_id:
                return True
            if record.get('repository'):
                return record['repository'] == key
            other = controller.routes.projects.get(record.get('project_alias'))
            return await repository_key(Path(record['cwd']), other.root if other else None) == key
        if reservations:
            for pending in tuple(controller.task_reservations.values()):
                if await related({'project_alias':pending.project_alias,'cwd':str(pending.cwd)}):
                    raise CommandError('同仓库已有接收中的任务，未修改设置。')
        for task in await engine.state.tasks(active_only=True):
            if await related(task['target']):
                raise CommandError('同项目或仓库仍有任务／占用，未修改设置。')
        for item in await engine.state.interaction_rows(active_only=True):
            if item['state'] not in {'resolved','stale'} and await related(item['target']):
                raise CommandError('仍有待处理交互，未修改设置。')
        for item in await engine.state.async_rows(active=True):
            if await related(item['target']):
                raise CommandError('仍有待处理追问，未修改设置。')
        for other in tuple(engine.catalog.sessions.values()):
            if other.target == target:
                continue
            record = {'project_alias':other.target.project_alias,'cwd':str(other.target.cwd)}
            if await related(record):
                status = (await engine.native.inspect(other.binding.thread_id)).get('status',{}).get('type')
                if status not in {'idle','notLoaded'}:
                    raise CommandError('同项目或仓库的其他会话忙碌，未修改设置。')

    @staticmethod
    def setting(command, before, models):
        fields=('model','modelProvider','reasoningEffort','serviceTier')
        if (not isinstance(before,dict) or any(k not in before for k in fields)
                or any(not identifier(before[k]) for k in ('model','modelProvider'))
                or any(before[k] is not None and not identifier(before[k]) for k in ('reasoningEffort','serviceTier'))):
            raise CommandError('当前设置或模型目录缺失，未修改设置。')
        current = models.get(before['model'])
        if current is None or any(k not in before for k in ('model','modelProvider','reasoningEffort','serviceTier')):
            raise CommandError('当前设置或模型目录缺失，未修改设置。')
        if command.name == 'model':
            candidate = models.get(command.text)
            if candidate is None:
                raise CommandError('模型名称不在当前目录，请用 /model list 核对。')
            effort = command.reasoning if command.reasoning is not None else candidate['default_effort']
            if effort is None:
                raise CommandError('模型目录未提供默认推理强度，请显式指定。')
            if effort not in candidate['efforts']:
                raise CommandError('所选模型不支持该推理强度，未修改设置。')
            if (before['serviceTier'] not in {None,'default'} and before['serviceTier'] not in {
                        t['id'] for t in candidate['tiers'] or []}):
                raise CommandError('新模型不能保持当前档位，未修改任何字段。')
            return {'model':command.text,'effort':effort}, {'model':command.text,'reasoningEffort':effort}
        fast = [v['id'] for v in current['tiers'] or [] if v['name'].casefold() == 'fast']
        if len(fast) != 1 or before['serviceTier'] not in {None,'default',*fast}:
            raise CommandError('Fast 不支持、信息缺失或当前为其他档位，未修改设置。')
        tier=fast[0] if command.argument == 'on' else 'default'
        return {'serviceTier':tier}, {'serviceTier':tier}

    async def write(self, command, target, validate, message_id, generation):
        native, engine = self.engine.native, self.engine
        journal, record, sent = None, None, False
        window = None
        try:
            if native.server_version not in VERSIONS or target is None:
                raise CommandError('当前版本或输入目标不支持设置修改。')
            ControlJournal.key(message_id)
            fingerprint = hashlib.sha256(json.dumps([command.name,command.argument,command.text,command.reasoning,
                target.session_id,target.project_alias,str(target.cwd)],ensure_ascii=False).encode()).hexdigest()
            journal = self.journal()
            old = journal.read(message_id)
            if old is not None:
                if old['fingerprint'] != fingerprint:
                    raise CommandError('同一消息已有不同设置记录，未重新执行。')
                return old.get('reply') or self.unknown(target)
            async with engine.admission_gate:
                async with asyncio.timeout(25):
                    validate()
                    await engine.catalog.discover()
                    session = await engine.catalog.require(target)
                    engine.controller.subscriptions.event_session(target, session.binding.thread_id)
                    if 'route' not in engine.controller.subscriptions.roles.get(target.session_id,set()):
                        raise CommandError('原输入订阅尚未核验，请重新选择会话。')
                    thread = session.binding.thread_id
                    before = await native.read_settings(thread,target.cwd)
                    models = await model_catalog(native, provider=before.get('modelProvider'))
                    updates,changes = self.setting(command,before,models)
                    await self.idle(target,session)
                    validate()
                    payload = {'fingerprint':fingerprint,'target':{'session_id':target.session_id,
                        'project_alias':target.project_alias,'cwd':str(target.cwd),'thread_id':thread,
                        'native_session_id':session.binding.native_session_id,'runtime':list(native.runtime_identity)},
                        'before':before,'setting':updates,
                        'reasoning_source':('model_default' if command.reasoning is None else 'explicit') if command.name=='model' else None}
                    record,created = journal.begin(message_id,payload)
                    if not created:
                        if record['fingerprint'] != fingerprint:raise CommandError('同一消息设置记录不匹配，未执行。')
                        return record.get('reply') or self.unknown(target)
                    header = target_description(target)+'\n\n'
                    detail = ('Fast：'+('已开启' if command.argument=='on' else '未开启')+
                              '\n\n仅确认设置，不代表实际提速或计费。' if command.name=='fast' else
                              '模型：'+literal(changes['model'])+'\n\n思考等级：'+reasoning_label(changes['reasoningEffort'])+
                              (' · 模型默认' if command.reasoning is None else ''))
                    if all(before[k]==v for k,v in changes.items()):
                        return journal.finish(message_id,'unchanged','**当前已是该设置，无变更**\n\n'+header+detail)
                    # Repeat all externally observable checks immediately before the send.
                    await self.idle(target,session)
                    if await native.read_settings(thread,target.cwd) != before:
                        raise CommandError('写入前设置已变化，本条未发送设置请求。')
                    await engine.catalog.require(target);validate()
                    expected = dict(before,**changes)
                    window = {'generation':generation,'cwd':target.cwd,'expected':expected,
                              'events':[],'conflict':False,'ready':asyncio.Event()}
                    self.settings_windows[thread] = window
                    engine.verified_native(generation)
                    sent = True
                    try:
                        ack = await native.rpc.request('thread/settings/update',{'threadId':thread,**updates})
                    except RpcError:
                        after = await native.read_settings(thread,target.cwd)
                        validate()
                        if after == before and not window['events'] and not window['conflict']:
                            return journal.finish(message_id,'rejected',header+'原生拒绝设置，回读原值未变；未重试。',after=after)
                        raise CommandError('拒绝后原生设置未能确认，保留待核对状态。') from None
                    if not isinstance(ack,dict):raise CommandError('原生写回执形态无效。')
                    await asyncio.wait_for(window['ready'].wait(),self.confirm_seconds)
                    after = await native.read_settings(thread,target.cwd)
                    await self.idle(target,session,reservations=False)
                    await engine.catalog.require(target);validate()
                    if window['conflict'] or not window['events'] or after != expected:
                        raise CommandError('设置事件／回读冲突，保留待核对状态。')
                    reply = '**设置已确认**\n\n'+header+detail+'\n\n'+RACE_NOTICE
                    return journal.finish(message_id,'confirmed',reply,after=after,settings_event=True)
        except asyncio.CancelledError:
            # Keep the durable intent. Cancellation cannot establish whether RPC ran.
            raise
        except (CommandError,ChannelError,ValueError,OSError,RpcError,KeyError,TypeError,TimeoutError) as exc:
            if record is not None:
                reply = self.unknown(target) if sent else '设置请求未发送，未修改设置；请核对后下达新命令。'
                try:
                    return journal.finish(message_id,'unknown' if sent else 'rejected',reply)
                except (ChannelError,ValueError,OSError):
                    raise CommandError(self.unknown(target)) from None
            if isinstance(exc,CommandError):raise
            raise CommandError('设置操作未发送（'+type(exc).__name__+'）；未重放，请核对状态。') from None
        finally:
            if window is not None:
                self.settings_windows.pop(record['target']['thread_id'],None)

    @staticmethod
    def unknown(target):
        return (f'设置结果待核对：{target.project_alias}｜{target.session_id}。\n'
                '原请求不会重放或回滚；请先查询 /model、/fast 或 /codex status，再明确下达新命令。')
