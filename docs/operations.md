# 前台使用与运维

本手册描述当前稳定操作路线。默认状态根为用户的 `Library/Application Support/wx-clawbot/`；以下 `/absolute/path/...` 均为占位值，执行前替换为准确对象。前台、用户级托管和真实测试不可并行争用同一本人绑定／消费者。文档提供方法，不代替当次提交、部署、发送、数据修改或删除授权。

当前进度见 [ROADMAP](../ROADMAP.md)，版本能力见[协议矩阵](protocol-baseline.md)，数据结构见[账本](state-schema.md)。历史候选操作卡在本页末保留入口；旧 schema 的步骤不能直接用于当前库。

## 安装与准备

1. 准备 Python 3.14、Git、已登录 Codex 的既有 daemon，以及用于可见新建的 iTerm2。开发环境安装见[开发指南](development.md)；日常托管使用下文独立非 editable 制品。
2. 在本项目私有状态根准备 `config.json`，从[模板](../config/config.example.json)填写别名与真实绝对 root。注册范围不是系统沙箱。私有目录本人所有、0700，敏感文件 0600，不放仓库。
3. 首次本人扫码和明确绑定按[微信指南](wechat-protocol.md#前台扫码与本人联调)执行；已有本项目绑定直接复用，不重新扫码覆盖，不读取其他项目凭据。诊断 echo 和 serve 不同时使用同一消费者。
4. 在普通 Shell 只读查看 `codex app-server daemon version`。桥接不启动／升级 daemon，实际 app-server 版本须匹配协议矩阵；该输出可能含本机路径，不直接公开。
5. 可见新建需要本人在 iTerm2 设置启用 Python API 并允许可信脚本。显式 `doctor --iterm2` 可能触发授权，不自动修改设置。

## 启动、查询与退出

PRJ01 双端项目管理已随 0.1.11 正式部署，原业务注册配置保持，未自动初始化总目录；实际来源与旧数据保护见[发布记录](validation/project-management-release.md)。初始化、IPC、运行／停止两种修改路径、新格式回退及请求结果核对见[项目管理操作与设计](project-management.md)。不得用新 CLI 在旧在用实例缺少项目管理入口时绕过实例直接写文件。

以下为明确的开发前台入口；正式托管解释器须来自独立 release：

```sh
.venv/bin/wx-clawbot doctor --config /absolute/path/to/private/config.json
.venv/bin/wx-clawbot serve --config /absolute/path/to/private/config.json
```

自定义状态根时所有命令均传同一个 `--state-dir`。默认只读发现既有 daemon；必要时 serve 可显式指定 `--socket /absolute/path/to/native-control.sock --codex-executable /absolute/path/to/native/codex --codex-home /absolute/path/to/codex-home`。原生可执行文件必须匹配既有 daemon，不能用依赖 GUI PATH／node 的包装脚本替代。

另一个普通 Shell：

```sh
.venv/bin/wx-clawbot status --state-dir /absolute/path/to/private/state
.venv/bin/wx-clawbot doctor --state-dir /absolute/path/to/private/state
.venv/bin/wx-clawbot stop --state-dir /absolute/path/to/private/state
.venv/bin/wx-clawbot status --state-dir /absolute/path/to/private/state
```

`stop_requested` 只是写入当前代次的退出请求；等待 `status` 为 stopped、消费者锁释放及原 job 不再 running，才启动新实例。HTTP 工作线程需等待有限超时排空。stop 不发送 Codex 中断、不杀终端；任务可能仍在原生运行。前台 Ctrl+C 也可退出，但不能将退出当作所有业务已结束。

| 状态 | 能说明什么／不能说明什么 |
| --- | --- |
| foreground_ready | 账本与微信入口准备好，不能证明目标可派发 |
| running／supervision | 准确进程及锁有效；不能替代 host／native／本人收件验证 |
| consumer_unverified | 有消费者但实例来源不足，不能假报健康 |
| host ready | iTerm2 连接可用；可见创建仍需准确握手 |
| native ready | 原生连接可用；每个新任务仍核验目标 |
| stopped | 桥接消费者空闲；原生任务可能继续 |

重启先恢复微信入口，再复验依赖和持久化选择；旧数字列表失效，旧同步／异步待答入口按恢复规则失效。原生换代或缺身份不能自动恢复选择，unknown 不重放。

## 日常选择与失败处理

`/projects` → `/sessions [关键词]` → `/focus <本次序号>` → 普通任务。`/sessions` 仅刷新列表，保留输入目标和观察订阅；退出输入目标使用 `/unfocus`，它不取消已接收任务。`/send` 单次派发不改焦点。`/cd` 无受管匹配时可见新建，`/new` 要有当前目录。独立 `/attach`／`/detach` 见[命令契约](command-contract-proposal.md)。

既有对话无需状态栏／标题 ID，也不要求当前窗口显示。发现范围是注册根和已知准确 cwd；子目录不递归，可通过合法 `/cd` 登记，但此命令也可能创建会话，不能当纯查询扫描器。未在目标 daemon 加载的 TUI 不可被桥接控制，不能仅凭底部 ID 或 doctor 协议通过认定归属。

电脑切到 B 不改微信已选 A；A 原生仍可核验就可继续，卸载或断连明确拒绝。不从存档恢复或新建替代会话。输入收到后固定原目标，切换不迁移旧任务。`/status <完整任务 ID>` 查看结果、占用和投递；原生中断不等于杀死全部系统子进程。

## iTerm2 退出、按需启动与恢复

- 后台只重连已运行 iTerm2，不反复拉起退出的应用。合法 `/cd`、`/new` 在需要宿主时可按需拉起；`/sessions`、普通文字、图片、帮助和状态不触发应用启动。已有准确原生对话可在宿主缺席时继续核验并派发。查询在原生未就绪时明确失败，保留原选择与原列表期限，不将空列表冒充完整核验。
- 宿主连接与原生连接各自管理代次；单纯 host 断连不使准确原生订阅失效。新任务和答案仍按各自身份要求复验。
- 宿主准备／发现总预算 25 秒，可见启动握手另有 120 秒预算。原生冷启动时在原 15 秒连接期限内，最多等待 5 秒无授权 UI 的传输就绪；换进程／取消／错误即结束，授权与创建不自动重试。
- 认证子进程单次 8 秒硬截止。系统权限提示需本人处理；超时不是 API 被禁用的证明，不绕授权或反复弹窗。未知创建先核对，不重发“再建一次”。
- 恢复滚屏不证明原进程或 native thread 继续。关闭窗口后原生可能仍加载，也可能卸载，以准确状态为准。

[HOST01](validation/host-lifecycle-recovery.md)和[真实冷启动](validation/iterm-cold-start-live.md)分别保存各版本证据；不要把旧版宿主强依赖用于当前后台选择。

## 故障定位

| 组件／症状 | 只读核对与下一步 |
| --- | --- |
| config | JSON、项目 root 真实解析、目录权限，不把凭据打印出来 |
| state／upgrade_required | 目录／文件权限、本人绑定、版本和消费者；看 migrate-state 计划，不删库 |
| agent_discovery／native unavailable | daemon、实际 server 版本、socket 归属与代次、Codex home；verified_schema 为 false 先查矩阵，不只扩白名单 |
| 会话不在列表／不能输入 | 注册 cwd、loaded、完整身份与能力；不要求重新显示 ID，不猜最近窗口 |
| host unavailable | iTerm2、API 和脚本权限；仅需可见创建时处理，无理由不重启其他应用 |
| channel_receive／channel_send | 网络、已确认本人绑定、登录及回复上下文；失效由本人扫码，不迁移他人凭据 |
| 任务 unknown／占用阻塞 | 看准确任务、原生终态与队列，按 REC01 核验；不重投输入或直接改库清锁 |
| queued 长期不动 | 原端核对是否暂停、准确队列／turn；不强制启动或重复提交，后续能力见 ROADMAP |
| 回执未收到 | 先分清执行终态、Outbox、发送尝试和 API accepted；没有本人证据不称已收件 |

托管日志只保留安全分类。native_unavailable 每 60 秒窗口最多 10 个不同签名明细，同签名合并为 suppressed_count；限频不是恢复证明，须核对 native ready。禁止用原始响应／完整异常正文绕过脱敏。不中断无关服务、不用 killall、不清空运行根。

## 图片运行与资源边界

当前媒体范围、容量、版本分层和附件生命周期见[图片指南](image-input.md)、[协议矩阵](protocol-baseline.md)及[账本](state-schema.md)。准备中只对未尝试原生提交且准确原目标通过核验者继续；已尝试者只读对账。下载或模型拒绝不去图重投，不自动换模型。同消息图文未作为手机能力交付。

原生帧、事件、分页和渲染均有边界，超限终止连接并保留未知，不能截断身份视图后继续派发。旧任务可严格只读核验结果，不因旧终端不在就清锁或复制历史。

## 只重试回执

先从 status 取得完整 event ID，默认只读查看：

```sh
.venv/bin/wx-clawbot retry-reply 'EXACT_EVENT_ID' --state-dir /absolute/path/to/private/state
```

确认对象、投递结果及权限并正常停止消费者后，才显式 `--apply`；unknown 可能已送达，必须另外接受重复风险并传 `--confirm-possible-duplicate`。每个事件最多三次尝试，命令只准备该回执，不立即发送、不执行 Agent；下次 Sender 用最新合法本人上下文发送。失败先定位网络／绑定／上下文，不以反复重试碰运气。

## 备份、账本升级与数据恢复

停止并核对唯一消费者，保存原 plist、配置、manifest、版本、任务／占用／unknown 及冻结 Outbox 逻辑摘要。敏感备份保持目录 0700、文件 0600，只在本人私有目录。SQLite 使用 `Connection.backup` 取得一致副本；不要只复制可能仍有 WAL 的主文件。下面只演示人工一致性备份，目标必须全新，不能覆盖已有备份：

```sh
.venv/bin/python - <<'PY'
from pathlib import Path
import os, sqlite3
from contextlib import closing
source = Path('/absolute/path/to/private/state/runtime.sqlite3').resolve(strict=True)
backup = Path('/absolute/path/to/private/backups/NEW-runtime.sqlite3')
fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
os.close(fd)
with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
    with closing(sqlite3.connect(backup)) as dst:
        src.backup(dst)
        assert dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not dst.execute('PRAGMA foreign_key_check').fetchall()
        print('schema', dst.execute('PRAGMA user_version').fetchone()[0])
PY
```

备份前核对消费者已停、私有父目录已存在且权限合规；失败保留证据，不把半成品称为有效备份。核对 application_id、user_version、绑定及所有旧表行数／摘要；不公开身份或正文。独立保存原配置／凭据／launch 登记等恢复材料，仅有 SQLite 副本不是完整配置恢复。

已有旧库先只读：

```sh
.venv/bin/wx-clawbot migrate-state --state-dir /absolute/path/to/private/state
```

只有明确迁移授权、消费者停止且对象／备份核对后才加 `--apply`。工具验证绑定、结构、完整性、同消费者锁并备份，再事务迁移到当前 schema；失败回滚、重复当前版本不再迁移。serve 不隐式升级。TGT02 的快照 version 2 不要求 schema 迁移。

恢复须区分：事务未提交保留原库；代码回退选择兼容当前 schema 的独立旧制品；数据恢复另行决定准确备份、丢失的新写入范围及授权。**已有新写入时不能用旧备份覆盖当前库**。先保留当前一致副本和诊断，再在隔离副本验证备份完整性、绑定、schema、行摘要和代码兼容，不把验证副本接到真实通道。旧代码不认识新 schema 就保持停止；数据恢复后仍须重新核验选择，unknown 不重放。不提供绕锁／强制降级 SQL。

保留期维护 `maintain-state` 默认只读；显式删除边界见账本及[安全说明](../SECURITY.md)，不能用清历史消除未知状态。

## 用户级 launchd 托管、日志与卸载

[模板](../config/launchd.example.plist)使用独立 release 的 Python、`-I -m wx_clawbot.managed` 和准确 manifest／config／state-dir。argv 保持数组和绝对路径，不能用开发路径补包；只安装／管理本项目 Label。`managed` 在同一进程调用 serve 并记录日志，重启策略属于 launchd。

先正常停止旧消费者并确认 job 不在运行，再核对 plist／准确路径。初次注册用 `launchctl bootstrap`；已有 job 主动停止后用 `launchctl kickstart`；**修改 ProgramArguments 后须 bootout／bootstrap，单独 kickstart 不证明读取新 plist**。

```sh
plutil -lint "$HOME/Library/LaunchAgents/local.wx-clawbot.plist"
launchctl print "gui/$(id -u)/local.wx-clawbot"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/local.wx-clawbot.plist"
```

上面分别是校验、查询、首次注册，不是每次全跑。已注册且停止后的恢复是 `launchctl kickstart "gui/$(id -u)/local.wx-clawbot"`。Label／plist 须确为本人部署的对象，系统输出含私人路径，不直接公开。

模板 RunAtLoad 登录启动，KeepAlive.SuccessfulExit=false 只在异常退出后限速重启，ThrottleInterval=30；正常 stop 退出 0 后保持停止，下次登录仍可启动。不管理 Codex／iTerm2，不修改电源策略。持久配置错误先停止／卸载 job 排障，不反复扫码。

日志 `<state-dir>/logs/bridge.jsonl`，0700／0600，单文件 1 MiB、三份备份；只保留已知状态、组件、安全异常分类，不保存正文／token／原始回溯。SIGKILL／断电可能只有 previous_exit_unobserved，不能捏造正常退出原因。status 的 supervision、消费者、实际 argv／包来源、host／native 和本人收件分别核对。

撤销托管只对本项目 `launchctl bootout "gui/$(id -u)/local.wx-clawbot"`，再确认消费者停止。bootout 不删除 plist，永久撤销登录项或删除数据须单独明确范围；不自动删除旧 release、凭据、备份或日志。历史监督测试见[进程恢复记录](validation/bridge-supervision.md)。

## ENG01：独立运行制品与开发隔离

正式目录 `<state-dir>/releases/<version>-<wheel摘要前12位>/` 内含独立 venv、wheel、lock 和 release.json。不能移动复制 venv 或原地更新在用目录。manifest 核对包文件、源码、wheel、lock、依赖、Python 和 schema；源码摘要不是 wheel 摘要。桥接自有渲染／媒体／探测／启动子进程核同一来源；外部 Codex 不冒充本项目包。

在开发 venv 准备固定构建后端，然后对全新项目 `.tmp` 路径先看计划，明确 apply 后构建；这些命令不启动服务：

```sh
.venv/bin/python -m pip install setuptools==80.9.0
.venv/bin/python scripts/build_release.py --output /absolute/path/to/project/.tmp/NEW-artifacts
.venv/bin/python scripts/build_release.py --output /absolute/path/to/project/.tmp/NEW-artifacts --apply
```

验收冻结的同一个 wheel 后，将其安装到全新私有 release，不重建另一制品：

```sh
.venv/bin/python scripts/build_release.py --artifacts /absolute/path/to/project/.tmp/NEW-artifacts --wheel-sha256 EXACT_WHEEL_SHA256 --output /absolute/path/to/private/state/releases/VERSION-DIGEST
.venv/bin/python scripts/build_release.py --artifacts /absolute/path/to/project/.tmp/NEW-artifacts --wheel-sha256 EXACT_WHEEL_SHA256 --output /absolute/path/to/private/state/releases/VERSION-DIGEST --apply
/absolute/path/to/private/state/releases/VERSION-DIGEST/.venv/bin/python -I -m wx_clawbot.release verify --manifest /absolute/path/to/private/state/releases/VERSION-DIGEST/release.json
```

发布／切换顺序：

1. 明确版本、代码基线、内容与发布授权，完成必要测试、文档／隐私检查、冻结 wheel／lock／manifest；准备兼容旧制品。源码修改、提交、推送和部署权限分别核对。
2. 活动任务／交互／sending 及关键回执核对完毕后，正常 stop 唯一消费者，等待退出／锁／原 job 停止，保存一致性备份和冻结摘要。
3. 仅对本项目 plist 生成准确差异，替换解释器、manifest 和必要 WorkingDirectory；原 config、state-dir、Label、PATH、日志／重启策略保留。schema 不兼容先完成独立授权的显式迁移。
4. plutil 校验；旧 job 确已停止后 bootout，保存核对后的 plist，bootstrap 同一 domain／Label 一次。不停止 Codex、iTerm2 或微信。
5. 核实际 argv／cwd、非 editable 包及父子 manifest、唯一消费者、schema、原任务／占用／unknown／冻结正文、路由和依赖；API accepted 与本人实收分列。不自动发测试消息。
6. 失败保持停止、保留当前库与诊断；仅恢复兼容当前 schema 的独立旧制品及原参数，不恢复指向已变化开发检出的旧 plist，不覆盖旧数据或重放任务。实际结果写验证记录和 ROADMAP。

历史版本不认识 manifest 参数时须使用其准确 argv 并独立核来源；旧版本首次发现和快照兼容要求以该版本证据为准，不能称回退后同样无需 ID。

## ENG01：本地检查、性能与真实原生交接

离线入口 `.venv/bin/python scripts/check.py`、按风险回归、合成负载与冻结制品检查见[测试指南](testing.md)。真实原生 prepare／run／cleanup 显式执行，要求本轮专用资源／授权，失败先 report、不删除 case 或重跑意图。当前 0.167.0 未开放异步专项入口，不能机械照搬旧 0.166.0 全阶段工具。

日常服务与测试使用独立账本／假发送端。原生中断后可能队列暂停，先核对再由本人决定原端继续或选择新对话，不重发未知任务。模型等待和授权等待不应占部署停服窗口。

## TGT02：无状态栏 ID 候选与切换

此标题保留历史链接。当前首次接入无需页脚／标题 ID，发布与本机证据见[0.1.8 记录](validation/native-session-release.md)，身份与旧快照见[身份契约](native-session-identity.md)。显示偏好由本人决定，程序不自动改全局配置。原操作卡完整历史见[整理前固定提交](https://github.com/benarchen/wx-clawbot/blob/8278de5645a57f2fc0348b746d59899bfe0bdadd/docs/operations.md)，当前切换使用上文 ENG01。

## AUD01：候选诊断与规则验收

保留原入口。故障分类已进入当前实现，排障见故障定位；规则实验与原生限制见[规则专题](project-rules.md)和[历史证据](validation/native-diagnostics-rules.md)。当次临时全局／模型／发送授权不能继承。

## iTerm2 冷启动连接

当前恢复流程见本页 iTerm2 章节；根因、首次修复及后续 0.167.0 真实复测分别见[调查](validation/iterm-cold-start-investigation.md)、[复测](validation/iterm-cold-start-live.md)。不再把“待安排冷启动”当成当前核心未验收。

默认普通 Shell 的数量问题是后续独立修复，候选通过 macOS AppKit 拉起应用，初始事件为 noop，仅给新进程传入 `-OpenNewWindowAtStartup NO`，再由 SDK 创建自有终端；参数退出即失效，不写持久偏好、不覆盖窗口恢复及后续 Dock 打开窗口选项。首轮仅 AppleScript launch 的失败、当前真实验证与部署状态见[本轮记录](validation/iterm-single-window.md)。不得关闭来源不明的普通 Shell 达到数量要求。真实复测先由本人保存并退出应用，显式验收入口使用独立非 editable manifest、两个临时项目及合成账本，不要求先切换日常服务或发微信消息。

## REC01 候选的准入诊断与受控切换

标题保留，命令为当前正式入口；原 schema 4→5 的部署过程仅见[历史证据](validation/admission-recovery.md)。默认只读：

```sh
.venv/bin/wx-clawbot admission-report --task-id 'EXACT_TASK_ID' --state-dir /absolute/path/to/private/state
.venv/bin/wx-clawbot admission-release --task-id 'EXACT_TASK_ID' --state-dir /absolute/path/to/private/state
```

自动核验先恢复可确认结果，再处理占用。持续等待 60 秒最多追加一次提示，不因超时解锁。少数人工处置须明确对象／理由、正常停消费者、重新取得报告摘要，然后：

```sh
.venv/bin/wx-clawbot admission-release --task-id 'EXACT_TASK_ID' --state-dir /absolute/path/to/private/state --apply --confirm-report 'EXACT_REPORT_DIGEST' --reason '已核对准确原生终态和队列'
```

apply 仍会连接受支持原生对象、核准确 thread／turn／client、完整提交／队列、revision 和审计；歧义或证据不足拒绝，无 force。释放不改 unknown，不执行输入，不发微信。禁止直接 SQL、清库、删项目配置或重建终端来清锁。

## PERF01 候选的独立验证与生产切换

原 schema 3→4 补丁、测量与失败路径见[PERF01](validation/performance-optimization.md)，当时部署见[分版本记录](validation/local-release.md)。补丁仅适用准确旧基线，不重复套入当前代码。当前制品及切换使用上文 ENG01，迁移使用账本现行入口。

## ASK01：异步答复与 schema 6

`/status <原任务 ID>` 区分 q 请求的 pending、accepted、observed、unknown、conflict；答案不产生新业务任务。门禁、格式和恢复以[异步契约](async-questions.md)及矩阵为准，不能套用同步暂停／首答语义。旧 schema 显式升级，已写入新数据不能回灌旧备份。

## 出站排版与冻结回执核对

规则见[排版专题](wechat-markdown.md)。核对原生正文、冻结发送正文、客户端显示和实际复制，不能凭复制按钮或 API accepted 判定字节正确。旧 Outbox 与尝试不重写；真人证据仅在专门安排中采集，不自动操作微信 UI。

## 上下文观察与定时验收

自然失效时间已获准后置，无固定 TTL 承诺；[W08 证据](validation/w08.md#2026-11-01-上下文收尾)保留接受与未触发记录。旧即时观察额度已用，不能重发。未来跨天预约须先验证持久计划、重启和到期／过期的至多一次语义，另有具体发送授权；当前不提供跨天调度产品功能。
