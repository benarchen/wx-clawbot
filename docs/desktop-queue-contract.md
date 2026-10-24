# 桌面统一排队入口提案

本文等待本人确认，不改变现有产品入口，也不将原 TUI 的 Tab 判定为已通过验收。

## 已验证的差异

原生 CLI 0.163.0 与 0.164.0 的 TUI 将忙碌时 Tab 输入保存在客户端本地；daemon 的 `thread/queue/add` 使用另一份队列。真实对照中，两份输入被放入同一 turn，只有后一条任务的标记得到回答，不能作为独立任务交付。

官方 `codex queue` 是向既有 thread 提交的控制命令，不启动另一个 Agent 会话。专用可见 Shell 已通过该命令与桥接共同入队：门控任务结束后，两条任务按原生顺序分别成为独立 turn，client ID 与 queue ID 均可核对，结果显示在原 TUI。

源码依据：[CLI queue](https://github.com/openai/codex/blob/83086188ae0614bd882818ff1aa23f3194962012/codex-rs/tui/src/session_queue_commands.rs)、[TUI 本地队列](https://github.com/openai/codex/blob/83086188ae0614bd882818ff1aa23f3194962012/codex-rs/tui/src/chatwidget/input_flow.rs)、[start 或 steer](https://github.com/openai/codex/blob/83086188ae0614bd882818ff1aa23f3194962012/codex-rs/app-server/src/request_processors/turn_processor.rs)。

## 拟采用的契约

- 微信普通任务与桌面“排队”入口都调用同一 thread 的 daemon 队列，逐项关联原生 queue ID、client ID 和实际 turn；停止、状态及答复继续走独立控制路径。
- 桌面忙碌时，在单独的普通 Shell 使用明确的排队命令，原 Codex TUI 继续运行、显示结果并接受审批／追问；空闲时仍可在原 TUI 输入。
- 当前可验证的原生命令为 `codex queue --thread <native-thread-id> --message '<task>'`；连接地址须先核对。本项目若正式提供桌面入口，应复用会话绑定检查，不让用户凭标题或目录猜 thread。
- 不声称已拦截原 TUI 的 Enter／Tab。直接使用它们仍遵循 Codex 的原生行为，不能被当成上述统一排队入口；检测到同一 turn 被外部追加输入时，任务状态须明确反映这一事实，不能伪造独立完成。
- 不修改全局配置或快捷键，不替换现有客户端，不停止原会话，也不安装完整 Gateway。

## 决策边界

采用此提案会增加一个明确的桌面排队入口，因此须由本人确认。若要求原 TUI 的 Enter／Tab 自动进入统一队列，则当前两版原生客户端的现场验证仍失败，需要原生客户端实现相应支持；本项目不能把单独入口冒充原按键行为已经修复。
