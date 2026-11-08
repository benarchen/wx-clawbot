# W02 原生连接证据

本文是 W02 早期现场调查与后续收尾的历史记录，原日期、失败和当时权限保持；标题中的“当前”指当时。现行无读屏接入见[身份契约](native-session-identity.md)，项目状态见 [ROADMAP](../ROADMAP.md)。

## 测试边界

本记录区分真实 daemon 握手、离线测试与终端产品验收。实际进度见 [ROADMAP](../ROADMAP.md)。没有向工作终端注入文本，没有创建替代 runtime 或复制历史。

## 真实握手定位与结果

2026-10-24，CLI 0.163.0、共享 daemon 0.164.0，Python 3.14.5。

首次原型经 `app-server proxy --sock` 向标准输入发送 JSONL，initialize 超时。随后核对 OpenAI 固定源码：proxy 使用 `tokio::io::copy` 透传原始字节，Unix 控制端点执行 WebSocket upgrade；它不做 JSONL／WebSocket 转换。依据：[proxy 分派](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/cli/src/main.rs)、[字节透传](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/stdio-to-uds/src/lib.rs)、[Unix transport](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/app-server-transport/src/transport/unix_socket.rs)。该源码为当前官方固定提交，不假定与安装二进制逐字相同；实际行为另行核对。

修正为已锁定 websockets 的 Unix WebSocket 连接，发 initialize（clientInfo、experimentalApi），收到响应后发 initialized。真实结果：握手成功，返回平台 unix／macos，版本 0.164.0。只关闭本桥接连接；未启动、停止、升级 daemon，未读取 thread 列表或正文，未提交模型任务。

## 已实现的安全边界

- socket 必须属于当前用户且禁止组／其他用户访问；未核对的版本拒绝接入。
- RPC 请求按带类型的 ID 关联；异步接收原生事件与请求。超时返回结果未知，不重放；断连失败所有待请求；事件队列满时连接进入故障状态，不悄悄丢审批。
- 宿主只读端点检查核对 session ID、job PID、微秒级进程启动时间、可执行路径与 TTY 设备号。普通 Shell、TTY 不符或退出端点均不会作为 Codex 候选。候选仅代表进程证据，尚不代表 native thread 已绑定。

2026-10-24 17:08，进程身份由秒级 `ps` 输出改为 macOS `libproc` 的 `PROC_PIDTBSDINFO` 与 `proc_pidpath`。读取路径前后复验 PID、用户、启动秒／微秒和 TTY；拒绝退出中与僵尸进程，不读取 argv 或环境。结构定义核对本机 Apple SDK 的 `sys/proc_info.h`／`libproc.h`；用 C 编译程序和 Python ctypes 对照，结构大小为 136 字节，TTY／启动秒／微秒偏移分别为 108／120／128，全部一致。自身进程真实读取稳定；同秒不同微秒的 PID 重用拒绝、端点退出、异常宿主 PID 为离线边界测试，未假称实际复现操作系统 PID 重用。

## 未通过关卡

早期 iTerm2 SDK 真实连接 localhost:1912 被拒绝。2026-10-24 17:05 只读检查仍未发现该端口监听，设置查询未返回启用值；未自动改设置。该项为历史失败证据，启用后的实际结果见后续记录；两个私有临时测试项目已准备。

V01 的 terminal／process／runtime／thread 四方关联及 V02 的桌面 → 桥接 → 桌面三轮仍未验证。不能把本阶段的握手成功称为原终端接入，也不能进入依赖它的 W03 验收。

离线测试使用内存对端及本地临时 Unix WebSocket 服务器，分别覆盖乱序响应、整数／字符串 ID、原生请求分类、超时与迟到响应、EOF、RPC 错误、畸形消息、事件溢出、版本拒绝及 socket 权限。它们不是 Codex 双端交互的实测。

## API 启用后的现场定位

2026-10-24 17:21，用户启用 Python API 后，真实 SDK 诊断成功，返回 1 个窗口、1 个终端。原先的未启用障碍已解除。现代 SDK 优先使用本机 Unix socket，只有不存在时才回退 TCP；单凭 TCP:1912 无监听不能判断 API 未启用，后续以 SDK 真实响应为准。依据为锁定 iterm2 2.30 的 connection.py 中 `_get_connect_coro` 实现。

本次专用窗口启动尝试暴露入口错误：传入的 Codex CLI 是 `#!/usr/bin/env node` 包装脚本，GUI 子进程找不到 node，用户截图显示 `env: node: No such file or directory`，会话已经退出。该尝试没有成功启动 Agent。已核对本机存在与 daemon 匹配的 0.164.0 原生可执行文件；新增启动命令构造检查拒绝包装脚本并安全引用参数，不修改全局 PATH 或 Codex 配置。修正后的启动尚待执行，不能宣称可见会话验收通过。

随后 SDK 创建调用停在返回创建响应后的 `_async_load → async_list_sessions`；受控中断了本次测试脚本，未停止 daemon 或用户终端。新连接的 WebSocket 握手也出现超时。本机只读线程采样显示 iTerm2 主线程处于 `_maybeWarnAboutShortLivedSessions → iTermWarning runModal → NSAlert runSheetModalForWindow`，可确认有短命会话退出警告正在等待处理；Unix API socket 由 iTerm2 持有。已请用户仅处理该警告及失败测试会话，不退出整个应用。界面工具被平台禁止访问 iTerm2，没有使用其他界面方式绕过。

诊断现在分别报告 connect／list_sessions 阶段，超时不再归因为未启用 API；关闭连接设定有限等待。启动测试将在创建回执返回后立即保存端点身份，再读取会话，避免失去已创建资源的核对依据。未收到界面恢复确认前不重试窗口创建。

## 现场恢复与持久信任关卡

2026-10-24 19:05，用户确认已关闭失败页面，SDK 真实复测成功，原工作终端未被注入测试输入。新的专用窗口已通过官方 SDK 创建，原生 Codex 0.164.0 正常运行，当前停在文件夹信任提示；没有创建 native thread 或执行模型任务。

原生提示明确说明信任决定会被保存，且临时目录位于本仓库内，信任目标为仓库根。测试没有直接确认提示。一次 SDK restart 的实测显示终端 ID 会改变，且即使先修改会话 profile，重启后的实际 argv 仍不包含新增参数；因此没有把 profile 修改当作启动成功依据。随后独立创建带真实单次 CLI 参数的测试 tab，逐字段核对其专用进程确实收到项目 trust_level 覆盖，仍显示信任提示。

已核对 0.163.0 正式标签对应提交与 0.164.0 现场行为：连接共享运行时后，TUI 的 check_directory_trust 调用服务端 read_remote_project_trust；不能用客户端 CLI 的临时覆盖替代此持久信任判断。依据：[0.163.0 实现](https://github.com/openai/codex/blob/83086188ae0614bd882818ff1aa23f3194962012/codex-rs/tui/src/onboarding/directory_trust.rs)、[当前固定源码](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/tui/src/onboarding/directory_trust.rs)。[官方单次 CLI 覆盖文档](https://learn.chatgpt.com/docs/config-file/config-advanced) 只说明一般覆盖机制，不能证明该远程信任检查接受覆盖。

服务端使用标准 Codex 配置根，当前项目没有项目级 `.codex` 目录或已有持久信任表。待用户确认的唯一配置增量为：

```toml
[projects."<project-root>"]
trust_level = "trusted"
```

这是一项待批准的例外，不是已经执行的变更，也不扩大其他项目或模型、认证、Skills、插件配置的修改范围。2026-10-24 19:16，全局 config.toml 摘要仍与任务开始时一致。没有批准前不接受原生信任提示或写入该文件。

项目范围的 thread 查询、已加载 thread 的订阅校验与连接清理已补齐；37 项离线及合成对端测试通过。真实 V01／V02 仍缺 native thread 绑定与三轮连续性，不能以原生程序启动成功替代验收。

## 后续验收完成记录

本人随后明确授权当前项目唯一信任项，已按授权新增；原文件字节全部保留，TOML 语义只有该条增量。测试改用与原终端一致的本机共享 daemon 模式，根目录信任正常继承，原生可执行文件仍为已安装的 0.163.0，运行时仍为既有 0.164.0。没有新增其他目录信任项。

2026-10-24 21:39，公开只读验收器重新读取真实端点和原生历史后通过，两份项目三轮、同目录区分、普通 Shell／退出拒绝、独立运行时拒绝、模型与配置基线均有证据。前述历史障碍及待验证描述不再表示当前状态；完整的关卡映射和验证边界见 [W02 验收说明](validation/w02.md) 与 [脱敏结果](validation/w02.json)，项目当前阶段见 ROADMAP。
