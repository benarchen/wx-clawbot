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

出现 `foreground_ready` 才表示完成账本恢复、原生连接和宿主连接；不代表某个业务任务已经执行成功。stdout 只输出状态及错误分类，不输出消息正文、凭据或认证响应。前台不自动写日志文件，终端历史的保留由使用者控制。

另一个普通 Shell 中运行：

```sh
.venv/bin/wx-clawbot status
.venv/bin/wx-clawbot doctor --state-dir "$HOME/Library/Application Support/wx-clawbot"
.venv/bin/wx-clawbot stop
.venv/bin/wx-clawbot status
```

自定义运行目录时，以上命令与 `serve` 都传入同一个 `--state-dir`。`status` 只读显示实例、权限、任务／回执计数及最多 100 个待核对回执 ID，不读出任务正文、微信身份或回复上下文。`running` 表示实例记录的进程启动身份及消费者锁同时有效；`consumer_unverified` 表示消费者存在但没有可核验实例，例如旧入口，不等同服务健康。`stopped` 表示消费者锁空闲；任务可能仍在原生终端执行。

`stop` 只写入当前实例代次的退出请求，不发送进程信号、不停止 Codex。返回 `stop_requested` 后等待 `status` 成为 `stopped`；HTTP 工作线程可能仍在等待超时，不要立刻启动第二个消费者。未核验实例拒绝请求；旧入口在原前台按 Ctrl+C。Ctrl+C 也是正式前台入口的正常退出方式。异常退出遗留的旧代次不会停止新实例。

重启仍使用同一 `serve` 命令；恢复原生状态后才轮询接收。旧审批失效；未知任务只核对原生记录，无法确认时保留 unknown，不重新执行。上次选择只有重新通过完整身份核验才恢复；不能核验时保持未选，旧列表编号失效。若启动时被原生弹窗遮住 Session ID，待终端恢复后用 `/sessions` 刷新，触发一次只读对账，再按新列表选择目标；仍不能核验的任务继续保持 unknown。

## 故障定位

错误只报告组件、异常类型和操作建议，不把异常中的响应正文直接输出。

| 组件／状态 | 核对方式 |
| --- | --- |
| config | 检查 JSON 字段、项目目录与可访问性 |
| state／upgrade_required | 检查 `0700`／`0600`、本人绑定、单消费者及[显式升级计划](state-schema.md)，不删除库重新开始 |
| agent_discovery／agent | 核对既有 daemon、受支持版本、同一 Codex home、当前完整 Session ID；未知任务不重新发送 |
| host | 打开 iTerm2，核对 Python API 和该脚本的授权，执行 `doctor --iterm2` |
| channel_receive／channel_send | 核对网络、本人绑定与登录状态；登录过期需要本人扫码，不能读取其他项目凭据或静默替换连接 |
| receive_disconnected | 网络轮询会有限退避重连，游标保留；不代表已丢消息或应再次提交任务 |
| maintenance／lifecycle | 核对账本／原生连接或实例记录权限；必要时在原前台 Ctrl+C 后重新诊断 |

不使用 `killall`／宽泛进程名停服务，不清空运行目录来绕过锁或升级错误。现有 hook 告警属于原环境，桥接不修改它来掩盖失败。

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

## 可选 launchd 模板与卸载

[用户级模板](../config/launchd.example.plist) 仅供后续明确部署。先替换所有绝对路径占位值，保持 `ProgramArguments` 数组，不拼接 Shell；显式 socket／原生可执行文件可避免 launchd 的缩减 PATH。模板不含凭据，凭据仍从私有目录读取。`RunAtLoad` 和 `KeepAlive` 均为 false，不自动启动或重启；stdout／stderr 指向 `/dev/null`，避免无界日志。需要保留日志时另行指定有轮转与权限管理的方案。

人工检查模板可用 `plutil -lint /absolute/path/to/private/local.wx-clawbot.plist`。本项目不会复制到 LaunchAgents 或执行注册。仅在未来明确部署该模板后，可用 macOS `launchctl bootstrap gui/$(id -u) /absolute/path/to/private/local.wx-clawbot.plist` 注册，`launchctl kickstart gui/$(id -u)/local.wx-clawbot` 启动；停止先用本项目 `stop`，再核对 `status`。卸载仅对自己部署的此 Label 执行 `launchctl bootout gui/$(id -u)/local.wx-clawbot` 并移除自己复制的模板，不操作其他 Label。

当前前台方式卸载时，先停止并核对桥接已退出；按需要保留私有运行目录以供恢复。删除凭据、账本、项目或虚拟环境均由本人另行明确选择，不自动删除；Codex 和 iTerm2 不需要卸载，也不应停止其会话。
