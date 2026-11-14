# 运行账本版本与升级

本文件说明程序自有私有账本，状态以 [ROADMAP](../ROADMAP.md) 为准。真实业务项目数据库与 Codex 历史不属于升级对象。

当前代码 `0.1.12` 使用 schema 6，延续 ASK01 已备份并显式升级的结构；具体本机加载状态见[部署证据](validation/local-release.md)。路由 JSON 快照 version 2 是独立格式，不是 SQLite schema 版本，见[身份契约](native-session-identity.md)。升级链支持 1／2／3／4／5→6；下方带旧版本的章节保存历史演进，不能当作当前部署版本或重复执行操作卡。

## 当前结构总览

PRJ01 自 0.1.11 提供，不增加项目 SQLite 表，不升级 schema 6；项目清单仍在私有配置，路由快照 version 2 仅增加可选 registry_revision，结合配置中的取消修订阻止旧选择在重新注册后复活。当前交付状态及新旧配置回退见[项目管理](project-management.md)，这不是旧日常制品已支持新格式的声明。

DDL 与结构校验以 [schema.py](../src/wx_clawbot/schema.py) 及 [runtime_state.py](../src/wx_clawbot/runtime_state.py) 为实现源；不在文档复制完整 SQL。当前 13 个业务表如下，SQLite 内部统计对象不算业务表。Project 来自配置，会话目录来自原生发现，没有 projects／sessions 表。

| 表 | 主标识／关系 | 职责与关键保护 |
| --- | --- | --- |
| channel | 固定 id=1，bot／owner | 本人绑定与接收游标，开库必须匹配凭据 |
| inbox | 稳定 message_id | 接收序号、正文／有序内容、摘要、phase；游标同事务，清理后保留去重墓碑 |
| reply_context | 固定 id=1 | 当前本人回复上下文，旧／重复入站不覆盖较新值 |
| tasks | task id，source_message_id／client_id 唯一 | 冻结 target、输入、原 thread／queue／turn、执行状态；external 无微信入站来源 |
| outbox | event id，逻辑关联 task | 冻结文本、优先级、投递状态、服务端回执；不能推导手机实收 |
| routes | 固定 id=1，外键 channel | 选择 JSON 快照；当前 version 2，旧选择无法复验只留诊断 |
| interactions | public_id，generation＋native_key 唯一 | 同步请求参数／目标／期限／状态，原 ID 类型不混淆 |
| delivery_attempts | outbox_id＋number，外键 outbox | 每次 HTTP 意图、上下文、client、结果；同回执最多一个 sending |
| attachments | id，message_id＋item_index 唯一，关联 Inbox／task | 私有媒体参数、文件与摘要、准备状态；完成／明确失败清除下载秘密 |
| task_occupancy | task_id 外键 | waiting／holding／released、revision、证据与核验时间 |
| occupancy_audit | id，task_id＋revision 唯一 | 追加占用变更，不把释放等同任务完成 |
| admission_waits | task_id 外键 | 阻塞者、原因、首次／最后核验和升级提示状态 |
| async_questions | public_id，source＋thread＋turn＋item 唯一 | 异步题目／答案／摘要／revision／期限；answer_client 唯一，关联 task |

逻辑关联不一定都有 SQL 外键，例如 tasks.source_message_id 和 outbox.task_id 不应画成强制外键。恢复状态和容量见后文，异步详情见[专题](async-questions.md)。

`<state-dir>/runtime.sqlite3` 的 application_id 固定为 wx-clawbot runtime，user_version 管理结构版本；本人 bot／owner 绑定必须匹配。默认先检查计划：

```sh
.venv/bin/wx-clawbot migrate-state --state-dir /absolute/path/to/private/state
```

检查只读返回版本、行数和变更对象，不返回身份、正文或凭据。默认私有目录与 `serve` 一致。

## 版本 2 到 3：图片附件

IMG01 当时将账本扩展为 3：新增 attachments，以及 inbox.content、tasks.input_items。前者保存必要私有下载材料、准备状态和文件摘要；后两者保存有序正文及附件引用，不把密钥放入任务输入。纯文本旧行默认空结构化内容，原任务、路由、交互、回执、正文摘要及未知状态保留。

migrate-state 默认只读。升级 1 或 2 时，先停止前台并取得原消费者锁，验证原版本和本人绑定，生成对应 runtime-v1 或 runtime-v2 私有备份，核对完整性及该版本全部旧表行数，再在事务中依序迁移到当前版本 6。失败回滚，不自动从备份覆盖。新库直接初始化当前版本 6；真实库是否升级只见 ROADMAP。

附件元数据、消息和游标在一个事务保存，任务创建和附件绑定也在一个事务。文件写入前记录随机文件名及摘要，采用 0600 临时文件、fsync 和排他落盘；缺失、半文件或摘要变化不会作为正确图片提交。准备完成或明确失败后清除下载参数和密钥。

仅 received 且原目标重新核验的图片可以继续准备及首次准入；已尝试提交者维持未知对账规则。清理先提交 released 决定，再删该记录的私有文件；磁盘失败保留文件名供下次显式维护重试，计划另列 released_files_pending。原生历史内联图片不属于清理范围。

下节保留版本 1 到 2 的历史步骤；当前升级器会继续执行图片步骤，不将只完成旧步骤误报为最新版。

## 版本 1 到 2

变更语句以 [schema.py](../src/wx_clawbot/schema.py) 的 `UPGRADE` 为唯一实现源。新增 routes、interactions、delivery_attempts，分别承载路由快照、连接代次绑定的交互，以及独立发送尝试；inbox 与 outbox 新增 body_sha256，保留正文清理后的稳定去重与冲突识别。原有列、消息 ID、任务与投递状态不由结构升级删除或重置。

版本 1 没有记录每次 HTTP 的准确起止时间。已有 sending／accepted／unknown／rejected 只以 legacy-v1 来源留存原状态，起止时间为空，不把创建时间冒充发送时间，不将 unknown 改为 accepted。旧诊断库不在本次升级范围。

显式执行前须确认升级对象与数据范围，并停止本项目的前台消费者：

```sh
.venv/bin/wx-clawbot migrate-state --state-dir /absolute/path/to/private/state --apply
```

执行器取得同一消费者锁，检查归属、结构及完整性，在冻结写入的事务中生成独立版本 1 备份。备份位于私有 `backups/`，权限为目录 0700、文件 0600；核对完整性、版本、绑定与全部旧表行数后，才添加结构、回填摘要并提交版本。失败时回滚事务，保留备份，不自动覆盖式恢复原库。

新建的程序自有账本直接初始化当前版本；已有旧版本不会因启动 `serve` 自动升级。版本不支持、表结构异常、绑定不符、备份超时或已有消费者占用都会拒绝执行。已是当前版本时重复升级不再生成备份。后续状态恢复对 sending／running 的未知分类与结构迁移分别记录，不能据此重新执行任务。

## 状态与恢复不变量

- 路由切换先取得原生订阅确认，再持久化候选快照，提交后才用于后续普通消息。失败恢复原选择的订阅；无法恢复或落库失败则停止前台处理，不能返回切换成功。重启重新发现并核验完整稳定会话 ID 与 thread，旧列表序号不恢复。
- 交互记录固定原始 ID 类型、连接代次、项目目标、操作和期限。答复 sending 意图在原生发送之前提交；电脑抢先处理、持久化期间过期、断连或不确定发送均不能重新授权。恢复不回答旧请求，原生 resolved 是处理确认。
- received 明确表示已记录且尚未调用原生提交，跨会话冲突时在此等待；可撤销这类本地等待。程序恢复后仅对完整身份复验通过的 received 继续准入。dispatching、queued、running、stopping 重启先归为 unknown；以原生 queue／client／thread／turn 核对，缺少记录不表示未执行，恢复路径不调用 queue/add。
- 准入保留同会话 FIFO，以 Git common directory 识别同仓库及 worktree；没有 Git 仓库时按注册项目根目录隔离。最多两个桥接活动项目、同项目或仓库只允许一个桥接会话持有未结束任务。检测到其他桌面会话活动时暂停新增派发；不能阻止独立客户端自行启动任务。每会话最多十条桥接排队／准入等待，活动占用（waiting／holding）最多 128 条，released unknown 不计入，不能用截断后的任务视图作互斥判断。
- 每次新准入与等待释放前重新发现已注册项目的当前会话，不能依赖上次列表遗漏后来出现的桌面活动；这不改变用户已经选择的列表快照与冻结目标。运行中停止先持久化 stopping 意图，再调用原生中断，回执与完成竞争时以真实终态为准。
- 原生队列满是已知未提交失败；原生队列删除与运行中断仍要求各自的确认。准入等待的本地撤销不冒充原生取消回执。
- 每次 HTTP 发送前原子登记尝试及其上下文，发送终态与 Outbox 同事务。发送 unknown 不自动重试；操作员若明确允许可能重复送达，才可准备独立尝试，最多三次，总是沿用原结果而不调用执行。成功消息 ID 与业务错误同时出现时保守记为 unknown，这是本项目的安全判定，不声称服务端提供了该组合的幂等保证。
- 紧急控制和交互优先于最终结果，最终结果优先于普通回执与进展；同优先级按插入顺序，不因墙上时钟回拨重排。终态事务淘汰尚未发送的接受／进展提示。

桌面主动任务以 `e-` 身份登记 external 来源、准确 thread／turn，以及可用的原生 client ID；没有微信 source_message_id，不保存原始任务正文，也不调用提交接口。聚焦可核对正在运行的桌面任务以供状态／停止；普通桌面结果和新交互仍由独立观察订阅决定。显式 stop 的中断终态会回执，不能将“请求已发送”当作中断完成。桌面任务的本地 client_id 是明确标记的索引，不冒充原生提交回执。

## 输出、容量与保留期

最终结果按行优先分段，每段含任务 ID／段号；观察长结果含项目来源。单段正文最多 7000 字符，最终回执总正文限制为 480000 字符，错误另保留最多 8000 字符。超限时明确提示并保留开头与末尾，完整内容仍在原终端；错误不会被普通正文截断挤掉。可辨认自然语言在输出层确定性处理中文间距与标点，代码块、命令、引号内容、路径、URL 和超长单行保持原文，用户提交正文不经过该渲染器。

本人微信显示对照证明：普通 LF 和 CRLF 被呈现为软换行，双 LF、U+2028、U+2029 可以分隔；代码围栏内的原始 LF 可显示为独立代码行。新回执使用 U+2028 表达说明与列表的逻辑换行，代码围栏使用 Markdown 段落边界并保留代码原始 LF。长代码分段补齐显示围栏，不丢失代码行；不对已记录的历史回执重新排版或重发。审批／追问完整提示超过 7000 字符时只提示原终端处理，不提供截断后的授权入口。显示对照不等于独立定位了服务端和客户端的具体实现。

前一最终段 sending／unknown／rejected 时，后段不越过它发送；紧急控制仍优先。旧进展与接受提示在事务内合并，不能在运行或终态之后追加过时的入队提示。未核对回执达 1000 条或 8 MiB 时停止接收新执行任务，保留现有结果和控制入口；单消息、RPC、HTTP、并发命令和事件队列分别有边界，不无限积压正文。已处理交互内存保留最近 64 条，交互总数最多 256、参数最多 16 MiB；未回答记录不为容纳新请求而丢弃，超限提示原终端处理。

保留期维护是显式操作，前台不会自动删除历史：

```sh
.venv/bin/wx-clawbot maintain-state --state-dir /absolute/path/to/private/state
```

默认只读列出符合条件的数量。操作员明确决定清理、停止前台并核对范围后，才添加 `--apply`：已结正文／上下文 7 天，已结任务、回执及交互摘要 30 天；unknown、未结束任务和未送达关键结果保留。入站稳定 ID 与摘要作为防重墓碑保留，摘要清理后旧消息仍不能重新执行。该操作只改程序账本，事务失败回滚；不触及 Codex 历史、项目文件或私有备份，也不宣称对 SQLite 旧页进行了物理安全擦除。前台输出安全状态与分类，不创建正文日志文件；managed 另保存受限、有界、轮转的诊断日志，不放开原始响应或私人正文，布局见[运维](operations.md)。

## 验证范围

冻结的 [版本 1 schema 样本](../tests/fixtures/runtime-v1.sql) 不含身份或消息正文。离线测试覆盖完整保留旧列数据、准确备份、DDL 后失败回滚、备份超时、占用锁、错误身份／版本／额外表拒绝，以及默认 CLI 不执行升级。真实运行库的具体执行与授权记录只由当次施工文档和 ROADMAP 记录，测试通过不表示真实库已经升级。

## PERF01 候选版本 3 到 4

[PERF01](validation/performance-optimization.md)实现版本 4，当时整合到 `0.1.0` 并完成本机升级；当前版本见 ROADMAP。版本 4 仅新增以下索引，不改变业务列、冻结正文、状态或唯一性：

| 索引 | 定义／作用 |
| --- | --- |
| `reply_task_kind` | `outbox(task_id,kind)`，定位同任务的前序 final 段 |
| `task_native_turn` | `tasks(thread_id,turn_id)`，按准确原生 turn 查任务 |
| `task_active` | `tasks(state) WHERE state NOT IN ('completed','failed','interrupted','cancelled')`，只扫描活动任务；查询显式指定该索引，避免新库统计缺失时扫终态历史 |

候选升级器支持 1／2／3 到 4，新库直接初始化 4；旧库 `serve` 仍拒绝隐式升级。3 的备份包含 attachments 等全部旧业务表，备份核对、绑定、消费者锁、FULL、事务回滚及 unknown 不重放保持。只有显式升级事务执行索引 DDL 和 tasks／outbox 的 ANALYZE；日常启动和领取不做统计维护。版本 4 开库还核对三个索引的准确结构，缺失／不符拒绝。

迁移演练、逐表摘要、额外文件／索引字节及写入成本见[正式数据](validation/performance-optimization.json)。不将合成库成绩当作真实库已升级；生产切换遵循[操作卡](operations.md#perf01-候选的独立验证与生产切换)。旧程序只识别到 3，不能直接回退运行 4；已产生新写入时不得覆盖旧备份。

## REC01 候选版本 4 到 5

`0.1.1` 当时将任务结果与仓库占用分离并完成本机加载，实际结果见 ROADMAP 和[REC01 记录](validation/admission-recovery.md)；上述版本 4 说明保留首版历史。新增 task_occupancy、occupancy_audit、admission_waits，字段及证据语义见同一记录。

占用有 waiting／holding／released 三态。旧 received／prepared 初始化 waiting，其他旧非终态已提交记录保守 holding；终态旧任务不增加占用。新意图及占用、派发状态变更、终态及释放与审计保持各自原子事务。占用释放不改写 tasks 的 unknown、输入、原目标或 client／queue／thread／turn。

新增索引为 occupancy_active（waiting／holding 部分索引）、occupancy_history（state／task_id 分页）及 task_unknown_history（unknown 的任务 ID 部分索引）。准入基于独立活动占用，最多读取 129 条并在超出 128 时拒绝，不能用截断结果放行；已释放未知记录不耗用活动名额，但依旧受 unknown 保留保护。显式刷新每次至多 20 条历史未知，完整身份／唯一 client 条件仍决定能否恢复结果；不以占用终态伪造任务完成。

升级器支持既有 1／2／3／4 依序到 5；默认 inspect 只读，apply 须停止消费者、核对本人绑定、备份与完整性，在事务内增加结构和索引。失败回滚，重复当前版本不新增备份。新库直接初始化 5，已有旧库 serve 拒绝隐式迁移。运行开库验证新索引准确结构及每条非终态任务的占用记录，不允许缺失占用悄悄放行。

历史 unknown 即使已释放占用，维护仍保留其输入、附件、结果关联与去重证据；后续严格核对确认为终态并交付后，才进入既有已结保留期规则。旧程序不认识版本 5，不能覆盖已有新写入的库回退到 4；操作卡见[运维](operations.md#rec01-候选的准入诊断与受控切换)。

## ASK01 已确认施工契约

ASK01 的 schema 6 新增 async_questions 及 async_turn／async_active／async_task 索引，字段与唯一约束见[异步答复契约](async-questions.md)，DDL 以 schema.py 的 ASYNC_UPGRADE／ASYNC_INDEXES 为准。本机 5→6 升级已验证私有备份、旧 12 表逐行摘要、完整性和外键；旧库启动不隐式升级。sending 答案重启后变 unknown，pending 变 stale，准确输入关联证据保留；维护只清已关闭且允许处置的记录，未结／unknown 及活动任务所需证据不清除。

## NCM01 控制意图文件（开发候选）

标题保留既有链接；此数据格式自 0.1.12 纳入源码，部署状态见 ROADMAP。

保持 schema 6 和既有表结构。`<state-dir>/native-controls/<sha256(message_id)>.json` 是私有设置操作记录，不是 SQLite 表、Agent 任务或原生设置缓存。format 1 包含 key／fingerprint、准确 target（桥接会话／原生 thread／native session／cwd／代次）、before、显式字段映射 setting、reasoning_source、phase、时间及终态冻结 reply；成功还记录 after 和 settings_event。该记录只用于至多一次发送及核对，不覆盖任何原生值。

phase 为 intent／unknown／confirmed／unchanged／rejected。intent 在 RPC 前落盘；崩溃遗留 intent 仍须按待核对处理，不能推断未发送。重复源消息命中任何 phase 均不再次写入；终态回执复用原文，不拿当前读值改写历史成功。读取时核 0700 目录、0600 普通文件和身份／大小；每条上限 16 KiB、最多 2048 条，达到上限或记录损坏就拒绝新增设置。记录只在短 lease 下创建或原子替换，并同步文件与目录；任何锁均不跨原生 await。

不会自动删除、轮转或恢复旧版本文件。普通账本维护不清理这些去重证据，备份及兼容回退须保留整个目录；见[运维](operations.md#ncm01开发候选的控制记录与回退)。查询与手动明确下达的新命令不等于恢复重放；unknown 的原操作和时间保持历史事实。

NCM01 模型设置的 setting 为 model／effort 映射，reasoning_source 区分 model_default／explicit；Fast 为 serviceTier 映射。旧候选 format 1 的 field／value 及旧 fingerprint 保留作历史去重证据，不改写、不重放；重送形态不匹配明确拒绝。无数据库迁移。

账号额度查询不新增表、文件或持久缓存；仅当前原生快照在本次回执中作为账号级信息展示，身份及余额／重置券等元数据不进入正文。已投递回执保持既有冻结语义，不能当后续当前额度。
