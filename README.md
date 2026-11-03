# wx-clawbot

面向本机 iTerm2 Codex 原生会话的微信桥接项目。

本项目自有代码和文档采用 [MIT License](LICENSE)。第三方依赖保持原授权，其中 iterm2 Python SDK 声明 GPLv2+；本项目 MIT 授权不代表完整组合产品可按 MIT 闭源再发行。依赖清单和发行边界见 [第三方声明](THIRD_PARTY_NOTICES.md)。

当前版本为 [`0.1.2`](https://github.com/benarchen/wx-clawbot/tree/v0.1.2)，已在本机使用原托管入口运行。已有账本须通过显式备份升级到 schema 6，启动不会自动迁移；操作见[账本升级](docs/state-schema.md)及[本机交付记录](docs/validation/local-release.md)。

当前提供前台微信桥接：本人绑定、项目选择、原终端会话发现与切换、单次派发与持续聚焦、独立观察订阅，以及在 iTerm2 可见创建新 Codex 会话。任务通过原生 daemon 队列提交，回复区分入队、执行和最终结果。[实际行为与验证范围](docs/validation/w05.md) 说明各入口的范围。

任务执行结果与仓库占用分别保存。历史 unknown 在准确原生终态与完整队列核验后可释放占用，未知结果继续保留且不会重跑；证据不足继续阻塞。`/status <任务 ID>` 可查看占用、阻塞原因和核验时间，`/stop <任务 ID>` 可撤销尚未提交的等待；正式诊断及异常处置见[运维说明](docs/operations.md#rec01-候选的准入诊断与受控切换)。

取消确认只发送一条；主动中断已订阅的桌面任务时，最终结果不再重复发送观察副本。最终正文保留原生最终回答及错误，不混入标记为 commentary 的进展；没有最终回答时明确说明。

Android 微信 8.0.80 已验证换行、加粗、明确层级标题、列表／引用、链接、行内代码及代码块展示。含代码的简单列表项以所属项标签另列续段和独立代码；表格采用字段列表，受限样式明确提示兼容。长结果按结构分段，代码与 URL 字面内容受保护，旧冻结回执不重排。[格式规则与客户端边界](docs/wechat-markdown.md) 说明复制、超限及 Mac 的已知限制。

中断结果以原生轮次的 `interrupted` 确认为准；已经启动的系统子进程可能继续运行，不能将该回执理解为所有子进程均已终止。

微信当前交互转发覆盖已接入的原生命令审批和同步追问，支持一次性审批、多题单选及自由文本；电脑与微信操作同一原生请求，由原生运行时裁决首次有效答复。已处理、过期或断连旧请求的答复被拒绝。[交互证据](docs/validation/w08.md) 区分各实际场景。`0.166.0` 的结构化异步问题另提供即时通知与 `/answer q-...` 补充答复，单题支持自由文字，多题使用完整 q 题键 JSON；入口有效 600 秒，任务可能继续运行。桥接持久化单次提交，电脑与微信仍可能同时被原生接受；已知外部输入使入口失效，冲突明确提示，必须等待或审批的动作继续走同步确认。接收、输入可见与模型采用分别记录，未知不重试、不跨轮次另开任务。详见[异步答复指南](docs/async-questions.md)。

Python 模块另提供目录校验、环境诊断、显式绑定复核，以及命令审批和多题单选与自由文本答复校验；[原生模块验证](docs/validation/w03.md) 说明交互与队列的底层行为。

微信侧提供独立二维码登录、本人绑定和指定口令文本回显，可与本人微信真实往返；该诊断入口不执行 Codex 任务。操作见[微信联调说明](docs/wechat-protocol.md)。

`serve` 提供前台命令桥接入口，组合项目／会话路由、原生队列、独立观察订阅和可见启动。任务意图与回复分别记录在本项目私有运行账本；重启后的未知任务不会自动执行。运行时换代后，仅在当前原终端完整复验及原生 client／终态唯一匹配时只读更新历史结果；图片受仓库保护等待时会说明原因。原生组件的实际检查范围见 [W05 证据](docs/validation/w05.md)。

## 安装与使用

使用 Python 3.14，并准备可用的 Git、iTerm2 与已登录的 Codex。实际执行任务需要受支持的既有原生 daemon；宿主或运行时暂时缺席时，微信帮助、项目列表和状态仍可用，桥接不自动启动 daemon。Git 用于核对同仓库与 worktree 的准入冲突；在仓库根目录执行：

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

当前已核验的原生 app-server 版本为 `0.163.0`、`0.164.0`、`0.165.0`、`0.166.0`；以 `doctor` 的 `runtime.appServerVersion` 和 `verified_schema` 为准，CLI 版本可以不同。`verified_schema: false` 时不要继续启动，须先核对对应版本协议，不能只修改版本列表绕过检查。

显式检查 iTerm2 API：`.venv/bin/wx-clawbot doctor --iterm2`。这可能触发宿主脚本授权；诊断不会启用 API、发送终端输入或启动 Codex。[协议与依赖基线](docs/protocol-baseline.md) 记录版本和重建方式。

核对现有运行时 socket 后，可只读测试握手：

```sh
.venv/bin/wx-clawbot native-probe --socket /absolute/path/to/native-control.sock
```

该命令核验 socket 归属、访问模式和已核对的协议版本，不创建、恢复或执行会话；输出连接状态与运行时版本。

现场原型的操作与显式验收入口见 [原终端验证说明](docs/validation/w02.md)。未完成身份核验的终端保持未绑定；目录或窗口标题不能作为会话身份。

当前绑定复验要求 Codex 状态栏显示准确原生线程 ID，用于识别同一进程内的会话切换。当前现场客户端使用 `thread-id` 显示项；未显示、被截断或与目标不匹配时拒绝派发，桥接不会自动编辑 Codex 全局配置。[W05 现场证据](docs/validation/w05.md) 保留当时版本和设置记录。

已有终端可在原会话中运行 `/statusline`，启用 Thread ID 并置于首位；已有有效线程 ID 时无需重复添加。不要同时显示 Thread ID 和 Session ID，底部多个 UUID 会被保守拒绝。此原生设置会保存到 Codex 的 `tui.status_line`；无需关闭原会话，新终端读取已保存设置，已有终端需要在各自 TUI 中应用。选项名称须以受支持客户端实际显示为准，不能仅因配置中没有 `session-id` 就判断身份缺失。

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

微信中发送 `/projects` 查看注册项目，`/sessions` 获取会话编号，`/focus 1` 选择后续普通消息目标，或 `/send 1 指令` 单次派发。`/cd 项目别名` 复用受管会话，没有时可见创建；`/new 标题` 在当前目录新建。有效的 `/sessions`、`/cd`、`/new` 可按需拉起未运行的 iTerm2；其他命令和普通消息不触发应用启动。`/help` 返回命令说明，`/status` 查看目标、任务及宿主／原生就绪状态。独立 `/attach`／`/detach` 语义见[命令契约](docs/command-contract-proposal.md)。

宿主连接失效后，桥接保持微信收发并在 iTerm2 重新运行时自动重连；用户主动退出应用后，后台不会反复拉起。重新连接后需要完整核验原会话，旧数字列表失效；只恢复窗口内容不能证明原 Codex 仍在。认证和 API 等待有时限，系统授权仍须本人处理，不自动改设置。真实验收状态及限制见 [HOST01 证据](docs/validation/host-lifecycle-recovery.md)。

按收到的准确请求 ID 使用 `/approve`／`/deny`；追问使用 `/answer`，多题答案须为实际题目 ID 到回答数组的 JSON 对象。单独发送选项文字会按普通任务处理，不自动猜测要回答哪道题。交互十分钟过期后只拒绝微信迟到答复，不自动批准或拒绝原生请求；仍可在原终端核对处理。

前台运行使用独立 `runtime.sqlite3`，首次只从本项目旧诊断库读取游标和回复上下文，不导入诊断消息为任务，不修改旧库 schema。初始化运行账本后，指定口令 `wechat echo` 不再使用旧诊断游标；微信通道同时只允许一个本项目消费者。退出前台进程会保留原生终端和其中可能仍在执行的任务。重启先启动微信通道，再恢复依赖和通过完整身份核验的选择；恢复期间拒绝新派发，不能核验的目标保持未选并提示刷新，旧列表编号失效，未知任务不自动重放。

已有旧版账本时，先用 `.venv/bin/wx-clawbot migrate-state` 只读检查升级计划；`serve` 不会自动升级已有运行数据。字段、备份、拒绝条件与显式执行方法见[账本升级说明](docs/state-schema.md)。

`.venv/bin/wx-clawbot maintain-state` 默认只读查看已结记录的保留期计划；实际清理需要显式操作并停止前台，具体范围见同一账本说明。

另一个普通 Shell 可运行 `.venv/bin/wx-clawbot status` 只读查看计数和待核对回执 ID，或用 `.venv/bin/wx-clawbot stop` 请求当前桥接自行退出；原生 Codex 会话继续运行。只重试回执的 `retry-reply`、分组件故障处理、私有权限及用户级托管模板见[前台运维说明](docs/operations.md)。

长期运行提供用户级 launchd 托管入口：登录启动、异常退出后限速重启、正常 stop 后保持停止；复用原配置及账本，不管理 Codex／iTerm2 进程。托管状态可由 status 核对，私有诊断日志限制容量并轮转。安装、主动恢复及回退见同一[运维说明](docs/operations.md)；电脑睡眠或关机期间不保证微信在线。

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

性能优化已整合入 `0.1.0`；原候选的源码补丁、自动验证入口及历史测量见[PERF01 记录](docs/validation/performance-optimization.md)，整合验证与实际部署见[本机交付](docs/validation/local-release.md)。原补丁仅用于从准确基线重建，不能重复套用到已升级工作区。

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q src tests
git diff --check
```

[排版模块与自测](docs/wechat-markdown.md) · [项目规范](AGENTS.md) · [当前进度与阻塞](ROADMAP.md) · [产品设计](docs/product-design.md) · [架构](docs/architecture-design.md) · [技术决策](docs/technical-decisions.md) · [开发契约](docs/development-contracts.md) · [施工清单](goals/implementation-plan.md)

本人可在已聚焦的原生会话中直接发送一张静态 JPEG／PNG，图片通过原队列处理，结果以文本返回；发送前使用 `/sessions` 和 `/focus <编号>` 选择目标。图片输入的原生版本准入为 0.165.0／0.166.0，当前已有账本须显式升级到 schema 4（包含 IMG01 的附件结构）。详细操作与边界见 [图片输入指南](docs/image-input.md)。

独立二维码登录、本人确认及指定口令文本诊断的操作入口见 [微信通道协议与联调说明](docs/wechat-protocol.md)。诊断命令不会执行 Agent 任务，只有已明确确认的本人绑定才能进行测试收发。
