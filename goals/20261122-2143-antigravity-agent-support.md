# AGY01：多 Agent 架构与 Antigravity（`agy acp`）完整兼容施工清单

## 一、 状态、目标与授权

- **编制时间**：2026-11-22 21:43（北京时间 `Asia/Shanghai`）。
- **当前状态**：`round2_candidate_ready（G01–G06 及首轮微信真机 5 项修复 + 深度代码审计加固完成，离线 1059 项与隔离真实 agy 1.5.14 复验通过；已部署独立候选待本人二轮微信复测）`。
- **迭代目标**：
  1. 在不破坏现有 Codex 全量能力（1041 项测试、SQLite schema 6、路由快照 version 2）的前提下，建立对称的多 Agent 后端抽象。
  2. 基于官方 `agy acp --stdio`（Agent Client Protocol，JSON-RPC 2.0 over stdio，零新增第三方依赖）接入 Antigravity（`agy`）后端，与 Codex 并行独立运行、各自升降级。
  3. 配置层支持可选 `default_agent`（默认 `codex`，后续可直接切换为 `antigravity`/`agy`），命令层支持显式覆盖（如 `/cd wx-clawbot agy`、`/cd wx-clawbot codex`、`/new agy [标题]`、`/new codex [标题]`）。
  4. 按 Codex 完整能力对齐交付 Antigravity：会话新建／发现／恢复（`session/resume`）、多轮文本对话、单张静态 JPEG／PNG 图片入站、`/model`／`/model list`／`/model set <模型> [推理强度]`、`/agy status`（及 `/agent status`）、`/stop` 中断（`session/cancel`）、原生权限审批桥接（`session/request_permission` → `/approve` `/deny`，绝不启用 `--dangerously-skip-permissions`）、桥接顺序排队（防并发 `session/prompt` 合并竞态）以及与 Codex 共享同一仓库级 `occupancy` 占用锁。
  5. 对 Antigravity 协议不存在或语义不同的能力（如 Codex 专属 `/fast` 档位、账号级剩余百分比额度桶、桌面 TUI 实时 `/attach` 观察），通过能力门禁明确拒绝并给出清晰提示，绝不伪造。
- **执行授权与边界**：
  - 本人已于 2026-11-22 明确确认四项关键决策：接受 `agy` 无桌面 iTerm2 会话（后台 `agy acp` 协议托管）；默认保持 `codex` 并支持后置/显式参数指定 `agy` 且可配置切换默认值；按现有 Codex 完整能力目标交付；权限策略与 Codex 保持一致（绝不跳过权限确认）。
  - 本次施工仅在 `dev` 分支实施并完成离线及专用隔离真实 `agy` 验证；**不自动执行** Git 提交、`main` 合并、打 tag、推送或切换本机生产独立制品（待本人确认与真机验收后按标准收尾执行）。

---

## 二、 Phase 0 协议实测基线（本机 `agy 1.5.14` 一手证据）

2026-11-22 在 `.tmp/phase0-agy-probe/` 隔离目录对本机 `~/.local/bin/agy`（`1.5.14`）完成 `agy acp --stdio` 实测，结论如下：

| 协议能力 | 实测方法与结果 | 关键约束与实现注意 |
| --- | --- | --- |
| 握手与版本 | `initialize`（`protocolVersion: 1`）返回 `agentInfo: {"name": "Antigravity ACP Server", "version": "1.5.14"}`，声明 `loadSession: true`、`promptCapabilities.image: true`、`sessionCapabilities: {resume, close, load, list, additionalDirectories}` | 复用标准库 `asyncio.create_subprocess_exec`，零第三方依赖；校验 `protocolVersion == 1` 与 `agentInfo.version` |
| 新建会话 | `session/new(cwd, mcpServers=[])` 返回 UUID `sessionId`、`models`（`availableModels`、`currentModelId`）、`modes`（`default`/`accept-edits`/`auto`/`plan`）、`configOptions`（`model`、`thought_level`、`mode`）、`_meta.antigravity.tier` | 不需拉起 iTerm2，秒级就绪；不修改全局 `~/.gemini/antigravity-cli/settings.json` |
| 会话列表 | `session/list(cwd)` 返回 `sessions: [{sessionId, cwd, title, updatedAt}]` | **重要实测发现**：服务端未严格按传入 `cwd` 过滤，且部分路径含 URL 编码（如 `%E4%B8%AD%E6%96%87`）；桥接必须严格做规范化与注册项目范围过滤 |
| 会话恢复与加载 | `session/resume` 恢复同会话且产生 `0` 条历史重放通知，后续 `session/prompt` 完整保留记忆（`PROBE_ALPHA_42`）；`session/load` 会重放历史通知 | 路由切换与聚焦使用 `session/resume` 避免误触发历史事件 |
| CLI 互通 | `agy --conversation <acp_session_id> --print='...'` 成功续接 ACP 创建的同一会话（返回 `PROBE_ALPHA_42`） | 桌面随时可用 `agy --conversation <id>` 查看／接手 |
| 文本执行 | `session/prompt` 流式推送 `agent_thought_chunk`、`agent_message_chunk`、`tool_call`、`tool_call_update`、`usage_update`、`session_info_update`、`config_option_update`，终态返回 `stopReason: "end_turn"` 与 `usage` | 仅汇总最终 `agent_message_chunk` 正文进入既有 Markdown 渲染与 Outbox |
| 单图入站 | `session/prompt` 传入 `[{"type": "image", "data": "<base64>", "mimeType": "image/png"}, {"type": "text", ...}]`，实测返回 `IMAGE_ACK` | 复用 `ImagePreparer` 解密／校验落盘路径，在工作线程读取并编码为 base64 传入 ACP；帧发送上限提升至 16 MiB |
| 模型与思考强度 | `session/set_config_option(configId="model"|"thought_level", value=...)` 及 `session/set_model(modelId=...)` 均实测生效，返回更新后的 `configOptions`（不同模型合法 `thought_level` 集合动态变化，如 `gemini-3.8-flash` 无 `xhigh`） | `/model set` 支持 `<基础模型> [强度]` 或直接传入完整 `modelId`；忙碌时拒绝，写入后核验返回值 |
| 中断 | `session/cancel` 通知实测使活跃 `session/prompt` 返回 `{"stopReason": "cancelled"}` | `/stop` 映射至 `session/cancel` 并等待终态确认 |
| 并发提交 | **重要实测发现**：活跃 `session/prompt` 未结束时并发发出第二条 `session/prompt` 会发生竞态／合并 | 桥接对同一 `agy` 会话严格串行（至多 1 个活跃 prompt），后续任务在 SQLite `received` 排队，经 `drain_admission` 顺序派发 |
| 权限审批与追问 | `ask_question` 工具在 ACP 中以 `tool_call_update(status="pending")` + `agent_message_chunk` 文本结束当轮（`end_turn`），用户下一条消息直接回复；`session/request_permission` 遵循 ACP v1 协议（`outcome: {outcome: "selected", optionId}` / `{outcome: "cancelled"}`） | 严禁传 `--dangerously-skip-permissions`；仅映射一次性 `allow_once`（`/approve`）与 `reject_once`/`cancelled`（`/deny`），永不映射 `allow_always`。注：当用户本机 Antigravity 全局权限策略已自动放行某命令时，`agy acp` 遵循用户个人配置不弹窗 |

---

## 三、 工程范围与红线约束

### 3.1 允许修改与新增的文件范围

- **新增模块**：
  - `src/wx_clawbot/agents/acp_rpc.py`：有界 stdio JSON-RPC 2.0 客户端（复用 `ConnectionLost` / `OutcomeUnknown` / `RpcError`）。
  - `src/wx_clawbot/agents/antigravity.py`：`AntigravityConnection` 后端实现（会话发现、创建、恢复、prompt、中断、单图编码、模型/状态控制、权限事件归一化）。
  - `tests/fixtures/antigravity-acp-contract.json`：脱敏最小 ACP 协议契约样本。
  - `tests/test_antigravity_acp.py`：ACP RPC、后端协议、权限审批、单图、模型切换、并发串行与崩溃保护单测。
  - `tests/test_multi_agent.py`：多后端路由、命令解析、独立升降级、同仓库 Codex + Antigravity 互斥锁与跨重启恢复测试。
- **修改模块**：
  - `src/wx_clawbot/agents/base.py`：扩展 `Capabilities` 字段（保持默认值向后兼容）。
  - `src/wx_clawbot/config.py`：支持可选 `default_agent`（默认 `"codex"`），保持 `version: 1` 配置向后兼容。
  - `src/wx_clawbot/commands.py`：扩展 `/cd`、`/new` 显式 Agent 参数解析，新增 `/agy status`、`/agent status`。
  - `src/wx_clawbot/routing.py`、`src/wx_clawbot/sessions.py`：`Target` 与 `SessionBinding` 增加 `agent: str = "codex"`，支持 `agy-v1` 绑定键且 100% 保持 Codex `native-v1`。
  - `src/wx_clawbot/catalog.py`、`src/wx_clawbot/subscriptions.py`：多后端发现、核验与按需订阅分发。
  - `src/wx_clawbot/interactions.py`：支持 ACP `session/request_permission` 一次性审批注册与应答。
  - `src/wx_clawbot/execution.py`、`src/wx_clawbot/execution_control.py`、`src/wx_clawbot/admission.py`、`src/wx_clawbot/admission_recovery.py`：多后端提交、Antigravity 单会话串行排队、事件消费、中断、审批与跨 Agent 仓库互斥。
  - `src/wx_clawbot/native_controls.py`：按目标 Agent 分发 `/model`、`/fast`、`/codex status`、`/agy status`、`/agent status`。
  - `src/wx_clawbot/controller.py`、`src/wx_clawbot/output.py`、`src/wx_clawbot/runtime_lifecycle.py`、`src/wx_clawbot/service.py`、`src/wx_clawbot/cli.py`、`src/wx_clawbot/project_registry.py`：多后端生命周期独立管理、`/cd`/`/new` 按 Agent 分流、`/sessions` 与 `/help` 更新、`doctor` 诊断扩展。
  - 文档同步：`README.md`、`ROADMAP.md`、`docs/protocol-baseline.md`、`docs/technical-decisions.md`、`docs/command-contract-proposal.md`、`docs/architecture-design.md`（及对应说明）。

### 3.2 严禁触碰的红线

1. 不破坏 SQLite `schema.VERSION = 6` 及既有 13 张表结构，不改动既有路由快照 `version: 2` 兼容解析，不改写历史 `unknown` 任务。
2. `unknown` 永不自动重放；投递重试不重新执行任务。
3. 绝不向 `agy acp` 传递 `--dangerously-skip-permissions`，绝不修改用户 `~/.gemini/antigravity-cli/settings.json` 或 `~/.codex/` 配置。
4. 绝不触碰 `openclaw-local`，绝不自动操作微信客户端，不将任何真实私人路径或对话标题写入仓库或测试 fixture。

---

## 四、 分阶段施工检查点（G01–G06）

- [x] **G01：ACP 协议层与 `AntigravityConnection` 后端实现**
  - 完成 `agents/acp_rpc.py`、`agents/antigravity.py` 与 `agents/base.py` 能力字段扩展。
  - 覆盖握手、会话新建/列表/严格目录过滤/恢复/关闭、prompt 流式收集、单图 base64 块构造、cancel、模型/思考强度读写与验证、权限事件封装。
- [x] **G02：配置、命令解析与身份/目录多后端抽象**
  - 完成 `config.py`（`default_agent`）、`commands.py`（`/cd <proj> [agy|codex]`、`/new [agy|codex] [标题]`、`/agy status`、`/agent status`）、`routing.py`、`sessions.py`、`catalog.py`、`subscriptions.py`、`output.py`。
  - 确保既有 Codex 行为、命令与 1041 项测试零回归。
- [x] **G03：执行、排队、审批、控制与多后端生命周期**
  - 完成 `interactions.py`（ACP 一次性审批）、`admission.py`（Antigravity 同会话串行 + 跨 Agent 同仓库互斥）、`execution.py`、`execution_control.py`、`native_controls.py`、`controller.py`、`runtime_lifecycle.py`、`service.py`、`cli.py`。
  - 实现 Codex 与 Antigravity 独立上下线：任一后端离线不影响另一后端可用。
- [x] **G04：离线单元与契约测试补齐**
  - 新增 `tests/fixtures/antigravity-acp-contract.json`、`tests/test_antigravity_acp.py`、`tests/test_multi_agent.py`。
  - 覆盖完整成功路径与关键失败路径（目录越界过滤、并发串行等待、权限拒绝/过期/仅一次性、单图入站、`/model` 读写与忙碌拒绝、`/fast` 与 `/attach` 明确拒绝、ACP 崩溃变 `unknown` 不重放、Codex 离线时 Antigravity 独立工作、Codex 与 Antigravity 同仓库互斥）。
- [x] **G05：隔离真实 `agy 1.5.14` 动态验证**
  - 在 `.tmp/` 隔离临时项目上运行真实 `AntigravityConnection` + `Controller` + `Execution` + `RuntimeState` 动态测试：验证真实 `/cd sample agy`、多轮文本、单图入站、`/model list` & `/model set`、`/agy status`、`/stop` 中断、`/sessions` 发现与清理。
- [x] **G06：全量检查与文档同步**
  - 运行 `.venv/bin/python scripts/check.py`（含全量 unittest、compileall、dependencies、diff、documents）。
  - 同步 `docs/protocol-baseline.md`、`docs/technical-decisions.md`（ADR-12）、`docs/command-contract-proposal.md`、`README.md`、`ROADMAP.md` 与本清单执行记录；清理本次 `.tmp/` 临时文件。

---

## 五、 执行记录区

- `2026-11-22 21:43` **[Phase 0 完成 & 清单定稿]**：完成本机 `agy 1.5.14` 隔离协议探针（`initialize`、`session/new`、`session/list`、`session/resume`、`session/load`、`session/prompt` 文本与 1x1 PNG 单图、`session/set_config_option`、`session/set_model`、`session/cancel`、`session/close`、并发 prompt 竞态及 `agy --conversation` 互通验证），形成本施工清单并进入 G01。
- `2026-11-22 21:54` **[G01–G03 实施完成]**：落地 `agents/acp_rpc.py`、`agents/antigravity.py` 及多后端配置、命令、目录、订阅、执行、审批、控制与独立生命周期改造；保持 SQLite schema 6 与路由快照 version 2 兼容。
- `2026-11-22 22:00` **[G04–G05 验证通过]**：新增 14 项离线单元与多 Agent 集成测试全部通过；隔离临时项目对真实 `agy 1.5.14` 运行 `/cd sample-live agy`、`/model list`、`/model set gemini-3.8-flash low`、`/agy status`、文本对话、单张 PNG 入站、`/stop` 中断与 `/sessions` 全部通过。
- `2026-11-22 22:11` **[G06 全量检查与文档同步]**：同步 `README.md`、`ROADMAP.md`、`docs/protocol-baseline.md`、`docs/technical-decisions.md`、`docs/command-contract-proposal.md`，清理 `.tmp/phase0-agy-probe/`，运行最终 `scripts/check.py` 全量回归核验。
- `2026-11-23 21:50` **[首轮手机微信联调 5 项修复 + 深度审计加固]**：根据首轮微信实测 6 张截图，修复 `/model list` 跟随聚焦（新增 `/model list [codex|agy]`）、`AntigravityConnection._pump()` 5 秒空闲超时静默退出与通知／返回顺序竞态（`StdioJsonRpc` 同步 `on_notification`）、`/sessions` 仅列当前活跃 `agy` 会话（过滤 `.tmp`、24 小时非聚焦闲置句柄自动回收不删历史、重启仅恢复上次聚焦会话）及 `agy --conversation <uuid>` 电脑接手提示；并完成深度代码审计修复 Codex `idle()` 跨后端检查、冷启动 `restore_agy_target()` 顺序恢复、`dispatch()` 同步登记 `turn_tasks`、`_pump()` 单条异常保护、断连审批 broker 失效与 `/status` 状态展示。离线 1059 项及本机 `agy 1.5.14` 6.5 秒空闲存活 + 文本 + 真实 64x64 红色 PNG 识别复验全部通过。
