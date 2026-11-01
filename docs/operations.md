# 前台使用与运维

## 安装与准备

在仓库根目录按 [README](../README.md) 安装项目虚拟环境。Python 限定 3.14，依赖使用哈希锁；不需要全局 Python 包。iTerm2 保持打开，设置中启用 Python API；首次连接可能需要允许本项目 Python 脚本。此 API 可操作终端，应只授权信任的脚本。

在私有目录保存 `config.json`，按[配置模板](../config/config.example.json) 填写项目别名和真实绝对目录。默认运行目录为 `~/Library/Application Support/wx-clawbot/`，目录必须为本人所有的 `0700`，凭据、账本和实例记录为 `0600`。不要把真实配置放入仓库。扫码与本人绑定见[微信说明](wechat-protocol.md)；已有本项目本人绑定时直接复用，不读取其他项目凭据。

普通 Shell 中先检查 `codex app-server daemon version`；必须是已经运行的原生 daemon。该官方命令会显示本机路径，不要把完整输出公开。桥接只读发现并核验既有 daemon，不自行安装、重启或更新它。原生 CLI／daemon 版本范围及 Session ID 显示要求见[原生证据](native-session-evidence.md)和 [README](../README.md)。

## 启动、查询与退出

在新终端进入仓库根目录，替换私有配置占位路径：

```sh
.venv/bin/wx-clawbot doctor --config /absolute/path/to/private/config.json --iterm2
.venv/bin/wx-clawbot serve --config /absolute/path/to/private/config.json
```

`serve` 自动向 PATH 中的 Codex CLI 查询既有 daemon 的 socket 和原生可执行文件，再核验连接。GUI 包装脚本依赖 `node`，不能代替原生 Mach-O 可执行文件。若当前终端找不到 CLI，先修复该终端自己的 PATH；也可沿用 [README](../README.md) 的显式 `--socket`／`--codex-executable` 参数。`--codex-home` 默认为当前用户的 `.codex`，必须与连接的既有运行时相同。不会更换模型、覆盖配置或新建后台替代会话。

出现 `foreground_ready` 表示账本及微信入口已准备，宿主和原生依赖可以仍在恢复；不能据此认定会话可派发或任务执行成功。`capabilities` 另报 host／native 状态；host 为 ready 且 native 为 ready 后，新任务仍须逐次核验准确会话。stdout 只输出状态及错误分类，不输出消息正文、凭据或认证响应。直接运行 serve 不自动写日志文件，也不保证随启动终端或工具退出后继续存活；长期运行采用下文用户级托管。

另一个普通 Shell 中运行：

```sh
.venv/bin/wx-clawbot status
.venv/bin/wx-clawbot doctor --state-dir "$HOME/Library/Application Support/wx-clawbot"
.venv/bin/wx-clawbot stop
.venv/bin/wx-clawbot status
```

自定义运行目录时，以上命令与 `serve` 都传入同一个 `--state-dir`。`status` 只读显示实例、权限、依赖状态、任务／回执计数及最多 100 个待核对回执 ID，不读出任务正文、微信身份或回复上下文。`running` 表示实例记录的进程启动身份及消费者锁同时有效，不能替代 components 中的 host／native 状态；旧进程没有依赖记录时显示 unknown。`consumer_unverified` 表示消费者存在但没有可核验实例，例如旧入口，不等同服务健康。`stopped` 表示消费者锁空闲；任务可能仍在原生终端执行。

`stop` 只写入当前实例代次的退出请求，不发送进程信号、不停止 Codex。返回 `stop_requested` 后等待 `status` 成为 `stopped`；HTTP 工作线程可能仍在等待超时，不要立刻启动第二个消费者。未核验实例拒绝请求；旧入口在原前台按 Ctrl+C。Ctrl+C 也是正式前台入口的正常退出方式。异常退出遗留的旧代次不会停止新实例。

重启仍使用同一 `serve` 命令；先轮询微信，依赖后台恢复期间帮助、项目列表和状态可用，新任务未核验不接收。原生连接代次变化后旧审批失效；未知任务只核对原生记录，无法确认时保留 unknown，不重新执行。上次选择只有重新通过完整身份核验才恢复；不能核验时保持未选，旧列表编号失效。若启动时被原生弹窗遮住 Session ID，待终端恢复后用 `/sessions` 刷新，触发一次只读对账，再按新列表选择目标；仍不能核验的任务继续保持 unknown。

手动启动准备接入的 Codex 时，先在 Shell 中实际进入已注册项目目录，再运行 `codex`。仅使用 `codex --cd <项目目录>` 可能使 Codex 的工作根目录与进程真实 cwd 不同；当前发现先按进程 cwd 限定注册项目，会保守忽略该终端，不应通过读取未注册目录屏幕绕过。可在尚未发送任务的新终端退出 Codex，先执行 `cd <注册项目目录>` 后重新启动。受管可见启动器已有独立子进程 `os.chdir`，不改变桥接自身目录。

还须核对 TUI 是否确实加入桥接使用的 daemon；CLI 的版本命令与 doctor 协议检查不能证明某个终端属于该运行时。不同原生二进制可能启动独立 TUI，表现为底部有 Session ID，但该 ID 不在目标 daemon 的已加载列表中。此时保持未核验，不复制历史或另起后台任务；优先使用微信 `/cd`、`/new` 的受管可见启动，它使用既有 daemon 报告且已核验的原生可执行文件，再按完整身份与真实握手确认。

## iTerm2 退出、按需启动与恢复

- iTerm2 未启动时，后台只等待；有效的 `/sessions`、`/cd`、`/new` 可通过系统启动入口拉起一次。`/new` 仍要求先有当前目录，无效参数先拒绝。帮助、项目列表、状态及普通文字／图片不拉起应用。
- 宿主断连后，不必重启微信桥接。应用重新运行后自动获取新连接、刷新端点并核验原生身份；同一波命令共用连接／启动流程，额外选择请求返回忙碌，不积压到恢复后集中执行。
- 会话操作先告知处理中，宿主准备／发现阶段总预算 25 秒，失败清理另有边界；真实可见 Codex 启动保留 120 秒握手预算。进展与明确结果是不同回执，进展不代表创建或派发成功。
- 认证通过可终止子进程完成，单次 8 秒截止；超时不等于 API 被禁用。电脑端若有系统 Automation 或 iTerm2 授权提示，需要本人处理。处理后再发一个会话命令重试授权；后台暂停明确授权失败的重复认证，不改设置、不绕过授权。请求授权前及授权子进程超时后会进行禁用授权 UI、移除 cookie／key 的有界传输探测：服务无响应则按连接故障退避重连；服务仍可响应时继续等待本人核对授权。该探测不执行 API 操作，也不授予会话派发资格。
- 应用已打开、API 已连接、原生运行时就绪和会话已核验是不同状态。daemon 缺席时保持微信入口，后台只读发现现有受支持运行时；不会另建后台 Codex 来冒充原终端。
- iTerm2 的窗口恢复可能只保留滚屏。原进程／native thread 已消失时，普通消息被拒绝；需要本人通过新的 `/cd`、`/new` 请求进入可见会话，未知旧创建不自动重做。
- 单纯宿主断连不会撤销仍有效的准确原生任务／观察订阅；它们继续接收结果及已关联交互，但不能授予新任务派发资格。原生连接断开才使该连接的旧交互失效。
- 重连中未知任务不自动重放，原冻结目标不迁移到新窗口。命令列表须重新获取；状态中的 unknown 须结合原生记录核对，不通过清库消除。

实施和真实验收范围见 [HOST01 记录](validation/host-lifecycle-recovery.md)。应用整体退出／重启由本人安排，不能因只有一个专用测试窗口就忽略其他窗口受影响的可能性。

## 故障定位

错误只报告组件、异常类型和操作建议，不把异常中的响应正文直接输出。

| 组件／状态 | 核对方式 |
| --- | --- |
| config | 检查 JSON 字段、项目目录与可访问性 |
| state／upgrade_required | 检查 `0700`／`0600`、本人绑定、单消费者及[显式升级计划](state-schema.md)，不删除库重新开始 |
| agent_discovery／agent | 核对既有 daemon、受支持版本、同一 Codex home、当前完整 Session ID；`doctor` 的 `runtime.verified_schema: false` 表示该服务端版本尚未核验，须先检查[协议基线](protocol-baseline.md)，不能仅凭 CLI 版本判断；未知任务不重新发送 |
| host | 打开 iTerm2，核对 Python API 和该脚本的授权，执行 `doctor --iterm2` |
| channel_receive／channel_send | 核对网络、本人绑定与登录状态；登录过期需要本人扫码，不能读取其他项目凭据或静默替换连接 |
| receive_disconnected | 网络轮询会有限退避重连，游标保留；不代表已丢消息或应再次提交任务 |
| maintenance／lifecycle | 核对账本／原生连接或实例记录权限；必要时在原前台 Ctrl+C 后重新诊断 |

不使用 `killall`／宽泛进程名停服务，不清空运行目录来绕过锁或升级错误。现有 hook 告警属于原环境，桥接不修改它来掩盖失败。

## 图片运行与资源边界

图片版本启用前用 migrate-state 查看计划，明确备份和对象，再停止前台执行显式升级；serve 不自动迁移。使用及错误分类见 [图片指南](image-input.md)，附件一致性与回收见 [账本说明](state-schema.md)。启用前后核对实际 schema、原配置、原生身份及未决任务，不清空状态重新开始。

图片准备有两个有界工作槽位，取消调用者不会在工作仍存活时提前释放额度。原生接收帧最多 16 MiB，事件同时受 256 条和 32 MiB 限制，WebSocket 接收高水位两个帧；出站 RPC 仍限 1 MiB。队列单项分页、最多核对 100 项，只保留身份，不积压内联图片；启动复核只读第一条握手 turn。超限时停止连接并保留未知状态，不重放。

运行时换代可能改变稳定会话编号。旧任务可在当前同项目、同目录、同 native thread 的唯一终端完整复验后，只读对账准确 client 的唯一原生终态；这不改写旧任务目标，不恢复旧路由，不创建订阅或重新派发。无法唯一匹配、当前身份不明、原生仍执行或缺少准确 client 时继续保持 unknown。图片准备完成但受仓库保护阻塞时，回执说明等待准入原因；本地 received 的图片尚未原生提交，恢复后保持原 client 和目标继续一次处理。

旧桌面任务的原生轮次若出现输入合并或 client 冲突，恢复保留 unknown 并提示核对，不把它误归为某条独立任务，也不阻止整个前台启动。配置移除旧项目不代表释放其未结束任务的仓库保护；缺少可核验仓库身份时保守等待。

## 只重试回执

先用 `status` 找到具体事件 ID，再只读查看计划：

```sh
.venv/bin/wx-clawbot retry-reply '<event-id>'
```

核对该回执属于预期结果，再停止桥接。已明确拒绝的投递可显式准备下一次：

```sh
.venv/bin/wx-clawbot retry-reply '<event-id>' --apply
```

unknown 可能已经送达手机；只有明确接受可能重复时才额外传入 `--confirm-possible-duplicate`。每个事件最多 3 次投递尝试。命令只准备单条出站记录，不建立 Agent 连接、不恢复／修改其他任务状态、不立即发消息；下次启动桥接后 Sender 使用最新有效本人回复上下文发送。该操作不意味着重新执行任务。发送失败必须先定位网络／登录／上下文，不反复重试以试运气。

保留期检查、显式清理及独立备份见[账本说明](state-schema.md)。不自动清理真实账本，不触碰 Codex 历史、其他服务或业务项目文件。

## 用户级 launchd 托管、日志与卸载

[用户级模板](../config/launchd.example.plist) 使用 `.venv/bin/python -m wx_clawbot.managed --config <原配置> --state-dir <原运行目录>`。仅在本人明确授权部署后，将占位绝对路径替换并保存至本人 `~/Library/LaunchAgents/local.wx-clawbot.plist`，不覆盖其他来源文件。保持 argv 数组，不拼接 Shell，不放入凭据。PATH 须能找到同一 Codex CLI；默认由既有只读发现机制核验运行时，沿用该用户的 Codex home，不固定一次性的 socket。

模板的 `RunAtLoad=true` 使用户登录后启动；`KeepAlive.SuccessfulExit=false` 只在异常退出后重新启动，`ThrottleInterval=30` 限制快速失败循环。`stop` 的正常退出码为 0，主动停止后保持停止，恢复需明确执行 kickstart；下次登录仍按已安装的启动项启动。macOS 注销、睡眠、关机或网络中断时不承诺在线，不修改电源设置，也不自动启动 Codex daemon。非零的持久配置／认证错误会继续限速失败，应先 stop／bootout 后定位，不反复扫码或改库。

托管入口复用原 serve 和账本，单独持有 `managed.lock`，既有消费者锁继续生效。`managed.json` 保存完整进程身份、源码摘要、启动及可观察的退出状态；`status` 的 `supervision` 字段只有在完整进程身份与有效前台相同时才报告 running。记录为 running 而进程已消失时显示 `previous_exit_unobserved`，不把未知退出误报为正常停止或捏造具体原因。

托管日志位于私有运行目录的 `logs/bridge.jsonl`，目录为 `0700`、文件为 `0600`，单文件最多 1 MiB，最多 3 份轮转备份。只保留已知状态、组件和异常类型；任意 stdout、原始 stderr／回溯、消息正文、账号、token、上下文均不入日志。SIGTERM 有明确记录；SIGKILL／断电无法由进程自己记下退出码，下一次启动会标记前次退出未观察到，再结合 launchctl 的退出状态判断。Python 导入或日志初始化前失败也可能没有应用日志，应检查 launchctl。stdout／stderr 指向 `/dev/null`，避免另增无界文件。

先停止并核对旧消费者退出，再校验及注册，避免并行两个入口：

```sh
.venv/bin/wx-clawbot stop
.venv/bin/wx-clawbot status
plutil -lint "$HOME/Library/LaunchAgents/local.wx-clawbot.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/local.wx-clawbot.plist"
.venv/bin/wx-clawbot status
```

已注册但主动停止后恢复：`launchctl kickstart "gui/$(id -u)/local.wx-clawbot"`。只读查看托管状态：`launchctl print "gui/$(id -u)/local.wx-clawbot"`；该系统输出可能含本机路径，不直接公开。`running` 与 host／native ready 及微信本人收件分别核验，不能只用 launchctl 的 PID 证明通道健康。

卸载／回退时仅对本人部署的 Label 执行 `launchctl bootout "gui/$(id -u)/local.wx-clawbot"`，再确认消费者停止，才能恢复原前台 serve。bootout 本身不删除 plist，下次登录会再次加载；永久撤销登录启动还须按本人明确授权移除或移出该文件。保留账本、凭据和日志，不操作其他 Label、Codex 或 iTerm2。真实安装与验证结论见[进程恢复记录](validation/bridge-supervision.md)。

当前前台方式卸载时，先停止并核对桥接已退出；按需要保留私有运行目录以供恢复。删除凭据、账本、项目或虚拟环境均由本人另行明确选择，不自动删除；Codex 和 iTerm2 不需要卸载，也不应停止其会话。


## 出站排版与冻结回执核对

排版模块的规则、自测和客户端边界见[排版说明](wechat-markdown.md)，实际加载与验收记录见[MD01 证据](validation/wechat-markdown.md)。分开核对接口 accepted、本人实际显示和实际复制；截图中的代码复制按钮不等于字节正确。用户提供的截屏／照片只留本地，公开记录保存摘要；不自动操作、登录或重试微信客户端。

正常重载前确认没有活跃任务和未决关键回执，保存任务／旧 outbox／当前配置摘要，按本页已有 stop 与 kickstart 流程仅恢复既有桥接 Label。核对旧进程正常退出、消费者释放、新进程源码摘要与预期一致以及 host／native 状态，再请本人验收新生成的回执。既有 outbox、摘要和投递尝试不随排版升级重写；未知任务不重放。若全局配置较更早快照发生其他变化，记录并保护重载前的当前值，不回滚用户现状。

本地 stopped／锁释放与 launchd 的旧任务退出可存在短暂先后差异：启动前另用 `launchctl print gui/$(id -u)/local.wx-clawbot` 确认顶层 state 为 not running，再执行既有 kickstart。启动调用成功不等于新进程已加载；须核对新管理进程／源码摘要。若没有新启动记录，先只读核对 launchd 与锁状态，不重复执行停止或使用强制重启参数。

排版缺陷先对照冻结发送原文与本人看到的内容，不无证据归因于任务执行、客户端风控或某个内部渲染阶段。根据明确差异补源形态回归，完整自测后再做少量具体授权的小样；未通过的核心格式保持未验收。

## 上下文观察与定时验收

自然失效时间不作为固定期限承诺。W08 本人已于 2026-11-01 同意将触发时间后置，保留必要故障／恢复验证；[实际证据](validation/w08.md#2026-11-01-上下文收尾)分别记录 API 接受、本人收件、确定性故障和真实自然失效，不能混用。

`tests/integration/w08_context_recheck.py` 是显式即时验收器，提供 prepare／report／observe／recover，必须使用新的项目 `.tmp` 私有目录和具体本人发送授权。prepare 冻结原记录／凭据摘要，30 分钟内 observe 最多一次；未达到七天不启动等待，过时不补发，有意图或结果不重试。recover 仅在真实非账号拒绝后使用本人新入站产生的不同上下文，最多一次。它不启动原生任务，不修改生产账本，不复用旧预约授权；本轮额度已经使用，不能重新执行 observe。

未来若安排跨天预约，须先具备持久化计划、重启后恢复和到期／过期核对，并验证重启／晚醒／发送意图不确定时的至多一次语义；临时 sleep 进程和旧存活回执不能作持续执行保障。不得为了补过时任务自行装服务、修改系统配置或发送。当前不新增跨天预约、托管服务或自动重登。

## PERF01 候选的独立验证与生产切换

[PERF01 交付](validation/performance-optimization.md)提供完整补丁、前后文件摘要及原始测量数据。原候选先隔离验证，后经本人明确授权整合为 `0.1.0`，已在本机备份升级并切换；实际结果见[正式记录](validation/local-release.md)。原始补丁仅用于准确基线的独立重建，不能重复应用到已升级工作区。以下操作卡保留受控切换方法，不授权重复迁移或重启。

先在独立检出核对基线提交及 manifest：已有文件的完整 SHA-256 必须匹配，新增文件须不存在，补丁摘要须正确；再执行 `git apply --unidiff-zero --check`，不得覆盖其他工作。独立检出应用完整补丁后，用项目虚拟环境和原精确依赖锁运行完整回归、编译、`pip check` 及离线 performance 的 baseline／candidate／compare；flow、migration、checks 是单独入口，native 冒烟必须另行冻结本轮专用资源。原始计时、同文摘要、上界和失败退出都要核对。正式入口均随补丁交付，结果只能写入项目 `.tmp`。

大结果子进程以当前 `sys.executable -I -m wx_clawbot.render_worker` 启动。部署解释器必须在隔离模式下也能加载完整候选包；不能只设 `PYTHONPATH`，不能让父进程使用候选而子进程加载旧包。

生产操作卡：

1. 核对将运行的完整版本／解释器／源码摘要、真实目录归属和只读 `migrate-state` 计划。只输出计数和摘要，不公开身份或正文；预检不能用会执行恢复写入的 `RuntimeState.open`。
2. 核对活动任务和未决关键回执，按授权等待或处理；正常停止唯一桥接消费者，确认锁释放且既有 launchd Label 顶层为 not running。不操作 Codex、iTerm2 或微信客户端，不同时启动前台和托管入口。
3. 保存私有配置／账本摘要，用候选解释器显式执行原有 `migrate-state --state-dir /absolute/path/to/private/state --apply`。工具必须成功取得同一消费者锁、验证绑定与版本、生成可核对备份，之后在事务内执行 3→4 三索引及 ANALYZE。1／2 按已有链路继续到 4。拒绝、超时或失败时停止，不绕锁或对运行库直接执行 DDL。
4. 核对版本 4、准确索引、完整性／外键、业务行及冻结正文摘要与备份一致。候选安装／加载目标正确后，仅对既有 Label 启动一次，确认新管理进程／消费者唯一、预期源码、bridge／host／native 健康。启动回执不代替实际加载核对；不自动发微信测试消息或重放 unknown。
5. 失败时先区分事务未提交、已升级未写入、已产生新写入。未提交应保持原库；其他情况保留原库、备份和私有日志，停止切换。代码回退与数据回退分别决策，恢复数据须有准确授权。不可用只识别 3 的旧代码直接打开 4，更不能用旧备份覆盖已有新任务。

本轮已完成合成 10 万任务＋10 万回执的升级／备份／重复执行，故障回滚与活消费者拒绝由离线测试覆盖。真实部署与迁移必须在后续记录实际结果。
