# 桌面统一排队契约与决策记录

本人于 2026-10-25 明确选择专用桌面排队入口，要求记录产品形态和后续修改依据。需求权威为 [产品设计场景 F](product-design.md#场景-f电脑与微信共同排队)；本文保存具体契约、选择理由与演进边界。该选择不将原 TUI 的 Tab 判定为已通过统一队列验收。

## 已验证的差异

原生 CLI 0.163.0 与 0.164.0 的 TUI 将忙碌时 Tab 输入保存在客户端本地；daemon 的 `thread/queue/add` 使用另一份队列。真实对照中，两份输入被放入同一 turn，只有后一条任务的标记得到回答，不能作为独立任务交付。

官方 `codex queue` 是向既有 thread 提交的控制命令，不启动另一个 Agent 会话。专用可见 Shell 已通过该命令与桥接共同入队：门控任务结束后，两条任务按原生顺序分别成为独立 turn，client ID 与 queue ID 均可核对，结果显示在原 TUI。

源码依据：[CLI queue](https://github.com/openai/codex/blob/83086188ae0614bd882818ff1aa23f3194962012/codex-rs/tui/src/session_queue_commands.rs)、[TUI 本地队列](https://github.com/openai/codex/blob/83086188ae0614bd882818ff1aa23f3194962012/codex-rs/tui/src/chatwidget/input_flow.rs)、[start 或 steer](https://github.com/openai/codex/blob/83086188ae0614bd882818ff1aa23f3194962012/codex-rs/app-server/src/request_processors/turn_processor.rs)。

## 已确认的首版契约

- 微信普通任务与桌面“排队”入口都调用同一 thread 的 daemon 队列，逐项关联原生 queue ID、client ID 和实际 turn；停止、状态及答复继续走独立控制路径。
- 桌面忙碌时，在单独的普通 Shell 使用明确的排队命令，原 Codex TUI 继续运行、显示结果并接受审批／追问；空闲时仍可在原 TUI 输入。
- 桌面使用原生命令 `codex queue --thread <native-thread-id> --message '<task>'`；在单独普通 Shell 执行，连接地址及完整 native thread ID 必须先核对，不按标题或目录猜测。多运行时时显式指定已核验的 `--remote unix://<socket-path>`。该命令是向已有会话提交任务的控制入口，不能以它启动或恢复另一个 Agent 会话。
- 不声称已拦截原 TUI 的 Enter／Tab。直接使用它们仍遵循 Codex 的原生行为，不能被当成上述统一排队入口；检测到同一 turn 被外部追加输入时，任务状态须明确反映这一事实，不能伪造独立完成。
- 不修改全局配置或快捷键，不替换现有客户端，不停止原会话，也不安装完整 Gateway。

## 选择理由与后续改造依据

选择专用入口的原因是统一 daemon 队列已经实测可行，而改造 Codex CLI 的 TUI 会引入额外构建与版本维护，超出首版所需成本。入口变化已获本人确认；微信侧命令与同一原生会话要求保持不变。

后续使用中若需要恢复原 TUI 内直接统一排队，先复测 [原 TUI 反例及验证方法](validation/w03.md)，核对目标版本的本地队列、服务端队列、`turn/start`／steer 行为，再设计适配。验收仍要求两端忙碌输入按序生成独立 turn，各任务有自己的结果与原生取消确认；不能仅凭新增选项或升级版本推断解决。

研究对象主要是 Codex CLI 的 TUI 输入派发，iTerm2 负责窗口与终端生命周期。必须提前评估是否要维护修改版客户端、是否需要重新打开已有终端、如何保持 native thread／上下文与原模型，以及回退方式。实施前重新确认范围，不自动替换客户端、迁移会话或修改全局配置。
