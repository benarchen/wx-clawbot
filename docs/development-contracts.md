# wx-clawbot 开发契约与接口验证方案

本文保存设计与验收要求；实际进度与验证状态以仓库 ROADMAP.md 为准。

需求权威见 [产品设计](product-design.md) ，选型依据见 [技术决策](technical-decisions.md) 。本文定义模块间行为与测试边界，不宣称示例接口已经存在于程序中。

## 1. 项目结构约定

```text
wx-clawbot/
  AGENTS.md
  README.md
  ROADMAP.md
  pyproject.toml
  requirements.lock
  .gitignore
  src/wx_clawbot/
    cli.py
    service.py
    commands.py
    projects.py
    sessions.py
    tasks.py
    interactions.py
    state.py
    delivery.py
    channels/wechat.py
    agents/base.py
    agents/codex.py
    hosts/iterm2.py
  tests/
    unit/
    contract/
    integration/
    fixtures/
  docs/
  config/
  .tmp/
```

先写 AGENTS.md，再创建实现目录；职责不足以独立成文件时允许暂时合并，不创建空壳。docs 保存正式设计和施工记录；config 只存无密钥模板；.tmp 不进入 Git。README 只写当前可用能力，未完成项放 ROADMAP。运行数据不在源码目录。

## 2. 模块边界

| 模块 | 输入与输出 | 禁止承担的职责 |
| --- | --- | --- |
| WechatChannel | 接收规范化消息；发送文本；报告账号与连接状态 | 不执行项目命令，不直接选择 thread |
| CommandRouter | 解析固定命令、绑定列表快照、冻结路由 | 不拼接 Shell，不让模型决定目标序号 |
| ProjectRegistry | 注册别名、realpath 边界、规则入口 | 不迁移项目，不把白名单当作操作系统沙箱 |
| SessionDirectory | 维护项目、iTerm 端点、原生 thread 的映射 | 不用窗口标题或目录猜唯一身份 |
| ItermHost | 发现、验证、创建可见终端 | 不根据屏幕文字宣布任务终态或审批完成 |
| CodexAdapter | 连接原生运行时、提交任务、观察、答复、取消 | 不更改用户全局配置，不另开 thread 冒充原会话 |
| TaskCoordinator | 持久化提交意图、原生队列映射、串行与恢复 | 不与原生队列重复调度同一任务 |
| InteractionCoordinator | 请求关联、答复校验、原生完成状态同步 | 不把桥接 SQLite 锁当作双端裁决的充分条件 |
| StateStore／Delivery | 事务、Outbox、分段、发送结果、脱敏日志 | 不因发送失败重新执行 Agent 任务 |

未来 Agent 的扩展点是 agents/base.py 中的小型能力接口；首版只实现 Codex。宿主扩展点只覆盖终端生命周期，不把一套协议强制包装成 ACP。

## 3. 规范化对象与接口

字段使用明确类型；内部时间采用 UTC 时间戳，用户展示为北京时间。native ID 保留原类型，不把整数 request ID 和字符串 request ID 混为一谈。

| 对象 | 最小字段 |
| --- | --- |
| IncomingMessage | account_id、sender_id、conversation_id、native_message_id、received_at、text、reply_context_ref |
| SessionRef | session_id、project_id、native_thread_id、runtime_id、runtime_generation、terminal_id、origin、capabilities |
| TaskRef | task_id、source_message_key、session_id、route_revision、client_submission_id、native_queue_id、turn_id、state |
| AgentEvent | event_kind、session_id、runtime_generation、native_event_ref、task_id 可空、payload |
| InteractionRef | public_request_id、native_request_id、session_id、turn_id、generation、kind、options、state、deadline |
| OutgoingMessage | delivery_id、task_id 可空、recipient、sequence、priority、text、reply_context_ref、state |

桌面主动发起的任务事件可以没有桥接 task_id；登记为 external 来源并保持可辨识，不伪造微信入站消息。订阅历史快照与实时进展分开，避免把历史最终结果当新任务结果重复推送。

建议内部方法：

```text
SessionHost.discover() -> TerminalEndpoint[]
SessionHost.validate(endpoint) -> EndpointStatus
SessionHost.open(launch_id) -> TerminalEndpoint
AgentAdapter.connect(runtime_ref) -> Capabilities
AgentAdapter.inspect(thread_ref) -> NativeSessionState
AgentAdapter.submit(task_ref, input) -> SubmissionReceipt
AgentAdapter.events() -> AsyncIterator[AgentEvent]
AgentAdapter.respond(interaction_ref, typed_answer) -> ResponseReceipt
AgentAdapter.cancel(task_ref) -> CancellationReceipt
```

Capabilities 至少区分 observe、submit、queue、interrupt、shared_interactions、open_visible_session。能力检查发生在接收任务前；未知字段可保留，不支持的请求类型明确提示，不自动同意。

外部 Codex 方法和参数从本机固定版本 schema 生成测试 fixture，内部对象不直接暴露整个 schema。升级 CLI 时先跑契约测试，再解除版本不匹配状态。

## 4. 会话身份与启动握手

已有会话映射需要形成 terminal_id、进程身份、runtime、thread_id 四者的证据链。窗口名、cwd、会话预览只能辅助展示。无法唯一确定时返回候选让用户选择，不能把选目录当成映射成功。

新会话启动先持久化 launch_id，再调用 iTerm2。启动命令只包含可信解释器、固定启动入口和随机 launch_id；目标目录及选项由私有启动登记读取。使用 exec 的 argv 传入 Codex 参数，用户文本不进入 Shell 命令。iTerm2 的字符串 command 如必需，逐参数进行 Shell 引用，路径中的空格、引号和替换符必须测试。

启动握手收到真实端点与 thread 后才标记 ready；只看到新 tab 不够。连接或启动超时保留 starting／unknown 供核对，不因重试创建第二个窗口。只回收本次创建且确认归属的失败资源，用户既有终端不被误关。

既有会话发现机制须在 V01 选出可验证方案；需要用户一次性绑定可以作为显式交互提出，但不能隐瞒自动发现不足。独立运行时无正式入口时记录具体阻塞，不自动迁移原会话。

## 5. 排队、任务与取消

唯一执行权威是原生运行时。原型先验证原生队列：提交时携带稳定 client_submission_id，保存返回的队列身份，并追踪到实际 turn。客户端关联 ID 是否有去重保证必须实测，不能默认成立。

桥接账本保存接收意图与状态，不重复执行原生已接收任务。仅当目标运行时无法提供满足 D04 的队列能力时，重新评估方案；不得一边依赖原生队列、一边在本地超时后重复派发。

```text
received -> submitting -> queued -> running -> completed / failed
running <-> waiting_interaction
queued -> cancelled
running / waiting_interaction -> cancelling -> interrupted
submitting / running / cancelling -> outcome_unknown
```

submitted 超时不表示未提交。恢复时先检查原生队列、turn 与任务关联；无法确认则保持 outcome_unknown，并阻止自动重放。任务失败和投递失败分别记录。

停止排队任务要求原生确认移除；停止运行任务要求实际中断事件。查询、停止与交互答复不进入普通任务队列。队列上限默认建议为每会话 10 条；桌面端追加消息也必须纳入原生状态观察。

跨会话项目互斥在提交原生队列之前取得许可；未取得许可的入站意图停留在 received，不宣称已进入原生队列。许可覆盖该项目本服务已提交且尚未结束的任务，排空后释放。它是准入控制，不是第二套执行队列。默认最多两个桥接活动项目；同仓库与 worktree 的互斥按架构约束执行。桌面直接发起的任务需要被观察并影响准入，但桥接器不能保证阻止外部客户端同时写文件；检测到冲突时暂停新增派发并明确提示。

## 6. 双端审批与追问

裁决点必须是两端共享的原生请求状态。服务记录 request ID、运行代次和连接归属，将明确的操作、选项及项目发送到微信。微信答复先验证身份、关联、有效期与答案类型，再通过持有该请求的正式协议连接回答。

电脑先回答：收到原生已处理状态后关闭微信待答入口。微信先回答：必须观察到电脑端原生等待状态解除。冲突同时到达：只允许原生接受一次有效决定；本地数据库只辅助去重，不能替代真实竞争验证。

任一答复结果不确定时不再次提交相反决定。断连后旧请求先标记 stale，核对原生是否仍等待；超时不能静默放行。需要拒绝或取消时使用正式支持的动作，并记录其确认结果。

“首次”指原生裁决点接受的首次有效答复，不按两台界面的本地时间猜先后。追问还须测试多选、自由文本、无效答案与用户取消；不同交互类型的通过结果分别记录。

## 7. 微信请求字段核对清单

以下是实现前逐字段核对入口，具体 payload 以冻结版本源码为准。参考：[API](https://raw.githubusercontent.com/Tencent/openclaw-weixin/main/src/api/api.ts) 、[登录](https://raw.githubusercontent.com/Tencent/openclaw-weixin/main/src/auth/login-qr.ts) 、[发送](https://raw.githubusercontent.com/Tencent/openclaw-weixin/main/src/messaging/send.ts) 。

当前公开源码中的客户端标识和版本生成方式是参考事实，不是我们可任意填写的保证。W04 必须核对独立客户端所需标识与适用条件，既不盲目伪造版本，也不声称官方授权；无法确认时记录为接入阻塞。

| 请求 | 必核对内容 |
| --- | --- |
| 公共 headers | Content-Type、AuthorizationType、Bearer token 的适用范围；X-WECHAT-UIN 的随机数编码；iLink-App-Id、版本编码、可选路由字段 |
| 登录 | get_bot_qrcode 的方法、bot_type、local_token_list；扫码状态、验证要求、确认后的账号与服务地址；不混用登录前后 headers |
| 接收 | getupdates 的 get_updates_buf、base_info、服务端轮询超时提示；消息类型、发送者、消息身份与 reply context |
| 发送 | sendmessage 中 msg 的收发方、client_id、type、state、文本 item、context_token，以及 base_info |
| 失败 | HTTP 错误与 ret／errcode 分开；失效账号停止任务入口；超时不等于失败且不能无限重试 |

不直接输出 headers、token、二维码密钥或完整响应到日志。reply context 按账号和会话保存，不能拿 A 的上下文给 B 发消息；缺少有效上下文时保留待发送状态并提示恢复方式，不声称成功。

接收游标与 inbox 消息在一个事务提交。去重键以实测稳定消息身份构成；缺少稳定 ID 时不得仅用正文哈希吞掉重复文本任务。client_id 的发送幂等能力不作先验保证，发送结果未知时标记 delivery_unknown。

## 8. 数据与错误处理

建议最小表：projects、sessions、routes、inbox、tasks、interactions、outbox、channel_state、launches。主键、唯一约束与外键服务于实际不变量，不先建通用工作流引擎。使用 schema_version 管理程序自有数据库，业务项目数据库不在范围内。

入站接收、去重和游标提交为一个事务；任务终态与最终 Outbox 写入为一个事务。外部 RPC 与 SQLite 不具备跨系统事务，因此必须保留 unknown 状态。DB 操作经单独的有界工作通道串行执行，连接不跨线程混用。

| 错误码 | 用户可理解的处理 |
| --- | --- |
| TARGET_REQUIRED／STALE_LIST | 选择目标或刷新列表，原路由不猜测变化 |
| SESSION_UNBOUND／UNSUPPORTED | 说明缺少哪项能力及可执行的下一步 |
| QUEUE_FULL | 拒绝新任务并显示队列，不丢旧任务 |
| INTERACTION_RESOLVED／STALE | 告知已处理或失效，不再次授权 |
| EXECUTION_UNKNOWN | 核对原生运行状态，不自动重跑 |
| DELIVERY_UNKNOWN／CHANNEL_EXPIRED | 保留执行结果，恢复通道后处理投递 |
| PROJECT_OUT_OF_SCOPE | 拒绝目录切换，保留当前选择 |

日志只保存关联 ID、错误类别、状态、耗时和必要脱敏摘要。正文保留期按设计默认值实现时须明示；清理只限程序自有账本，不碰 Codex 历史和业务项目。

## 9. 关键接口验证关卡

全部动态测试先在两个 fixture 项目进行；不得向用户正在使用的终端注入试验任务。测试专用 iTerm2 会话需先在终端正常启动，再模拟桥接服务接入，以覆盖“已有会话”。

| 编号 | 验证动作 | 通过证据与失败处理 |
| --- | --- | --- |
| V00 静态基线 | 版本、help、schema、公开源代码核对 | 本轮已完成该范围；不代表下面动态关卡通过 |
| V01 宿主与身份 | SDK 连接；发现正常／普通 Shell／已退出端点；同目录两个 Codex；核对 daemon 与 thread | 映射无歧义、旧端点不误投、独立运行时被识别；失败先补映射方案 |
| V02 原会话双端 | 桌面先发送标记，桥接发送第二条，桌面继续第三条；核对原生历史与结果事件 | 同一个 thread 和可见终端，三轮上下文连续；不能以恢复副本通过 |
| V03 双端交互 | 两端分别先答；同意与拒绝竞争；多选追问；断线、超时与迟到答复 | 每个原生请求仅一次有效结果，两端解除等待；不支持共享请求即停止宣称 D05 可用 |
| V04 原生队列 | Agent 忙时两端各追加任务；取消排队／运行任务；提交回执丢失后恢复 | 顺序可解释、控制操作可及时处理、无重复执行、每条输入可关联实际 turn |
| V05 可见启动 | 从项目选择请求创建新 tab；含空格路径、恶意替换符、重复请求、启动中断 | 无 Shell 注入；同一 launch_id 不重复启动；手机与电脑操作同一会话 |
| V06 微信文本 | 登录本人测试绑定；收、回、过期上下文、重复消息、断网与重连 | 真机文本闭环和去重字段有证据；不读取旧凭据、不与旧消费者争用同一绑定 |
| V07 故障恢复 | 发送前后、RPC 回执前后、Outbox 写入后分别中断桥接进程 | 已执行任务不重跑；不确定状态明确；原终端保留；关键结果可恢复 |
| V08 延迟与资源 | 两会话、各 10 条任务上限下持续收事件；长轮询断连；超长输出 | 统计本地控制处理 p95、内存趋势和队列上界；目标 p95 < 1 秒，排除模型及公网时间 |

V03 必须有真实原生交互；测试替身只能补边界，不能代替平台行为证据。V06 的扫码、绑定及实际发消息属于后续明确安排的联调，本轮没有执行。

每次记录版本、前置状态、步骤、预期、实际、脱敏日志和结论。失败结果进入 ROADMAP，证据文件只保存必要内容；没有采集到的状态标记未验证。V01 至 V04 通过后才扩大核心功能建设；微信通道也须在完整产品验收前通过 V06。
