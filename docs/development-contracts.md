# wx-clawbot 开发契约与接口验证方案

应用基线为 0.1.10，本文维护当前开发树的跨模块不变量、实际接口入口和 V00 至 V08；实际部署见 ROADMAP。产品需求见 [PRD](product-design.md)，结构见[架构](architecture-design.md)，如何开发和运行测试分别见[开发指南](development.md)及[测试指南](testing.md)。早期建议接口／表名不再作为实现 API；原稿的固定提交与章节映射见 [DOC01 报告](validation/documentation-restructure.md)。

## 1. 项目结构约定

源码按真实职责放在 `src/wx_clawbot/`；模块表见架构 F03。`tests/test_*.py` 为离线测试，`tests/integration/` 为显式集成入口，不能把其中所有脚本一并自动执行。`tests/fixtures/` 只保存脱敏最小样本；`config/` 只放无身份模板。状态在私有目录，临时资料在被忽略的项目 `.tmp/`。无行为不建框架层，规范以 AGENTS 为源。

## 2. 模块边界

| 边界 | 输入／输出与契约 | 不允许的替代 |
| --- | --- | --- |
| 通道→控制器 | 本人身份、稳定 message ID、有序内容、回复上下文；同事务接收游标／Inbox | 通道不选择 thread，不以正文哈希吞相同文本的不同消息 |
| 控制器→路由／目录 | 固定语法、当前列表、revision 和冻结 Dispatch；sessions 仅更新内存列表，不改变选择／订阅／任务或启动宿主 | 不让模型猜序号，不按标题或桌面焦点改投；查询不走选择恢复与持久化事务 |
| 目录→原生适配 | 准确 runtime／thread／native session／cwd、loaded、订阅 | 不读屏猜 ID，不恢复 notLoaded，不伪造 endpoint |
| 控制器→可见启动 | 持久化 launch ID、合法 cwd、可信 argv、自有 boot 与唯一握手 | 不将用户文本拼进 Shell，不重复未知创建 |
| 执行→原生队列 | 先记录提交意图和占用，再使用准确 thread、稳定 client；保存 queue／turn | ACK 不当作执行完成，本地等待不当作原生队列 |
| 原生事件→结果 | 单一消费、准确 thread／turn／client 及输入分类，真实终态 | commentary 不当 final，合并输入不假报各任务独立完成 |
| 结果→账本→发送 | 事务外渲染、终态和冻结 Outbox 原子落库，发送前记录尝试 | 历史回执不重渲染，发送失败不执行原任务 |

项目规则由原生机制负责；桥接不提供逐轮刷新、变更检测或自动阻断。实际限制见[规则契约](project-rules.md#已确认的原生限制契约)。

## 3. 规范化对象与接口

以下是源码中实际对象及关键入口的索引，不是保证所有对象都实现统一插件接口。精确签名仍以源码为准；不手写一套虚构 `openSession/startTask` API。

| 源码对象 | 关键字段／方法 | 使用约束 |
| --- | --- | --- |
| `channels.messages.IncomingText` | 规范化消息与有序内容，见类定义 | 已核验本人、稳定 ID，外部字段保留原义 |
| `routing.Target / SessionList / Dispatch` | session_id、project_alias、cwd、origin；list_id／targets／expires_at；target／route_revision／text／has_images | 冻结目标与快照，序号不能长期保存 |
| `sessions.SessionBinding` | endpoint 可空、project、runtime_identity、thread_id、native_session_id；`verify_binding`、`binding_key` | endpoint 不是必需原生路由身份 |
| `catalog.SessionCatalog` | `discover(keyword)`、`include_directory(cwd)`、`require(target)` | 完整有界发现才替换目录；require 独立复验 |
| `agents.base.AgentAdapter` | capabilities、runtime_identity；inspect、is_loaded、loaded_threads、observe_loaded、submit_idle | 只是当前最小 Protocol，不宣称统一所有 Codex 方法 |
| `agents.base.Capabilities` | observe、submit_idle、queue、interrupt、shared_interactions、image_input | 缺省 false，不能仅有方法名就宣称支持 |
| `agents.codex.CodexConnection` | connect、inspect、list_project_threads、loaded_threads、observe_loaded、read_turns、unsubscribe | 具体原生协议／版本／socket 检查在适配器 |
| `agents.queue.NativeQueue` | list、add、delete、request_interrupt | 独立队列类，控制行为须准确确认 |
| `controller.Controller / execution.Execution` | prepare、execute、restore；submit、dispatch、reconcile、control | 选择事务与执行／恢复分工；外部结果不能由本地标记推导 |
| `runtime_state.RuntimeState` | task_intent、task_update、task_finish、claim_reply、finish_reply 等 | 同一有界工作执行器；SQL 和外部网络不混事务 |

真实文件入口见[需求追溯](requirements-traceability.md)。原生 request ID 保留整数／字符串类型区别；墙钟用于持久化与显示，进程内期限同时使用单调时钟，不依靠本地时间猜双端先后。

### IMG01 图片输入契约

有序图片元数据与游标同事务保存，下载前固定本人和目标；下载／解密／完整 JPEG／PNG 解码在事务外有界执行。同会话后到文本不能越过未准备好的前图，控制命令不等待媒体工作。图片只作为原任务的原队列输入，不去图重投、不自动换模型。附件保留与未尝试提交任务恢复见[图片指南](image-input.md)和[账本](state-schema.md)。解析能力不等于同消息图文已真机交付。

## 4. 会话身份与启动握手

既有对话必需准确原生代次、thread／native session、注册 cwd、加载及正式订阅能力；无需 terminal 或可见 ID。发现根目录不代表递归子目录，预算或分页不完整明确拒绝。身份、稳定编号及 version 1→2 路由快照兼容见[身份契约](native-session-identity.md)。

新建先持久化 launch 意图，固定入口读取私有登记，launcher 使用 argv 和 exec，不让用户标题或路径成为 Shell 代码。boot 的 PID／启动时间／TTY 和真实端点核对后，再查唯一不可预测标记、非派生 thread、准确输入和 completed 回复；只有窗口回执不能 ready。未知状态仅核对，不重复创建。架构 F05 是当前时序。

## 5. 排队、任务与取消

任务状态是实现使用的名字，不能将早期 submitting／cancelling／outcome_unknown 当作真实枚举：

| 对象／状态 | 行为与转换依据 |
| --- | --- |
| task prepared | 原任务意图已落库，尚未完成 received 登记；崩溃按恢复规则保守处理 |
| received | 明确尚未尝试原生提交，可等待仓库／前序图片，可本地撤销；复验后可首次准入 |
| dispatching | 外部调用前持久化，原生提交结果不明必须 unknown |
| queued | queue receipt 已关联，仅表示原生接收；排队删除须原生确认 |
| running／waiting_interaction | 原生准确 turn 活动／等待同步交互；控制请求不入普通队列 |
| stopping | 原生中断请求前的意图，终态竞争仍由原生裁决 |
| completed／failed／interrupted／cancelled | 准确结果入账；interrupted 不保证所有系统子进程终止 |
| unknown | 不知道独立执行结果，只读对账；不能自动重投输入 |
| 占用 waiting／holding／released | 独立于 task.state，以严格证据与 revision 审计转换；释放不改写 unknown |

准入按同会话顺序、注册项目和 Git common directory 核验，避免本服务跨会话冲突；不承诺锁住外部客户端。实际容量以[账本](state-schema.md)为准。微信与[桌面专用入口](desktop-queue-contract.md)共享原生队列，原 TUI 的 Enter／Tab 不纳入统一入口。

## 6. 双端审批与追问

同步命令审批与 `requestUserInput` 使用同一原生 request，原生 resolved 才是完成裁决；本地锁只防本入口重复提交，不证明两端互斥。答复前校验 owner、准确 ID 类型、代次、thread、操作、期限及答案，先持久化 sending 再响应。断连／重启使旧入口 stale，未知响应不改为相反决定重试。微信十分钟过期只关本地入口，不自动批准、拒绝或取消原生请求。

同步多题 JSON 是原生题目 ID→回答数组，例如 `{"choice":["PHONE_ALPHA"]}`，单选可按题目规则带一份自由补充；同题复选后置。异步多题是全部 q 键→字符串，例如 `{"q1":"答案一","q2":"答案二"}`，不能传数组。异步不是原生同步请求，不保证暂停或全局首答互斥；详见[异步契约](async-questions.md)。

## 7. 微信请求字段核对清单

[固定参考](wechat-reference.json)记录同一 commit 与摘要，[微信协议](wechat-protocol.md)维护逐字段实际请求：登录前后 header／Bearer、二维码状态、getupdates 游标／消息身份、sendmessage 收件人／client_id／context_token、ret／errcode／message_id 以及重定向与媒体限制。不能只比较字段名称或把 client_id 认定为服务端幂等保证。

未知身份不保存正文；同 message ID 不重复交付，冲突内容保守记录。发送 unknown 可能已送达，不自动重试。缺有效上下文保留关键结果，不把 API accepted 当作手机收到。

## 8. 数据与错误处理

当前实际 13 表见[账本](state-schema.md)，projects／sessions 不在数据库表清单。错误是安全分类与用户处理动作，不假设下表为实现导出的统一错误枚举：

| 失败类型 | 必须行为 |
| --- | --- |
| 无目标／过期列表／身份变化 | 拒绝并提示刷新或重选，不猜测改投 |
| 未支持版本／能力 | 明确拒绝，先核协议和证据，不只扩白名单 |
| 队列／容量满 | 拒绝新增任务，保留旧任务和关键结果 |
| 交互已处理／过期／未知 | 不再授权，不复活旧入口 |
| 执行 unknown | 准确原生只读核对，不重跑 |
| 投递 unknown／通道失效 | 保留执行结果，诊断后按明确授权处理投递 |
| 目录越界／备份失败／账本不符 | 原选择或原库保持，不清库绕过 |

日志只记安全状态／类型和必要脱敏关联，不打印原始响应、正文或凭据。迁移、维护、释放和 retry 默认只读，apply 要求准确对象和对应权限，见运维操作卡。

## 9. 关键接口验证关卡

这些是持续有效的验证要求，不是本次已执行列表。历史版本通过和当前适用范围由[追溯](requirements-traceability.md)及证据给出；真实测试须明确新一轮授权与专用资源，旧 Goal 的单次许可不能继承。

| 编号 | 验证范围 | 通过标准及失败处理 |
| --- | --- | --- |
| V00 静态基线 | 实际版本、help、匹配 schema、固定来源 | 字段和门禁一致；不替代动态测试 |
| V01 宿主与身份 | 既有原生发现、同 cwd 多对话、换代／卸载／普通 Shell、可选宿主 | 准确对象无歧义，无页脚依赖；失效拒绝，不把存档加载当接入 |
| V02 原会话双端 | 桌面→微信→桌面多轮及桌面切换 | 同一准确 thread 上下文连续，微信不被动改投，无替代副本 |
| V03 双端交互 | 两端先答、冲突、同步多题／自由答、超时／断连迟答 | 原生一次有效决定和两端解除等待；异步不能混入这一承诺 |
| V04 原生队列 | 微信／桌面专用入口排队、取消、ACK 丢失 | 独立 turn／结果和准确关联，未知不重交，保留 TUI 反例 |
| V05 可见启动 | 合法／特殊字符路径、重复意图、丢回执、唯一握手 | 无注入、一次创建、两端同一对话，未就绪不假报成功 |
| V06 微信文本 | 本人登录／绑定／往返、重复、上下文和网络故障 | 真机通信与稳定去重证据；自然失效时点按已确认决定后置，不伪造期限 |
| V07 故障恢复 | 接收、RPC、终态／Outbox、HTTP 前后故障 | 意图持久化、unknown 不重放、原生保留、关键结果可核对 |
| V08 延迟与资源 | 合成负载、长输出、队列上界和控制路径 | 样本与边界可复现，本地 p95 目标 < 1 秒；不包含模型／公网 SLA |

V01 至 V08 的真实关卡不能由替身代替。自然上下文失效触发已获准后置，保留确定性故障／恢复测试；旧即时观察授权已使用，不新增发送或跨天预约。每轮记录版本、前置、意图、实际结果和脱敏证据，不能删除失败 case 再跑。

## MD01：新出站排版与冻结契约

新结果在事务外兼容渲染与结构分段，再一次冻结入账；发送器和重投不渲染旧正文。代码／URL／路径／引号内容保护、Android 验收与 Mac 缺陷以[排版专题](wechat-markdown.md)为准。旧 v4／v5 候选、失败样例和真人复制记录仅见历史证据，不作为当前生产候选状态。

## REC01：占用恢复接口

自动核验与 `admission-report / admission-release` 共享准确终态、提交／队列、revision 和审计判定。默认只读，apply 要求消费者停止、准确报告摘要和理由，无 force。释放不改变 unknown、原目标或旧输入；等待提示不按期限解锁。见[运维入口](operations.md#rec01-候选的准入诊断与受控切换)。

## ASK01 已确认施工契约

异步答案是原轮次输入，严格匹配预先登记 client、正文摘要、thread／turn 和来源才可分类为辅助输入；其他合并输入保持 unknown。状态持久化和冲突边界见[异步契约](async-questions.md)，不扩大版本门禁。
