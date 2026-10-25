# wx-clawbot

面向本机 iTerm2 Codex 原生会话的微信桥接项目。

当前提供前台微信桥接：本人绑定、项目选择、原终端会话发现与切换、单次派发与持续聚焦、独立观察订阅，以及在 iTerm2 可见创建新 Codex 会话。任务通过原生 daemon 队列提交，回复区分入队、执行和最终结果。[实际行为与验证范围](docs/validation/w05.md) 说明各入口的范围。

Python 模块另提供目录校验、环境诊断、显式绑定复核，以及命令审批和多题单选与自由文本答复校验；[原生模块验证](docs/validation/w03.md) 说明交互与队列的底层行为。

微信侧提供独立二维码登录、本人绑定和指定口令文本回显，可与本人微信真实往返；该诊断入口不执行 Codex 任务。操作见[微信联调说明](docs/wechat-protocol.md)。

`serve` 提供前台命令桥接入口，组合项目／会话路由、原生队列、独立观察订阅和可见启动。任务意图与回复分别记录在本项目私有运行账本；重启后的未知任务不会自动执行。原生组件的实际检查范围见 [W05 证据](docs/validation/w05.md)。

## 安装与使用

使用 Python 3.14，并准备可用的 Git、iTerm2 与已登录的 Codex 原生 daemon。Git 用于核对同仓库与 worktree 的准入冲突；在仓库根目录执行：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/wx-clawbot doctor
```

按 [配置模板](config/config.example.json) 准备本机配置，项目 root 使用真实绝对路径，再运行：

```sh
.venv/bin/wx-clawbot doctor --config /absolute/path/to/private/config.json
```

诊断输出只包含版本、配置状态和项目数量；无效配置返回非零状态，不打印配置内容。

显式检查 iTerm2 API：`.venv/bin/wx-clawbot doctor --iterm2`。这可能触发宿主脚本授权；诊断不会启用 API、发送终端输入或启动 Codex。[协议与依赖基线](docs/protocol-baseline.md) 记录版本和重建方式。

核对现有运行时 socket 后，可只读测试握手：

```sh
.venv/bin/wx-clawbot native-probe --socket /absolute/path/to/native-control.sock
```

该命令核验 socket 归属、访问模式和已核对的协议版本，不创建、恢复或执行会话；输出连接状态与运行时版本。

现场原型的操作与显式验收入口见 [原终端验证说明](docs/validation/w02.md)。未完成身份核验的终端保持未绑定；目录或窗口标题不能作为会话身份。

当前绑定复验还要求 Codex 状态栏显示 Session ID，用于识别同一进程内的会话切换。未显示、被截断或与目标不匹配时拒绝派发；原型不会自动编辑 Codex 全局配置开启该项。[W05 现场证据](docs/validation/w05.md) 说明原因与验证范围。

已有终端可在原会话中运行 `/statusline`，启用 Session ID 并置于首位。此原生设置会保存到 Codex 的 `tui.status_line`；无需关闭原会话。新终端读取已保存设置，已有终端需要在各自 TUI 中应用。

完成本人绑定后，可显式启动前台桥接：

```sh
.venv/bin/wx-clawbot serve --config /absolute/path/to/private/config.json
```

该命令通过本机 Codex CLI 只读发现既有 daemon。需要明确指定时：

```sh
.venv/bin/wx-clawbot serve \
  --config /absolute/path/to/private/config.json \
  --socket /absolute/path/to/native-control.sock \
  --codex-executable /absolute/path/to/native/codex
```

`--codex-executable` 必须是已核验的原生可执行文件，不能使用依赖 GUI 环境中 `node` 的包装脚本。默认沿用当前用户的 Codex home；可用 `--codex-home` 明确指定同一既有运行时的目录。桥接不自动更换模型或修改全局配置。

微信中发送 `/projects` 查看注册项目，`/sessions` 获取会话编号，`/focus 1` 选择后续普通消息目标，或 `/send 1 指令` 单次派发。`/cd 项目别名` 复用受管会话，没有时可见创建；`/new 标题` 在当前目录新建。`/help` 返回命令说明，`/status` 查看目标与任务。独立 `/attach`／`/detach` 语义见[命令契约](docs/command-contract-proposal.md)。

前台运行使用独立 `runtime.sqlite3`，首次只从本项目旧诊断库读取游标和回复上下文，不导入诊断消息为任务，不修改旧库 schema。初始化运行账本后，指定口令 `wechat echo` 不再使用旧诊断游标；微信通道同时只允许一个本项目消费者。退出前台进程会保留原生终端和其中可能仍在执行的任务；重启不自动恢复上次输入焦点，须重新选择目标。

已有旧版账本时，先用 `.venv/bin/wx-clawbot migrate-state` 只读检查升级计划；`serve` 不会自动升级已有运行数据。字段、备份、拒绝条件与显式执行方法见[账本升级说明](docs/state-schema.md)。

`.venv/bin/wx-clawbot maintain-state` 默认只读查看已结记录的保留期计划；实际清理需要显式操作并停止前台，具体范围见同一账本说明。

另一个普通 Shell 可运行 `.venv/bin/wx-clawbot status` 只读查看计数和待核对回执 ID，或用 `.venv/bin/wx-clawbot stop` 请求当前桥接自行退出；原生 Codex 会话继续运行。只重试回执的 `retry-reply`、分组件故障处理、私有权限及待部署模板见[前台运维说明](docs/operations.md)。

会话列表同时显示编号、稳定会话 ID、原终端／受管类型和目录。启动未确认时，可用 `/sessions` 核对已经出现的原会话，不必再次新建。失败任务会保留原生错误；额度恢复后可提交新请求，原失败任务不会自动重跑。仍在原终端和原生已加载列表中的错误状态会话，经完整身份复验后可以继续使用。

## 桌面普通任务排队

电脑忙碌时，在另一个普通 Shell 使用 Codex 自带的排队命令，向已核验的原会话提交任务：

```sh
codex queue --remote unix:///absolute/path/to/native-control.sock \
  --thread '<native-thread-id>' --message '完成当前任务后，再检查测试结果'
```

先核对原会话的完整 native thread ID 和其运行时 socket，再替换示例占位值。该命令返回原生队列 ID，任务随后在同一原会话执行，结果仍显示在原 Codex 终端。收到入队回执只表示已排队；结果未知时先查询原生状态，不重复提交同一任务。

首版采用这一专用桌面入口共用 daemon 队列。原 TUI 的 Enter／Tab 保持 Codex 原生语义，忙碌时的独立普通任务使用上述入口；空闲时仍可直接在原 TUI 继续对话。操作边界、选择原因和后续客户端适配依据见 [桌面排队契约](docs/desktop-queue-contract.md)。

## 开发与文档

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q src tests
git diff --check
```

[项目规范](AGENTS.md) · [当前进度与阻塞](ROADMAP.md) · [产品设计](docs/product-design.md) · [架构](docs/architecture-design.md) · [技术决策](docs/technical-decisions.md) · [开发契约](docs/development-contracts.md) · [施工清单](goals/implementation-plan.md)

独立二维码登录、本人确认及指定口令文本诊断的操作入口见 [微信通道协议与联调说明](docs/wechat-protocol.md)。诊断命令不会执行 Agent 任务，只有已明确确认的本人绑定才能进行测试收发。
