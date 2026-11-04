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
    config.py
    routing.py
    catalog.py
    controller.py
    sessions.py
    execution.py
    subscriptions.py
    interactions.py
    async_questions.py
    async_state.py
    runtime_state.py
    occupancy.py
    admission.py
    admission_recovery.py
    admission_ops.py
    schema.py
    retention.py
    delivery.py
    output.py
    render_worker.py
    release.py
    channels/wechat.py
    agents/base.py
    agents/codex.py
    hosts/iterm2.py
  tests/
    test_*.py
    integration/
    fixtures/
  docs/
  config/
  scripts/
    check.py
    build_release.py
  .tmp/
```

先写 AGENTS.md，再创建实现目录；职责不足以独立成文件时允许暂时合并，不创建空壳。docs 保存正式设计和施工记录；config 只存无密钥模板；.tmp 不进入 Git。README 只写当前可用能力，未完成项放 ROADMAP。运行数据不在源码目录。

上图是当前核心入口映射，不是全部文件清单。配置／目录边界由 config 与 routing 实现，会话目录由 catalog／sessions／hosts 实现；任务协调在 execution，占用恢复拆至 admission 系列。runtime_state 与其同 worker 的占用／异步状态模块共同管理账本；结果并发在 results，生命周期在 runtime_lifecycle，托管在 managed。单元与契约测试当前直接放 tests 下，真实接口入口在 integration，不为早期目录建议创建空的 unit／contract 层。

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

### IMG01 图片输入契约

[IMG01 施工清单](../goals/20261028-1135-image-input.md) 第 1 节的本人范围决定及第 4 至 8 节定义本次扩展的行为、数据不变量和通过条件。当前交付单图，同消息图文保留解析能力但不宣称真机支持。IncomingMessage 与任务输入最小扩展为有序 text／image 内容项，附件记录关联准确消息与任务；纯文本继续使用原命令语义。

本人身份、目标和收件顺序在下载前校验及固定；附件元数据与游标事务保存，下载／解密／完整图片解码在事务外有界执行。图片准备不得让同会话后到文本超车，也不得阻塞状态、停止和交互控制。去重摘要覆盖全部内容项。

图片与文字以一次原生队列提交关联唯一 client／queue／turn；提交未知只读对账，不去图重投。附件在准备、排队、运行、unknown 或关键结果待交付时保留；升级与保留期维护均沿用默认只读、显式 apply 的工作流。真实运行库迁移单独落实对象和备份，不因 serve 自动升级。

图片下载器只负责受限 CDN 获取、解密、格式与资源校验，不决定项目或 thread。图片使用现有本人绑定、私有存储与当前模型；不增加外部视觉 API。G01 两端真实可行性通过前，不扩展完整产品实现。

## 4. 会话身份与启动握手

已有会话映射需要形成 terminal_id、进程身份、runtime、thread_id 四者的证据链。窗口名、cwd、会话预览只能辅助展示。无法唯一确定时返回候选让用户选择，不能把选目录当成映射成功。

新会话启动先持久化 launch_id，再调用 iTerm2。启动命令只包含可信解释器、固定启动入口和随机 launch_id；目标目录及选项由私有启动登记读取。使用 exec 的 argv 传入 Codex 参数，用户文本不进入 Shell 命令。iTerm2 的字符串 command 如必需，逐参数进行 Shell 引用，路径中的空格、引号和替换符必须测试。

启动握手收到真实端点与 thread 后才标记 ready；只看到新 tab 不够。连接或启动超时保留 starting／unknown 供核对，不因重试创建第二个窗口。只回收本次创建且确认归属的失败资源，用户既有终端不被误关。

既有会话发现机制须在 V01 选出可验证方案；需要用户一次性绑定可以作为显式交互提出，但不能隐瞒自动发现不足。独立运行时无正式入口时记录具体阻塞，不自动迁移原会话。

## 5. 排队、任务与取消

唯一执行权威是原生运行时。原型先验证原生队列：提交时携带稳定 client_submission_id，保存返回的队列身份，并追踪到实际 turn。客户端关联 ID 是否有去重保证必须实测，不能默认成立。

首版桌面普通任务经已确认的专用 `codex queue` 入口，与微信侧使用同一 daemon 队列；原 TUI Enter／Tab 不作为统一队列入口。电脑提交端须核对运行时与完整 thread ID，保留真实 queue receipt；两端任务必须按顺序各自形成独立 turn 和结果。原按键反例与后续客户端改造依据见 [桌面排队契约](desktop-queue-contract.md)。

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

本节首次有效答复裁决指同步原生 server request；ASK01 异步 agentMessage 采用已确认的补充模式，不能套用原生首答互斥或暂停语义，见文末异步契约。

裁决点必须是两端共享的原生请求状态。服务记录 request ID、运行代次和连接归属，将明确的操作、选项及项目发送到微信。微信答复先验证身份、关联、有效期与答案类型，再通过持有该请求的正式协议连接回答。

电脑先回答：收到原生已处理状态后关闭微信待答入口。微信先回答：必须观察到电脑端原生等待状态解除。冲突同时到达：只允许原生接受一次有效决定；本地数据库只辅助去重，不能替代真实竞争验证。

任一答复结果不确定时不再次提交相反决定。断连后旧请求先标记 stale，核对原生是否仍等待；超时不能静默放行。需要拒绝或取消时使用正式支持的动作，并记录其确认结果。

“首次”指原生裁决点接受的首次有效答复，不按两台界面的本地时间猜先后。首版追问经本人确认采用多题单选与自由文本，同一题复选后置；须测试多题关联、选项、文本、无效答案与用户取消，不同交互类型的通过结果分别记录。

## 7. 微信请求字段核对清单

以下是实现前逐字段核对入口，具体 payload 以[固定 commit 与文件哈希](wechat-reference.json)为准；本项目字段对照见[微信协议](wechat-protocol.md)。

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

HOST01 另按[宿主生命周期施工清单](../goals/20261029-1038-host-lifecycle-recovery.md)增加宿主退出／重启、按需启动、同步认证硬截止、代次隔离和会话复验关卡；微信收发独立于 host／native 可恢复缺席，原生提交与未知创建仍保持最多一次。该契约不代表新增能力已验收，不降低下列 V01 至 V08 关卡。

全部动态测试先在两个 fixture 项目进行；不得向用户正在使用的终端注入试验任务。测试专用 iTerm2 会话需先在终端正常启动，再模拟桥接服务接入，以覆盖“已有会话”。

| 编号 | 验证动作 | 通过证据与失败处理 |
| --- | --- | --- |
| V00 静态基线 | 版本、help、schema、公开源代码核对 | 本轮已完成该范围；不代表下面动态关卡通过 |
| V01 宿主与身份 | SDK 连接；发现正常／普通 Shell／已退出端点；同目录两个 Codex；核对 daemon 与 thread | 映射无歧义、旧端点不误投、独立运行时被识别；失败先补映射方案 |
| V02 原会话双端 | 桌面先发送标记，桥接发送第二条，桌面继续第三条；核对原生历史与结果事件 | 同一个 thread 和可见终端，三轮上下文连续；不能以恢复副本通过 |
| V03 双端交互 | 两端分别先答；同意与拒绝竞争；多题单选与自由文本追问；断线、超时与迟到答复 | 每个原生请求仅一次有效结果，两端解除等待；不支持共享请求即停止宣称 D05 可用 |
| V04 原生队列 | Agent 忙时桌面专用入口与桥接各追加任务；取消排队／运行任务；提交回执丢失后恢复；保留原 TUI 反例 | 两端共用 daemon 队列，按序独立完成且关联实际 turn；控制操作及时处理、取消有原生确认；不以未获确认的其他入口替代 |
| V05 可见启动 | 从项目选择请求创建新 tab；含空格路径、恶意替换符、重复请求、启动中断 | 无 Shell 注入；同一 launch_id 不重复启动；手机与电脑操作同一会话 |
| V06 微信文本 | 登录本人测试绑定；收、回、过期上下文、重复消息、断网与重连 | 真机文本闭环和去重字段有证据；不读取旧凭据、不与旧消费者争用同一绑定 |
| V07 故障恢复 | 发送前后、RPC 回执前后、Outbox 写入后分别中断桥接进程 | 已执行任务不重跑；不确定状态明确；原终端保留；关键结果可恢复 |
| V08 延迟与资源 | 两会话、各 10 条任务上限下持续收事件；长轮询断连；超长输出 | 统计本地控制处理 p95、内存趋势和队列上界；目标 p95 < 1 秒，排除模型及公网时间 |

V03 必须有真实原生交互；测试替身只能补边界，不能代替平台行为证据。V06 的扫码、绑定及实际发消息必须在明确安排的本人联调中执行，不能以模拟替代；实际验证状态见 ROADMAP。

本人于 2026-10-25 同意分阶段完成 V06：W04 以真实通信闭环、去重、游标和断连恢复验收；自然过期观察原转入 W08。2026-11-01 本人明确同意修订：自然失效的实际触发时间后置为非阻塞观察，保留未验证记录，不再为等待某个天数阻塞交付，也不将普通业务拒绝或替身测试称为自然过期证明。V06 的本人真实通信证据继续必要；发送失败后的结果保留、unknown 不自动重试、任务不重跑、明确授权的重试使用新上下文及准确绑定，须由确定性故障／恢复测试验证。

本次允许对既有确认本人绑定进行一次即时旧上下文观察，不继承已错过预约；发送前复验原 case／绑定／凭据，记录实际年龄、单次意图和结果。若旧值被拒且非账号失效，再等待本人真实新消息产生不同上下文后单次核对恢复；unknown 不重试。若旧值仍被接受，则记录结果，不再延长等待。不得因此操作微信 UI、重登、修改生产账本或派发原生任务。后续跨天预约须具备持久化计划、重启恢复和过期检查；本次改用即时执行，不新增托管或系统配置。

每次记录版本、前置状态、步骤、预期、实际、脱敏日志和结论。失败结果进入 ROADMAP，证据文件只保存必要内容；没有采集到的状态标记未验证。V01 至 V04 通过后才扩大核心功能建设；微信通道也须在完整产品验收前通过 V06。

## MD01：新出站排版与冻结契约

2026-10-31 S02 真人对照已确认：明确标注“第 4 项续段／代码”并将代码置于顶层独立消息时，Android 续段、所属关系、代码边界和 END 完整可见；本人以首尾标记保护中转后的两行代码与 37 字节预期一致。后续将该兼容接入直接包含代码的顶层简单列表项：保留原编号／顺序，将该项续段和代码用明确所属标签另列，代码主体只移除列表容器前缀，字面内容与行尾保持。含子列表、引用或未知块的复杂项保留原结构，不凭这一短样声称其已经真机通过。为避免再次串扰，兼容生成的顶层代码仍单独分段；不得改写原生结果、历史冻结正文或已收集的复制原文件。

2026-10-31 夜间候选修正：本人确认混合结果的 Android 实际界面也有行内内容移位，原生输出与冻结正文均逐字正确。G03 试用完整复杂列表／引用与根级代码块的消息隔离，保留全部原文及独立段号；强制边界超过 64 时转明确的保真片段，避免短容器生成无界数量的消息。同时代码保真须比较解析后的实际代码内容，不能只断言源字符串仍在围栏内；补齐深缩进和列表结构缩进的语义回归。括号 HTTPS 兼容统一采用本人 L02 确认可点击的标准自动链接，离线回归须核对实际 href，不能只核对 URL 字符串仍存在。该 v5 候选完整 509 项回归通过，未有真人显示证据，留在磁盘，不加载或冒充修复通过；生产维持已加载的 v4。

2026-10-31 本人已明确将 Mac 完整要求后置，本次必要客户端为 Android 微信 8.0.80；其余格式、复制、真实任务和投递安全关卡保持。后文 2026-10-30 的 Mac 必验安排仅为历史决策，当前完成条件以 [MD01 第 1 节](../goals/20261029-1217-wechat-markdown-rendering.md) 为准。Mac 缺陷和原始结果保留，不冒充通过，也不新增媒体／网页替代能力。

Mac 简单表格的转义竖线实测出现缺失时，采用已定义的字段列表兼容：按原始行／列顺序保留表头与数据对应，单元格代码和链接保持其语义，重复／空表头不得造成字段丢失。仅转换解析器确认的顶层简单表格，嵌套容器未验证时保留源结构，不宣称支持。

双端实测后，新出站兼容以可辨分行为准：普通说明单 LF 可转成段落边界，代码和链接字面内容中的换行保持；引用式链接可展开为普通链接，目标准确；仅在没有反引号冲突时将波浪线围栏转换为三反引号。复杂围栏或受限客户端无法保真时保持未验收，禁止插入不可见字符来掩盖差异。旧回执继续冻结，不重新渲染。

2026-10-30 本人已接受标题显式层级标记兼容并确认 Android 加粗明显，允许先按 Android 实施，Mac 手动验收保留至当晚 20:00。新展示保留标准 LF；H1 至 H6 使用加粗的中文级别标记。代码、链接与引用式定义按源切片保护，超长不可分结构明确标注片段；新增展示仅入账一次，发送器不重渲染旧 outbox。Mac、复制及真实新结果验证仍是完工条件。

本人已于 2026-10-30 明确启动 [MD01](../goals/20261029-1217-wechat-markdown-rendering.md)。先核验目标客户端的核心格式能力，再实现统一的入账前展示及结构分段；规范只约束新回执，原生历史和任务输入保持原样。中文排版只处理可识别正文节点，代码／命令／路径／URL／引号字面值保护；旧 outbox 正文、摘要和投递重试使用原冻结内容，不进行二次渲染或迁移。仍使用现有 text_item.text，禁止添加猜测的 Markdown 协议字段。核心效果不可达时保留未通过并由本人决定范围，不用图片／网页替代文本冒充通过；样例和正式 Agent 结果分别取证，不改变 HOST01 身份、队列及审批语义。

## REC01：占用恢复接口

本节定义 `0.1.1` 的已交付契约，实际本机证据见[REC01 记录](validation/admission-recovery.md)。tasks.state 继续保存真实结果；独立占用状态和追加审计记录决定仓库许可。初始化／迁移不得释放历史非终态已提交任务；received 尚未取得原生提交资格。新原生提交前原子取得占用，ACK 不明继续 holding。

自动核验与人工处置共享一套证据判定和比较更新；只有准确终态、关联完整、提交已排除在途且队列核验通过才可释放。合并 turn 的结果继续 unknown。释放不提供新派发权限，原目标仍须完整核验。128 条活动、十条会话等待及两个活动项目均排除已释放历史，但不能截断仍 holding 的视图；unknown 不因此进入保留期删除。

等待持久化阻塞者、原因、核验时间和通知状态，初次提示与 60 秒升级各至多一次；不以期限解锁。人工处置默认只读、准确任务加 revision／摘要、显式 apply、理由和消费者维护锁，拒绝无证据 force。详见 REC01 清单及[正式证据](validation/admission-recovery.md)。

## ASK01 已确认施工契约

ASK01 异步补充是运行中用户输入，跨端可同时接受；同步请求的首次有效答复裁决不延伸到异步。新输入严格身份、单次意图、冲突及恢复契约见[异步答复契约](async-questions.md)。
