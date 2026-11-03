# wx-clawbot 技术选型与决策记录

本文保存设计与验收要求；实际进度与验证状态以仓库 ROADMAP.md 为准。

本文承接已确认的 D01 至 D06；不重新讨论是否需要该产品。产品行为见 [产品设计](product-design.md) ，系统分层见 [架构设计](architecture-design.md) 。接口与验证见 [开发契约](development-contracts.md) ，执行顺序见 [施工清单](../goals/implementation-plan.md) 。

## 1. 选型结论

开发基线采用 Python 单进程服务：微信文本通道、命令路由和可靠性账本在本机运行；iTerm2 SDK 管理终端；Codex 原生接口控制同一会话；SQLite 保存必要运行状态。无需为该设计部署 OpenClaw Gateway，也不要求购买新的模型 API。

这是本项目的技术方案，不代表博主采用了相同实现。优先实现同一原终端、同一 Codex 会话上的远程操作；不以复制历史后新开后台会话替代用户需求。

| 决策 | 选择 | 原因与限制 |
| --- | --- | --- |
| T01 主语言 | Python 3.14，开发基线为本机 3.14.5 | 可直接使用 iTerm2 官方 Python SDK，并复用标准库；减少 Go 主程序加 Python 适配进程的边界 |
| T02 进程模型 | 一个 asyncio 服务，有限后台工作线程 | 收消息、处理控制命令和观察 Agent 并行；数据库、HTTPS 阻塞操作不阻塞主事件循环 |
| T03 终端宿主 | iTerm2 官方 Python SDK | 负责发现、校验、创建终端；Agent 语义由 Codex 适配器提供 |
| T04 Codex 通信 | 连接现有共享 daemon 的本机 Unix WebSocket | 原终端和桥接器连接同一运行时；既有会话是否满足此条件必须验证 |
| T05 会话排队 | 微信与桌面专用 `codex queue` 入口共用 daemon 队列 | 本人于 2026-10-25 确认；原 TUI 本地队列不纳入统一入口，客户端改造后置；SQLite 只记录意图和关联，见桌面排队契约 |
| T06 微信接入 | 基于腾讯公开客户端协议实现最小文本适配器 | 不安装整个 OpenClaw；仅承接登录、接收、发送和必需的连接状态处理 |
| T07 状态 | 标准库 sqlite3；配置 JSON | 消息、路由、任务和 Outbox 支持事务；不引入 ORM、Redis 或外部数据库服务 |
| T08 HTTP | 首先使用标准库 HTTPS 客户端与独立、有限工作线程 | 接收长轮询和发送分别占用资源；若原型无法满足取消、连接或延迟要求，再有依据地更换客户端 |
| T09 工程 | 项目内 .venv、pyproject.toml、精确依赖锁、unittest | 与用户全局 Python、Codex 配置隔离；锁定实际验证成功的依赖组合 |
| T10 常驻 | 用户级 launchd；先前台运行验收 | 常驻属于后续部署阶段；不立即注册系统服务 |

以上为开发侧选型。T04、T05、T06 必须通过原型关卡才能作为已支持能力发布；失败时先核对接口与实现，不悄悄改变 D01 至 D06。

## 2. 为什么调整草稿中的 Go

Go 并非不能实现；博主的 Go 方案也不构成我们必须使用 Go 的理由。本项目首版只有一个用户、少量会话，主要等待微信网络和 Agent 事件，尚无证据表明语言吞吐是瓶颈。

本机已有 Python，iTerm2 提供官方 Python SDK，Python 标准库又能处理 SQLite、异步子进程和测试。采用 Python 可以少维护一个宿主适配进程。语言选择以集成成本为依据，没有声称获得未经测量的性能提升。标准能力依据：[sqlite3](https://docs.python.org/3.14/library/sqlite3.html) 、[异步子进程](https://docs.python.org/3.14/library/asyncio-subprocess.html) 。

## 3. 设计输入时的静态快照

以下为最初文档准备时的历史输入，不是当前安装与进度声明。实施基线见 [协议记录](protocol-baseline.md)，原终端现场证据见 [W02 验收](validation/w02.md)，当前状态只见 ROADMAP；不据此自动升级。

| 项目 | 本机结果 | 解释 |
| --- | --- | --- |
| Codex CLI | 0.163.0 | 通过版本、help 和本机生成的 schema 核对接口名称 |
| Python | 3.14.5 | 作为首个开发与测试解释器 |
| SQLite | 3.53.2 | 本机 Python sqlite3 报告的库版本 |
| iTerm2 | 3.7.6 | 来自已安装应用的信息文件 |
| Go | 当前 PATH 未找到 | 不能据此断言电脑完全未安装 Go |
| iterm2、websockets、protobuf | 默认 Python 未发现可导入模块 | 尚未安装项目依赖或验证兼容性 |
| 新项目目录 | 已存在，当前为空 | 尚未初始化工程、Git 或部署 |

已生成稳定与实验版 Codex JSON schema。已核对 thread/read、thread/resume、turn/start、turn/interrupt 等接口；实验版 schema 还包含 thread/queue/add 等队列接口及 clientUserMessageId 字段。字段存在不证明去重承诺、审批竞争和终端广播行为成立。

本轮没有连接用户实际 Codex 会话、启动或停止 daemon、启用 iTerm2 API、执行模型任务或发送微信消息。

## 4. Codex：优先接入共享运行时

官方资料描述了共享本地 app-server、远程连接及队列命令；本机帮助也提供 app-server proxy --sock。首选方案是由桥接器连接同一原生 Unix WebSocket，读写 JSON 消息，让原终端继续拥有自己的界面。参考：[开发命令](https://learn.chatgpt.com/docs/developer-commands) 、[App Server](https://learn.chatgpt.com/docs/app-server) 。

必须区分以下情况：

| 现场情况 | 处理 |
| --- | --- |
| 已有 iTerm2 Codex 使用可连接的共享运行时 | 验证同一 thread、事件和审批后接入 |
| 已有会话使用独立运行时，例如 --no-daemon | 显示检测结果，调查可用正式入口；不能自动重启、复制会话或声称已接管 |
| 微信要求新会话 | 在 iTerm2 创建可见终端，并让它连接已验证的运行时；通过启动握手登记准确 thread |
| 一个目录存在多个终端或多个 thread | 用稳定身份建立关联；仅凭 cwd、标题或最近时间不能自动选定 |

只管理桥接器拥有的代理连接，不把断开连接解释为关闭用户 Codex。若需要本项目拥有的运行时，其创建、归属和退出策略必须在原型中明确；不自动替换用户既有共享运行时。

双端审批是核心验证项：原生 resolved 通知只能说明存在完成事件，不能单独证明两个客户端都收到同一请求、都能答复、且先答生效。必须真实验证这三件事。

## 5. iTerm2 SDK 与依赖审查

SDK 提供终端对象、创建 tab 和发送文本接口。发送文本是模拟输入，不能据此推断 Agent 接受、执行成功或进入审批状态；正式任务优先经 Codex 协议提交。参考：[SDK](https://iterm2.com/python-api/) 、[创建终端](https://iterm2.com/python-api/window.html) 、[Session 接口](https://iterm2.com/python-api/session.html) 。

| 依赖 | 调研结果 | 进入运行链前的门槛 |
| --- | --- | --- |
| iterm2 | PyPI 2.30，2026-10-12 发布；官方仓库与发布者入口可对应；声明 GPLv2+ | 在项目 .venv 验证 Python 3.14 与本机 iTerm2；固定版本与哈希，记录许可证 |
| protobuf、websockets | 官方 SDK 的传递依赖 | 锁定解析后的实际版本，完成导入、连接、断线测试；不能直接把调研时最新版本当作已测试组合 |
| 腾讯参考客户端 | 仓库 package.json 为 2.4.10，声明 MIT；插件依赖 OpenClaw | 仅作为协议和字段参考；移植代码时保留应有声明，不称其为官方 Python SDK |
| fastclaw-ai/weclaw | 本轮查到最新 release 为 v0.7.1；上游与截图中的 50 层修改不是同一份代码 | 只作参考，不直接引入整个 fork；未确认博主仓库身份 |

依赖依据：[iterm2 发布页](https://pypi.org/project/iterm2/) 、[SDK setup.py](https://raw.githubusercontent.com/gnachman/iTerm2/master/api/library/python/iterm2/setup.py) 、[腾讯 package.json](https://raw.githubusercontent.com/Tencent/openclaw-weixin/main/package.json) 、[weclaw releases](https://github.com/fastclaw-ai/weclaw/releases) 。

近期发布信息已核对；维护者长期活跃度和 issue 响应质量尚未完成充分核验，部分 GitHub 请求遇到限流。W01 应补齐，不能写成“依赖已全面审计”。许可证记录用于后续分发决策，本轮不直接替整个项目选定 MIT 或作法律兼容性结论。

## 6. 微信文本通道的证据与范围

腾讯仓库公开了客户端协议参考与请求实现，可核对二维码登录、getupdates、sendmessage、headers、context_token、游标和错误处理。该文档自身也区分客户端行为与服务端保证，因此不能把可选字段推导为服务端允许缺省，也不能把 client_id 当作已证明的服务端幂等键。依据：[协议参考](https://raw.githubusercontent.com/Tencent/openclaw-weixin/main/docs/protocol.md) 、[请求实现](https://raw.githubusercontent.com/Tencent/openclaw-weixin/main/src/api/api.ts) 、[登录实现](https://raw.githubusercontent.com/Tencent/openclaw-weixin/main/src/auth/login-qr.ts) 、[文本发送](https://raw.githubusercontent.com/Tencent/openclaw-weixin/main/src/messaging/send.ts) 。

首版只实现满足产品闭环的文本能力：登录、本人身份绑定、长轮询、结果与交互消息发送、失效检测。媒体上传、群聊、多账号和任意外部通知 API 不进入首版。

二维码展示先复用服务端返回的有效展示入口；如果实际返回值不能直接扫码，再在 W04 选择必要的展示库，不能仅打印未知格式的字符串就称登录体验完成。不会读取旧 OpenClaw 凭据来自动迁移账号。

本轮保存了公开源码的内容哈希，但未得到固定 commit 的完整验证快照。实施时应冻结一致的上游 commit、版本、许可证和关键文件哈希；不要把 main URL 当作不可变依赖。

## 7. 本机目录与生命周期

源码：`<project-root>/`。

2026-10-24 设计输入中的私有状态目录为 `~/Library/Application Support/wx-clawbot/`，当时仅确定路径；这一历史描述不代表当前未部署。当前已使用的 config.json、credentials.json、runtime.sqlite3、日志及托管布局见[运维说明](operations.md)，实际部署见[交付记录](validation/local-release.md)。目录权限 0700，敏感文件 0600；源码只保存脱敏模板。

Socket 优先沿用被核验的原生运行时地址，不猜测固定路径。项目自有 socket 若需要，必须检查 Unix 路径长度并使用私有短路径。launchd 的程序路径使用绝对路径，不能依赖交互式 Shell 的 PATH；停止桥接服务不默认关闭用户终端。

## 8. 设计输入时的未决项与开工条件（历史）

| 项目 | 当前状态 | 关闭方式 |
| --- | --- | --- |
| 原终端到 native thread 的可靠映射 | 接口方向明确，现场未验证 | V01、V02 |
| 两端审批及追问共享、先答生效 | 未验证，不降级为单端审批 | V03 |
| 原生队列与桌面输入协调 | 实验接口已存在，行为未验证 | V04 |
| 微信文本协议可用性、稳定去重键、回复上下文有效性 | 已核对参考源码，未真实绑定 | V06 |
| /attach 与 /detach | 本人已确认独立观察订阅 | focus 控制输入目标，attach 观察桌面任务，detach 只退订；按命令契约真实验证，不模拟成功 |
| 数值默认值 | 仍为设计建议 | 小负载与故障测试后校准 |

以上表格保留设计输入时的验证问题；当前完成状态只见 ROADMAP。完整功能开发须经过 V01 至 V04，不能用伪造事件或另建会话跳过核心体验关卡。

本机新 TUI 使用已核对的原生可执行文件、既有 CODEX_HOME 和本机共享 daemon 模式；桥接器用原生 Unix WebSocket 连接同一运行时。`--remote` 即使指向本机 Unix socket 也采用远端目录信任判定，不能假定与本机仓库根信任继承相同。一般 `-c` 参数会使已核对的客户端放弃共享 daemon，不能通过临时关闭更新检查规避启动界面；专用测试使用非空初始握手输入，并先核对就绪及共享运行时身份。相关实际证据和边界见 W02／W03 验收。

实施核对：`app-server proxy` 仅透传原始字节，不能直接写 JSONL。Unix 控制 socket 使用 WebSocket；桥接直连该 socket，不新建运行时。见 [官方固定源码](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/stdio-to-uds/src/lib.rs)。

可恢复错误状态：额度失败可使原 thread 显示 `systemError`，同时仍在原终端和运行时内存中。不能只按 idle／active 白名单将其当作未加载。对 systemError 额外要求原生 `thread/loaded/list` 包含准确 thread ID，且 `canAcceptDirectInput` 为 true；继续核验原进程、页脚 ID、运行时、sessionId 与 cwd。缺少任一证据即拒绝，不恢复存档副本。依据为固定 CLI schema、实际失败现场及[官方状态／已加载列表说明](https://learn.chatgpt.com/docs/app-server)。原失败任务保持 failed，只有用户新的请求进入原生队列。

## REC01：按证据释放占用

执行结果与仓库占用采用独立持久化状态；输入合并使独立结果不可确认时，原生准确终态和空队列仍可能证明占用结束。该证明只释放占用，不授权路由、不恢复旧线程，也不声称每条历史输入各自完成。以 revision／连接代次和事务拒绝陈旧证据；不能仅凭空队列、idle、时间或窗口退出释放。

活动查询走独立占用部分索引，已释放未知记录分页保留；不把它们计入活动上限，也不清理未知证据。原生历史查询在找到全部准确目标轮次后停止，不为占用判定扫描无关旧历史。操作与数据边界见[REC01 记录](validation/admission-recovery.md)。

## ASK01 已确认施工契约

ASK01 已确认采用 0.166.0 的结构化 agentMessage.questions 与准确 turn/steer；RPC ACK 只证明原生接受，输入精确可见另记 observed；拒绝伪造 resolved 和问题级互斥。依据及候选决策见[异步答复契约](async-questions.md)。
