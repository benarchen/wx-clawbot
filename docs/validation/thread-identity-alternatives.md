# 当前桌面线程身份的后台获取与替代路径

初始范围为 0.167.0 后台身份接口调研，未执行 Hooks／标题实验或修改用户配置。本人随后于 2026-11-07 明确采用微信独立选择：已确认目标不跟随桌面切换，无法可靠接入时提示。该路径已完成实现与真实原生验收，随后按新授权随 0.1.7 发布部署，见 [TGT01 交付](wechat-independent-target.md)及[发布记录](wechat-independent-release.md)；以下后台接口结论不意味着必须跟随桌面当前显示。

## 已核对的接口边界

本机生成的 ClientRequest 包含 180 个请求变体，ServerNotification 包含 86 个通知变体。核对方法名及 ThreadReadResponse／ThreadLoadedListResponse／InitializeParams，未发现将 iTerm2 terminal ID／进程身份映射到该 TUI 当前所选 thread 的直接查询或切换通知。

Thread 元数据提供 id、sessionId、cwd、status、source、threadSource、originator 等；source 表示来源，originator 明确是创建时来源，不代表当前客户端。Initialize 的 ClientInfo 仅有 name／title／version；loaded/list 返回线程列表和分页游标，不包含终端当前选择。remoteControl/client 等名称不是已证实的本地 TUI 选择接口，不能仅凭命名推断可用。

[官方 app-server 文档](https://learn.chatgpt.com/docs/app-server)说明 loaded/list 是内存中已加载线程，不能据此推断正在某个窗口显示。项目已有[同进程切换反例](w05.md)：旧线程仍 loaded／idle／可输入，因此 PID、cwd、最近活跃时间、旧启动登记或某个日志文件仍打开，均不足以独立证明当前选择。

## 候选路线

| 路线 | 能力与限制 | 当前判断 |
| --- | --- | --- |
| 保留原 CLI，读取后台现有列表 | 能获得原生 thread ID／状态／历史，但没有证实桌面选择映射 | 不能独立完成首次关联；已证明绑定可按准确身份独立复验 |
| 将准确 ID 移到终端标题／结构化终端变量 | 须证明完整 thread UUID 与原生更新来源 | 本人明确不采用标题方案；本次不实施结构化变量实验 |
| Hooks 主动登记映射 | 可在启动／恢复等事件记录身份，但事件携带 session_id，不保证为当前 thread；子 Agent Hooks 使用父 session_id，切走会话也不会立即触发 SessionEnd | 可辅助定位，当前不足以单独作为派发门禁 |
| 在原生 TUI 增加当前选择 IPC／事件 | 可报告桌面选择，但需改原生客户端或推动官方支持 | 本人明确不采用；微信独立选择不需要实现桌面选择跟随 |
| 微信独立选择原生 thread | 保留首次来源证明，对已选 thread 独立复验并按原生队列派发 | 本人已明确要求实施；候选已验证同进程 A→B 后准确 A 续接、B 不串投及失效提示 |

[官方标题配置](https://learn.chatgpt.com/docs/developer-commands)提供 `/title` 及 thread 标题项；文档未据此证明本机输出完整 UUID、所有切换同步或可作为稳定机器身份，故只能列为实验候选。手动标题或任意程序可写的变量不能升级为可信身份源。

[官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks)列出 SessionStart 的 startup／resume／clear／compact／fork 来源，公共字段 session_id，且说明子 Agent 使用父 session_id；SessionEnd 不会在切走会话时立即触发。因此不能把“最后一次 Hook 登记”视作“当前桌面选中”。这些是当前官方说明，本机各具体事件仍需匹配版本实测，未据此修改 Hooks。

## 验收与决策边界

若以后继续替换首次发现的页脚来源，仍须覆盖 `/new`、恢复、fork、子线程与多个 TUI，核对标识对应准确 thread 而非 session 根。本次没有取消首次发现的页脚要求，只将已证明绑定的后续复验与桌面当前选择分离；进程、运行时代次、native session、目录及加载状态仍须复验，未知任务不重放。

真实试验还观察到：测试观察连接断开后，原生可卸载旧 A，独立选择不保证卸载后仍能使用；此时明确拒绝，不能从存档恢复。持续原生订阅下的准确 A 续接已通过。本次不再把“必须始终跟随桌面当前画面”当作用户要求；当前产品决策以[命令契约](../command-contract-proposal.md#微信独立选择原生会话)为准。
