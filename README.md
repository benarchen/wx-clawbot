# wx-clawbot

面向本机 iTerm2 Codex 原生会话的微信桥接项目。

当前提供项目配置与目录校验、只读环境诊断，以及连接既有 Codex 原生会话的 Python 原型接口：候选端点发现、显式绑定复核、事件订阅、空闲轮次提交、daemon 队列操作、命令审批与多题追问答复校验。[模块能力及真实验证](docs/validation/w03.md) 说明各入口的范围。

## 安装与使用

使用 Python 3.14，在仓库根目录执行：

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
