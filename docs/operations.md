# 前台使用与运维

## AUD01：候选诊断与规则验收

AUD01 已完成工程验收，规则责任采用本人明确接受的原生限制方案；日志修复已按后续授权切换到本机独立 0.1.4，见[本机切换](validation/aud01-local-deployment.md)。[交付记录](validation/native-diagnostics-rules.md) 和[机器摘要](validation/native-diagnostics-rules.json)记录准确验证范围。工程验收候选沿用 0.1.3／schema 6，后续 Git 交付版本为 0.1.4／schema 6，见[发布记录](validation/aud01-publication.md)；不同制品须核对各自 wheel／源码摘要，不能只凭版本字符串认定加载一致。

候选托管日志接纳 native_unavailable，保留安全 error_type 及有界 error_types／classification_truncated。单调时钟每 60 秒窗口最多 10 条不同签名的故障明细，同签名只记首次；native ready 或后续窗口出现事件时，以 native_failures_suppressed／suppressed_count 汇总。进程异常退出前尚未汇总的内存计数不保证保留。过滤、容量、权限和轮转保持，不应为诊断放开原始异常输出。

原生失败先核对安全类型、组件、版本和端点；异常组可看有界叶子分类，classification_truncated 表示非完整异常树。限频不代表恢复，需看 native ready 或准确健康状态；未知任务先对账，不重发。

规则实验先由本人正常打开 iTerm2 并处理必要脚本授权；不重启 daemon、退出用户窗口或自动拉起应用。以下在候选检出执行，路径占位值替换为本次准确且尚无 case.json 的项目临时目录：

```sh
.venv/bin/python tests/integration/rules_native.py plan --case-dir /absolute/path/to/project/.tmp/aud01-owned
.venv/bin/python tests/integration/rules_native.py prepare --case-dir /absolute/path/to/project/.tmp/aud01-owned --confirm-dedicated
.venv/bin/python tests/integration/rules_native.py run --case-dir /absolute/path/to/project/.tmp/aud01-owned --confirm-dedicated
.venv/bin/python tests/integration/rules_native.py boundaries --case-dir /absolute/path/to/project/.tmp/aud01-owned --confirm-dedicated
.venv/bin/python tests/integration/rules_native.py report --case-dir /absolute/path/to/project/.tmp/aud01-owned --confirm-dedicated
.venv/bin/python tests/integration/rules_native.py cleanup --case-dir /absolute/path/to/project/.tmp/aud01-owned --confirm-dedicated
```

工具仅接受已核对的 0.166.0，一个自有窗口、一个标签及临时项目。原始输出／身份留私有证据；run／boundaries 均不重放既有执行意图，失败先查准确结果；已有 case 不机械再次 prepare，活动任务或身份不符不自动 cleanup。原生三轮标记及六轮边界已实际完成，结果和限制见交付记录；这不代表已提供规则热更新。

正式验收使用已冻结候选的解释器，并向父进程显式提供该候选的 WX_CLAWBOT_RELEASE_MANIFEST；prepare／run／cleanup 均沿用同一对象。例如替换准确路径后执行：

```sh
/usr/bin/env WX_CLAWBOT_RELEASE_MANIFEST=/absolute/path/to/candidate/release.json /absolute/path/to/candidate/.venv/bin/python -I tests/integration/rules_native.py prepare --case-dir /absolute/path/to/project/.tmp/aud01-frozen-owned --confirm-dedicated
```

测试子进程显式继承已验证父进程的 manifest，避免 GUI 会话残留另一个制品标识。明确开发调用无 manifest 时只清除本次测试子进程的残留值，不修改全局环境；这不授予正式制品身份。启动失败先看私有 startup-error，不通过删除 manifest 或放宽校验继续。

真实连接故障回归使用同一候选解释器／manifest，将 action 改为 diagnostics、case-dir 指向全新项目临时目录。它建立独立空测试账本，只关闭自身的原生 WebSocket，并核对故障日志及新代次恢复；不创建终端、不提交任务、不连接微信。已有 runtime.sqlite3／报告会拒绝，不复用生产状态。本轮已真实通过 ConnectionLost 入日志及第二代连接 ready。

早期两个失败启动均经准确端点缺席、无 boot 和完整原生列表核对后归档，未重放；最终冻结候选已完成九轮规则实验并安全清理。以后重测使用新意图；已有意图先 report 并核对准确终端／队列，保留 unknown。规则边界见[规则说明](project-rules.md)，没有通用 reload 命令。

工程完成口径为候选修复及规则契约交付；本人后续明确授权的 0.1.4 本机切换现已完成，实际结果见上述本机记录。以后再次切换仍须准确授权。冻结 wheel、锁及 manifest 后，按下文 ENG01 操作卡安装到新 release 目录；沿用 schema 6，无迁移。正常停止、核对消费者与发送、变更本项目准确运行路径、启动一次并复核父子 manifest／单消费者／健康／旧数据。失败时恢复兼容 schema 6 的原独立制品和托管参数，保留当前账本，不覆盖备份、不重放任务、不重启 Codex／iTerm2。

## iTerm2 冷启动连接

0.1.5 在按需命令尚未建立宿主连接时，先用禁用授权 UI 的传输探测有界等待当前准确进程的 API；最多 5 秒，包含在原 15 秒连接期限内。进程更换、取消及非传输错误立即结束；后台不自动拉起应用，授权和可见会话创建不自动重试，未知操作不重放。准确交付状态、离线结果及待安排的真实冷启动验收见[调查与修复记录](validation/iterm-cold-start-investigation.md)。本机已按授权加载继承本修复并支持 0.167.0 核心协议的独立 0.1.6，准确发布与切换证据见[交付记录](validation/codex-0167-release.md)；仍须通过 manifest 核对实际制品。

## 安装与准备

在仓库根目录按 [README](../README.md) 安装项目虚拟环境。Python 限定 3.14，依赖使用哈希锁；不需要全局 Python 包。iTerm2 保持打开，设置中启用 Python API；首次连接可能需要允许本项目 Python 脚本。此 API 可操作终端，应只授权信任的脚本。

在私有目录保存 `config.json`，按[配置模板](../config/config.example.json) 填写项目别名和真实绝对目录。默认运行目录为 `~/Library/Application Support/wx-clawbot/`，目录必须为本人所有的 `0700`，凭据、账本和实例记录为 `0600`。不要把真实配置放入仓库。扫码与本人绑定见[微信说明](wechat-protocol.md)；已有本项目本人绑定时直接复用，不读取其他项目凭据。

普通 Shell 中先检查 `codex app-server daemon version`；必须是已经运行的原生 daemon。该官方命令会显示本机路径，不要把完整输出公开。桥接只读发现并核验既有 daemon，不自行安装、重启或更新它。原生 CLI／daemon 版本范围及首次发现的 Thread ID 显示要求见[原生证据](native-session-evidence.md)和 [README](../README.md)。

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

[用户级模板](../config/launchd.example.plist) 使用独立版本目录的 `.venv/bin/python -I -m wx_clawbot.managed`，显式传入 release manifest、原配置和原运行目录；制品准备及切换见下方 ENG01 操作卡。仅在本人明确授权部署后替换占位绝对路径并保存至本人 `~/Library/LaunchAgents/local.wx-clawbot.plist`，不覆盖其他来源文件。保持 argv 数组，不拼接 Shell，不放入凭据。PATH 须能找到同一 Codex CLI；默认由既有只读发现机制核验运行时，沿用该用户的 Codex home，不固定一次性的 socket。旧 editable 安装是历史入口，不能作为新增生产版本的默认布局。

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

## REC01 候选的准入诊断与受控切换

本节描述 `0.1.1`／schema 5 的正式入口；本机已按本节操作卡完成切换，实际证据见[REC01 记录](validation/admission-recovery.md)。任务结果与占用分别查看；unknown 可以保留而占用已释放，二者不可混淆。默认先自动核验：恢复可确认结果，随后核验剩余占用。正常任务无需本人定期清锁。

微信 `/status <任务ID>` 显示占用状态、阻塞者、核验时间和未解除原因。收到等待回执只代表 received，尚未提交；持续 60 秒最多追加一次提示，不按期限解锁。`/stop <任务ID>` 可以撤销 received。`/sessions` 刷新仍可按严格身份和唯一关联核对结果，每次附带至多 20 条未知历史的分页，不重跑任务。

本地诊断默认只读，不连接原生、不发微信：

```sh
.venv/bin/wx-clawbot admission-report --task-id <task-id>
.venv/bin/wx-clawbot admission-release --task-id <task-id>
```

少数人工处置须先明确准确对象与理由、正常停止本项目消费者并核对锁已释放，再重新生成报告，使用报告中的确认摘要：

```sh
.venv/bin/wx-clawbot admission-release --task-id <task-id> \
  --apply --confirm-report <report-digest> --reason '已核对准确原生终态和队列'
```

工具仍会建立受支持的只读原生连接、复核原 thread／turn／client、完整空队列和报告 revision；有在途／执行／排队／身份歧义、报告变化或无证据时拒绝，不能 force。重复已成功操作幂等；不把 unknown 写成完成，也不执行旧输入。不能用直接 SQL、清库、删除旧项目配置或重建终端替代处置。

本机切换操作卡：

1. 冻结当前源码／包摘要、schema、任务及 outbox 等原业务表逻辑摘要、配置与现有 Label；核对活动任务及当前 received 的冻结目标。升级后该 received 可能按原意图执行，须属于本人已提交的有效请求。
2. 验收候选完整回归、真实原生、负载、查询、wheel 安装与隔离模式子进程，准备准确变更清单、备份和恢复边界；不边开发边改日常源码。
3. 按已授权清单正常 stop，等待旧进程退出和同一消费者锁释放；不强杀，不停止 Codex／iTerm2，不安装第二个托管 Label。
4. 在维护锁规则下，使用冻结候选显式 `migrate-state --apply` 完成 4→5；核验私有备份可读、旧表全行逻辑摘要及冻结内容未变、新结构／索引／完整性／外键正确。旧库不因 serve 自动升级。
5. 在停止窗口精确同步已验收源码和项目内安装，保持原配置、绑定、托管 argv、全局设置与模型。父包和 `python -I` 子进程均须实际加载完整 `0.1.1`，不能只用 PYTHONPATH 伪装生产加载。
6. 仅启动原 Label，核对唯一消费者、源码摘要、schema 5、host／native ready；自动恢复按原目标、client、任务意图至多一次推进。核对历史 unknown 状态与占用审计、当前原任务唯一原生终态及冻结投递结果，不额外发送测试消息。
7. 同步真实交付记录和 ROADMAP，保留备份和所有旧冻结回执；API accepted 与本人实际收件分别报告。

失败恢复：迁移事务失败保留 schema 4 并核对原版可运行；迁移已到 5 时不能直接用只支持 4 的旧程序。优先修复候选加载，保留库和备份；已产生新写入时禁止覆盖旧备份，不自动降级或回放。需要数据恢复时单列具体方案及授权，不把“恢复服务”作为覆盖新数据的理由。

## ASK01：异步答复与 schema 6

`/status <原任务 ID>` 显示 q 请求、状态和本地期限。accepted 只表示原生接收补充；observed 只表示准确输入可见；unknown 不自动重试，conflict 表示已观察到跨端竞争。旧轮次结束后的答案拒绝，不会自动新建任务；必须审批的动作仍走同步请求。详见[使用及边界](async-questions.md)。

旧库须先正常停止本项目唯一消费者，用 `migrate-state` 只读核对，再明确执行 `migrate-state --apply`；支持旧版本到 6，验证私有备份及旧业务／冻结回执。已有新版本写入后不直接覆盖旧备份，也不让 0.1.1 读 schema 6。恢复应保留现状并使用兼容 schema 6 的代码；不能通过清库解决。

本机 ASK01 已按前述 stop／kickstart 路径一次恢复原 Label，未改 plist／凭据／全局配置，不重启 Codex 或 iTerm2。自动原生测试使用专用可核验会话，输出原始 ID／答案只存私有证据；额外微信验收须有具体条数与内容授权。实际加载与手机状态见[本机记录](validation/local-release.md)和 ROADMAP。

## ENG01：独立运行制品与开发隔离

开发检出与生产版本分别安装。正式布局为 `<state-dir>/releases/<version>-<wheel摘要前12位>/`，内含 `.venv/`、固定 wheel、`requirements.lock` 和 `release.json`；解释器与所有新子进程从该版本环境加载。私有状态根、账本、凭据和原 Label 保持；不把虚拟环境复制到新位置，也不原地覆盖正在运行的版本目录。

manifest 分别记录 wheel SHA-256、锁摘要、项目包文件摘要、源码树摘要、依赖版本、Python 和 schema。源码树摘要与 wheel 压缩文件摘要不是同一对象。托管入口显式 `--release-manifest`，在连接服务前验证；渲染、图片、宿主探测与可见启动子进程继承准确 manifest，并使用隔离导入。开发前台仍支持不带 manifest 的明确启动，这不代表它具备正式制品隔离。

先在开发项目虚拟环境中安装原固定构建后端 `setuptools==80.9.0`，不要全局安装；准备全新且父目录已存在的项目临时输出路径。以下绝对路径均须替换为本次准确对象：

```sh
.venv/bin/python -m pip install setuptools==80.9.0
.venv/bin/python scripts/build_release.py --output /absolute/path/to/project/.tmp/eng01-artifacts
.venv/bin/python scripts/build_release.py --output /absolute/path/to/project/.tmp/eng01-artifacts --apply
```

默认只读计划；apply 构建源码包和 wheel，再按现有哈希锁建立全新环境、非 editable 安装并验证。不连接微信／原生运行时，不启动服务。目录已存在就拒绝，失败目录作为本次证据保留，核对后另用新路径；不能机械覆盖或继续一个未知构建。构建进程默认固定 `SOURCE_DATE_EPOCH` 以稳定 wheel 时间戳，不调整系统时钟。

审核测试通过的 frozen wheel、lock、manifest 及准确摘要后，在私有 releases 父目录准备正式安装，沿用同一个 wheel，不重新构建一份不同制品：

```sh
.venv/bin/python scripts/build_release.py --artifacts /absolute/path/to/project/.tmp/eng01-artifacts --wheel-sha256 EXACT_WHEEL_SHA256 --output /absolute/path/to/private/state/releases/VERSION-DIGEST
.venv/bin/python scripts/build_release.py --artifacts /absolute/path/to/project/.tmp/eng01-artifacts --wheel-sha256 EXACT_WHEEL_SHA256 --output /absolute/path/to/private/state/releases/VERSION-DIGEST --apply
/absolute/path/to/private/state/releases/VERSION-DIGEST/.venv/bin/python -I -m wx_clawbot.release verify --manifest /absolute/path/to/private/state/releases/VERSION-DIGEST/release.json
```

VERSION-DIGEST 必须是 manifest 版本加短 wheel 摘要；父目录权限 0700、记录文件 0600。只准备环境不等于切换运行版本。任何真实写入须在当次授权覆盖的目录执行，不由此命令触碰其他项目或 Label。

切换操作卡按以下顺序执行：

1. 核对原 Label／进程、consumer、schema、完整活动占用、待答交互和发送状态。没有关键执行或 sending 后，用原 `stop` 正常退出并确认消费者锁释放；不强停正在发送／执行的任务，不杀 Codex／iTerm2。
2. 在停止状态保存私有账本一致性备份、原 plist／配置摘要、已冻结回执行及 unknown 证据；校验新包支持当前 schema。ENG01 保持 schema 6，无隐式迁移。已升级 schema 的恢复也不能覆盖回旧备份。
3. 根据原 plist 生成准确差异，只替换本项目的解释器、隔离导入参数、manifest 及必要 WorkingDirectory；配置、状态根、PATH、Label、KeepAlive、节流、日志策略保持。先 `plutil -lint`，审核原件备份与差异，不复制模板覆盖用户其他设置。
4. 原消费者已正常退出后，仅 `launchctl bootout` 本项目 service target，替换经过核对的本项目 plist，再 `launchctl bootstrap` 原 gui domain。修改 ProgramArguments 后必须重新载入 job，单独 kickstart 不能证明已读取新 plist。
5. 独立核对实际进程 argv、消费者锁、supervision、包及父子摘要、schema、旧行保护与 component 状态。host 未运行与 bridge 失败分开；没有授权不拉起原应用，不将 API accepted 写成手机实收。
6. 新启动失败时保持停止，保留当前账本与故障证据；只恢复兼容当前 schema 的已核验代码及原配置。不能用回滚代码为由恢复旧数据、清 unknown 或重放任务。未完成的切换保留未完成状态。

旧版本目录只在确认不再加载、无相关子进程且保留策略／删除授权明确后清理；不自动删除旧版本、私有备份或整个 `.tmp`。

## ENG01：本地检查、性能与真实原生交接

基础入口 `.venv/bin/python scripts/check.py` 不安装依赖、不访问微信、不产生原生模型任务、不维护生产数据；结果保存在本项目 `.tmp/check/`。它执行非零且无跳过的 unittest、编译、pip check、Git 差异及文档一致性检查。没有对应 Git 检出时单独标记 diff 不适用，不把它写成已核验差异。失败步骤返回非零并保留摘要和日志。

性能入口 `tests/integration/engineering_performance.py measure --output <本项目.tmp内的新JSON>` 使用合成原生分页、私有合成 SQLite 和实际渲染；`load` 默认至少 120 秒，路径为入站校验／游标与 Inbox、controller、Outbox、Sender 和假发送端，统计完整本地处理时延，零真实微信。输出保留原始样本与准确源码摘要，基线／候选交替执行，不能在并发跑其他 CPU 压测时比较。原生／外部网络耗时不属于该基准 SLA；门槛和矩阵见 [ENG01 清单](../goals/20261103-2356-engineering-hardening.md)。

`compare` 要求明确的 `--baseline-python` 与 `--candidate-python`，候选 frozen 环境另传 `--release-manifest`；先丢弃一组预热，再完整交替执行七组。两侧父／隔离子进程源码摘要必须相同。微基准另在各进程内预热，历史查询保留 100 次、小渲染保留 7 次样本；冷启动另列，失败不参与提速百分比，不删慢样本。

冻结制品可用 `tests/integration/engineering_release.py --release <准确版本目录> --output <本项目.tmp内的新目录>` 核对开发路径干扰、渲染子进程、错误 manifest 拒绝、单消费者、SIGTERM 和兼容恢复后的合成账本行保持。此入口只在自己新建的合成状态根执行；它不操作 launchd 或实际生产数据，不能替代后续真实服务切换验证。

真实原生验收与基础检查分开，先确认本轮专用资源及测试任务范围；以下需要受支持运行时和专用宿主，不得放入默认检查或 CI：

```sh
.venv/bin/python tests/integration/engineering_native.py prepare --case-dir /absolute/path/to/project/.tmp/eng01-native --confirm-dedicated
.venv/bin/python tests/integration/engineering_native.py report --case-dir /absolute/path/to/project/.tmp/eng01-native
.venv/bin/python tests/integration/engineering_native.py run --case-dir /absolute/path/to/project/.tmp/eng01-native --confirm-dedicated
.venv/bin/python tests/integration/engineering_native.py cleanup --case-dir /absolute/path/to/project/.tmp/eng01-native --confirm-dedicated
```

prepare 登记一窗口、至多两个自有标签，调用正式 `admission_native.py` 准备流程；run 先准确核验映射，依次调用 `performance_native.py` 的同步交互／结果、`async_questions_native.py` 的异步补充、`admission_native.py` 的结果／占用恢复，最后在独立合成身份下调用控制小样验证排队取消／运行中断，分别保存原始证据。所有交付发送使用假通道；测试的准确原生输入与答案只在所登记自有终端执行。临时 Plan 设置只用于自有线程并恢复，不能修改全局设置。四个阶段都通过后才允许 cleanup，逐一核验进程／原 thread／idle／空队列再关闭；用户终端保持。

工作流在每次外部动作前先记录意图；非 ready 状态拒绝再次 run，cleanup 也不能越过未知结果。失败时使用 report 和子步骤日志只读定位，先核对准确原生 client／turn 与任务是否仍执行；不要删除 case、重跑旧步骤或把 phase 改成 verified。需要补充动作时形成新意图和明确处置方案，不自动重放。原始 ID、路径、问题与答案均留私有证据，公开报告只保留脱敏结果。

原生中断后可能由客户端保留队列暂停状态：本轮实测一个已确认加入的输入在 idle thread 上保持 queued，尚无任何 turn；桥接没有将其冒充运行，也未强制启动或重发。真实工作流将中断关卡放在最后；遇到日常相同现象，先核对准确队列／原终端状态，再由本人决定原端继续或选择新会话，不重发未知任务。自动恢复暂停队列需要独立确认启动语义，不作为 ENG01 的隐式功能改造。

临时模型验收仅用于明确授权的专用线程，不是生产桥接能力。原生模型／工具环境须实际产生结构化 async 问题；已终态且未产生该通知会明确失败，不把普通文字问题转换成授权，也不自动切模型。有具体授权时，prepare 和 run 均显式追加 `--async-test-model gpt-6.1-sol --confirm-temporary-model`；该选择随准备记录冻结，run 不接受临时换成另一模型。底层 `engineering_async_model.py` 保存原模型／完整受保护设置，严格核验身份／idle／空队列后只改测试线程，结束后精确恢复；任务或设置不确定时保留证据，不重试输入／答案。独立使用该入口的 run／report／cleanup 仍须准确 owned case 和全新报告目录。未取得具体授权不能把确认参数当成授权来源。

日常桥接与测试使用不同账本和假发送端，真实原生自测不默认要求停日常服务。先完成能力和资源预检，再把必要的正常停止、备份和 bootstrap 单独放进最终切换窗口；不能把模型等待或授权等待留在停服窗口。本轮原生阶段过早停服的实际时长已在交付记录单列，未当作程序启动时间。

回退到旧代码时，不能盲目恢复指向 editable 开发目录的旧 plist：开发源码已经提升后，该路径不再代表旧版本。应使用事先核验、兼容当前 schema 的独立旧版本解释器和目录。ENG01 准备的旧 0.1.2 不认识 `--release-manifest`，其恢复 argv 使用准确旧版本的 `.venv/bin/python -I -m wx_clawbot.managed --config <原配置> --state-dir <原状态根>`，WorkingDirectory 为旧版本目录；其他原 Label 设置保持，先正常停并核对锁，再 bootout／bootstrap。它没有新版本运行时 manifest 保护，必须单独复核非 editable、旧源码摘要和依赖；保留现有账本，不把代码回退变成旧数据覆盖。旧版本目录、备份和安装说明仅在明确保留策略／删除授权后清理。
