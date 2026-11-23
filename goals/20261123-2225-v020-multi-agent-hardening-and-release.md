# V020：多 Agent 架构全面加固、全量审查闭环与 `0.2.0` 里程碑施工清单

## 一、 状态、目标与授权边界

- **编制时间**：2026-11-23 22:25（北京时间 `Asia/Shanghai`）。
- **当前状态**：`completed（G00–G06 及 0.2.0 标准收尾全部完成：提交 d87587e、main 快进、annotated tag v0.2.0 与远端双分支／标签原子推送核验通过；本机已切换至同一正式独立制品 0.2.0-d7356c74be88 并恢复就绪）`。
- **目标版本**：由当前 `0.1.17` 推进至 **`0.2.0`**（首个完成多 Agent 架构抽象、Codex 与 Antigravity 对称治理及完整运维闭环的次版本号里程碑）。
- **核心目标**：
  1. **全部 8 项架构与负责人审查问题 100% 闭环**：覆盖 2 项 P1、4 项 P2 与 2 项 P3，不留已知技术债或孤儿代码。
  2. **多 Agent 架构解耦与对称治理**：将分散在 `controller.py`、`execution.py`、`native_controls.py` 中的 `if agent_kind == "antigravity"` 分支收口到清晰的后端适配策略层，使 Codex 与 Antigravity 在会话生命周期、设置持久化审计（`ControlJournal`）、仓库占用运维解锁（`admission-release`）和独立无依赖启动上达到对称工程标准，为未来接入第 3 个 Agent 预留无侵入扩展点。
  3. **全量离线回归 + 隔离真机自测 + 跨文档与架构图同步**：补齐端到端测试盲区，更新受影响专题文档及派生 SVG 架构图，产出完整的 `0.2.0` 验证与交付归档文档。
  4. **保持既有稳定性与数据兼容**：SQLite `schema.VERSION = 6`、13 张核心表、路由快照 `version: 2`、既有 Codex 能力及历史 `unknown` 记录零破坏。
- **执行授权与红线**：
  - 本清单保存阶段**只新增本文件**，不修改业务源码、测试或生产服务。
  - 启动施工后，在 `dev` 分支按检查点 `G00` → `G06` 顺序推进，单次只执行本 Goal，默认不委派。
  - **Git 发布与生产切换边界**：完成 `G00` 至 `G06`（含版本推进至 `0.2.0`、冻结制品验证与交付文档准备）后暂停汇报；**不自动执行** `git commit`、合并 `main`、打 `v0.2.0` tag、推送远端或切换本机正式生产制品，待本人验收后由「完成收尾工作」明确触发标准收尾（若本人启动时一并明确授权标准收尾，再按 `AGENTS.md` 标准收尾顺序执行）。

---

## 二、 审查问题全量闭环映射表（8/8）

| 编号 | 级别 | 问题摘要 | 原位置 | 目标修复方案 | 所属检查点 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **R-01** | P1 | `admission-release` 无法处置 Antigravity 产生的 `unknown` 仓库占用锁 | `src/wx_clawbot/admission_ops.py`、`admission_recovery.py`、`cli.py` | `admission-report` 显式输出 `agent` 与 `thread_id`；`admission-release` 按任务 `agent` 分流：Codex 保持原生 `terminal_evidence()`，Antigravity 在前台停服 + 准确 `confirm_report` + 显式 `reason` 下，连接或核验 `agy` 非运行态并写入 `operator_verified_antigravity` 审计证据释放占用，任务仍保留 `unknown` 不改写 | **G01** |
| **R-02** | P1 | 跨文档与架构图未按 `docs/README.md` 维护触发矩阵完全同步 | `docs/architecture-design.md`、`docs/diagrams/`、`docs/native-controls.md`、`docs/operations.md`、`docs/testing.md`、`docs/product-design.md`、`config/config.example.json` | 全面同步多 Agent 架构、控制命令、运维参数、测试指南、配置模板与架构图（重新渲染受影响 SVG 并完成视觉检查） | **G05** |
| **R-03** | P2 | `watch_agy()` 断连时未清理 `catalog.sessions` 中的旧 `antigravity` 内存项 | `src/wx_clawbot/runtime_lifecycle.py` | 在 `watch_agy()` 的 `finally` 中同步清除 `controller.catalog.sessions` 中 `agent == "antigravity"` 的内存条目，保持内存快照与运行态实时一致 | **G01** |
| **R-04** | P2 | Antigravity `/model set` 未接入 `ControlJournal` 持久化写意图与部分写留痕 | `src/wx_clawbot/native_controls.py`、`src/wx_clawbot/control_journal.py` | 为 Antigravity `/model set` 接入同一 `ControlJournal`：写入前登记 `message_id` + `fingerprint` 意图，确认 `unchanged` / `confirmed` / `rejected` / `unknown` 状态并冻结回执，解决两步 RPC 部分写入无审计记录与重试幂等问题 | **G01** |
| **R-05** | P2 | `serve()` 与 `doctor()` 对 `codex_home` / `codex` 存在强前置依赖，阻碍纯 `agy` 独立运行 | `src/wx_clawbot/service.py`、`src/wx_clawbot/cli.py`、`src/wx_clawbot/runtime_lifecycle.py` | 当 `default_agent == "antigravity"` 或无 Codex 环境时允许 `codex_home` 缺省／不阻塞 `serve()` 启动（Codex 监听降级为不可用而不崩溃）；`doctor` 按配置 `default_agent` 与双运行时可用性给出准确健康判定，保持现有 Codex 默认场景 100% 行为兼容 | **G01** |
| **R-06** | P2 | 端到端回归测试盲区（微信单图走 `agy` 全链路、`watch_agy` 崩溃重连循环、真实 `agy` 审批边界） | `tests/test_multi_agent.py`、`tests/test_antigravity_acp.py`、`tests/test_admission_ops.py` | 补齐：1）微信入站单图经 `Controller` → `ImagePreparer` → `Execution` → `AntigravityConnection` 离线全链路测试（含「尚未进入桥接队列」）；2）`BridgeRuntime.watch_agy()` 崩溃重连 + `restore_agy_target()` + 断连清理 `catalog.sessions` 与审批 broker 集成测试；3）`admission-release` 处置 `agy` `unknown` 占用与 `ControlJournal` 幂等测试；4）纯 `agy` 无 `codex_home` 启动与 `doctor` 测试。真实 `agy` 审批若本机策略自动放行则如实记录边界，不伪造通过 | **G03 / G04** |
| **R-07** | P3 | 孤儿／死代码未清理（`agent_label()`、`list_all_sessions()` 与仅由其写入的 `self._listed`） | `src/wx_clawbot/agents/base.py`、`src/wx_clawbot/agents/antigravity.py` | 删除全仓零引用的 `agent_label()`；移除生产无调用的 `list_all_sessions()` 与孤立缓存 `self._listed`（保持 `/sessions` 仅列活跃会话的极简语义，同步收口 `test_antigravity_acp.py` 中对应测试至 `canonicalize_agy_cwd` / `list_active_sessions` / `evict_idle_sessions`） | **G02** |
| **R-08** | P3 | `controller.py`（930 行）、`antigravity.py`（855 行）、`execution.py`（840 行）、`native_controls.py`（646 行）体积偏大且存在散落 `if agent_kind == "antigravity"` 分支 | `src/wx_clawbot/agents/`、`controller.py`、`execution.py`、`native_controls.py` | 提取清晰的多 Agent 策略／适配层模块（如 `agents/registry.py` 或后端专属策略处理器，以及从 `antigravity.py` 拆分模型目录与控制辅助），收敛 `controller.py`、`execution.py`、`native_controls.py` 中的重复后端分流逻辑，确保新增第 3 个 Agent 无需散点侵入核心流程，同时严格保持既有外部行为与接口契约不变 | **G02** |

---

## 三、 代码边界与工程红线

### 3.1 允许修改与新增的文件范围

- **核心代码（`src/wx_clawbot/`）**：
  - `src/wx_clawbot/__init__.py`（版本号推进至 `0.2.0`）
  - `src/wx_clawbot/agents/base.py`、`src/wx_clawbot/agents/codex.py`、`src/wx_clawbot/agents/antigravity.py`、`src/wx_clawbot/agents/acp_rpc.py`
  - 可新增小型高内聚模块：`src/wx_clawbot/agents/registry.py`（或 `src/wx_clawbot/agents/controls.py` / `src/wx_clawbot/agents/antigravity_models.py`，视 G02 最小清晰拆分决定，绝不建空壳框架层）
  - `src/wx_clawbot/admission_ops.py`、`src/wx_clawbot/admission_recovery.py`
  - `src/wx_clawbot/controller.py`、`src/wx_clawbot/execution.py`、`src/wx_clawbot/execution_control.py`、`src/wx_clawbot/native_controls.py`
  - `src/wx_clawbot/runtime_lifecycle.py`、`src/wx_clawbot/service.py`、`src/wx_clawbot/cli.py`、`src/wx_clawbot/catalog.py`、`src/wx_clawbot/sessions.py`
- **构建与配置模板**：
  - `pyproject.toml`（版本号推进至 `0.2.0`）
  - `config/config.example.json`（保留兼容结构或补充清晰文档说明，确保现有 `test_config.py` / `scripts/check.py` 全通过）
- **测试文件（`tests/`）**：
  - `tests/test_antigravity_acp.py`、`tests/test_multi_agent.py`、`tests/test_admission_ops.py`、`tests/test_native_controls.py`、`tests/test_cli.py`（以及必要的专项回归文件）
- **文档与架构图**：
  - `README.md`、`ROADMAP.md`
  - `docs/architecture-design.md` 及对应重新渲染的 `docs/diagrams/architecture-F0*.svg`
  - `docs/native-controls.md`、`docs/operations.md`、`docs/testing.md`、`docs/protocol-baseline.md`、`docs/command-contract-proposal.md`、`docs/technical-decisions.md`、`docs/product-design.md`、`docs/README.md`
  - 本施工清单及最终交付验证记录 `docs/validation/v020-multi-agent-release.md`

### 3.2 严禁触碰的工程红线

1. **禁止改动数据库 Schema 与快照版本**：SQLite `schema.VERSION` 保持 `6`，13 张表结构与约束不变；路由快照保持 `version: 2` 且兼容 `version: 1` 读取；绝不自动迁移或覆盖生产账本。
2. **禁止自动重放 `unknown`**：`unknown` 任务保持待核对，投递重试不重新执行任务；`admission-release` 仅释放仓库占用并留审计证据，严禁改写任务执行结果。
3. **禁止降低安全与权限边界**：`agy acp --stdio` 绝不传 `--dangerously-skip-permissions`；审批仅映射一次性 `allow_once` / `reject_once` / `cancelled`；不修改 `~/.codex/` 或 `~/.gemini/antigravity-cli/settings.json`。
4. **禁止触碰隔离资源**：绝不读取、引用或修改 `openclaw-local`；不自动操作微信客户端或未经授权发送微信测试消息；不将任何私人路径、真实项目名、真实对话标题或凭据写入仓库／fixture／文档。
5. **禁止破坏 Codex 存量能力**：所有既有 1041+ 项 Codex 单元与契约测试必须 100% 保持通过，不得删除、跳过或弱化断言。
6. **禁止原地覆盖运行中制品**：隔离测试产物统一放 `.tmp/v020-<step>/` 并在完工后清理；构建与验证使用独立目录，不热改当前运行中的 `local.wx-clawbot` 制品目录。
7. **禁止手工修改派生 SVG**：架构图源码仅维护在 `docs/architecture-design.md` 的 Mermaid 代码块，修改后必须用工具重新渲染并做视觉核查，不手改 SVG 或嵌入系统字体。
8. **禁止越权发布**：未获明确「完成收尾工作」或对应授权前，不执行 `git commit`、合并 `main`、创建 `v0.2.0` tag、推送远端或切换生产服务。

---

## 四、 分阶段施工步骤（G00–G06）

### G00：基线冻结与现状核对

- [x] **G00.1 记录施工前基线**
  - 检查 `git branch --show-current`（应为 `dev`）、`git status --short`、`git diff --stat`。
  - 确认当前离线测试基数（1059 项）与当前运行候选（`0.1.17-ff62cf1d3439`）互不干扰。
- [x] **G00.2 核对关键接口依赖**
  - 核对 `tests/test_admission_ops.py`、`tests/test_cli.py`、`tests/test_config.py`、`tests/test_native_control_writes.py` 对 mock 对象的属性预期，避免重构破坏既有 `SimpleNamespace` 测试桩。

---

### G01：P1/P2 核心能力补齐与对称治理（R-01、R-03、R-04、R-05）

- [x] **G01.1 实现 `admission-release` 对 Antigravity `unknown` 占用的受控审计解锁（R-01）**
  - `admission_ops.report()` 在 `occupancies` 中补充 `agent` 与 `thread_id` 字段（不破坏现有字段键名）。
  - `admission_ops.release()` 在校验前台消费者锁、schema、`confirm_report` 摘要与 `reason` 之后，按 `rows` 的 `agent` 分流：
    - 混合 `codex` 与 `antigravity` 同批记录时 fail-closed 拒绝；
    - `codex` 保持原有 `CodexConnection` + `terminal_evidence()` 严格核验逻辑不变；
    - `antigravity` 在确认前台消费者已停止（持有 `channel-consumer.lock` 即证明无桥接 `agy acp` 子进程在跑该会话）并校验任务标识与目录规范性后，生成 `kind="operator_verified_antigravity"` 审计证据（含 `thread_id`、`operator_reason`、`operator_report`、`verified_consumer_stopped=True`），调用 `release_rows(..., reason="operator_verified_antigravity")` 释放占用并保持任务 `state == "unknown"` 不改写。
- [x] **G01.2 `watch_agy()` 断连时清理 `catalog.sessions` 残留项（R-03）**
  - 在 `runtime_lifecycle.py` `watch_agy()` 的 `finally` 块中，同步移除 `controller.catalog.sessions` 中 `s.target.agent == "antigravity"` 的条目（保留 Codex 项与 `subscriptions.bound` 审计关联语义不受损）。
- [x] **G01.3 Antigravity `/model set` 接入 `ControlJournal` 持久化幂等与留痕（R-04）**
  - 在 `native_controls.py` 的 Antigravity 写入路径接入 `ControlJournal`：
    - 校验 `message_id` 并计算含 `agent`、`model`、`reasoning`、`session_id`、`cwd` 的 `fingerprint`；
    - 已有记录时直接校验指纹并返回既有回执或 `unknown` 提示（不重放）；
    - 发送 RPC 前先 `journal.begin()` 落盘；若目标模型与思考等级均与当前一致则 `journal.finish(..., "unchanged", ...)`；
    - 写入成功后回读核验模型与思考等级并 `journal.finish(..., "confirmed", ...)`；若第二步失败、超时或连接异常导致状态不确定，则落盘 `unknown` 并明确提示「先查 `/model` 或 `/agy status`，不自动重放或回滚」。
- [x] **G01.4 解耦 `serve()` 与 `doctor()` 对 Codex 的强前置依赖（R-05）**
  - `service.py`：`codex_home` 不存在时，仅在 `agy_executable` 可用且（`default_agent == "antigravity"` 或明确允许 Codex 缺席）时降级运行（`BridgeRuntime.run()` 保持等待／报告 Codex 不可用，不拖垮 `watch_agy()` 与微信通道）；若两者均不可用则明确报错退出。
  - `cli.py`：`doctor()` 保持既有返回字段完全向后兼容；当 `config` 指定 `default_agent == "antigravity"` 且 `agy` 可用时，即使本机未运行 Codex daemon 也能清晰区分 `codex` 不可用与整体多 Agent 可用状态（需确保既有 `test_cli.py` 全部零回归）。

---

### G02：P3 死代码清理与多 Agent 架构解耦重构（R-07、R-08）

- [x] **G02.1 清理死代码与未用缓存（R-07）**
  - 删除 `src/wx_clawbot/agents/base.py` 中零引用的 `agent_label()` 与 `AGENT_LABELS`（如无他用）。
  - 删除 `src/wx_clawbot/agents/antigravity.py` 中生产无调用的 `list_all_sessions()` 与仅由其写入的 `self._listed`，并精简 `inspect()` / `resume_session()` 中对 `self._listed` 的无效回退分支。
- [x] **G02.2 拆分与收口多 Agent 策略适配层（R-08）**
  - **拆分 `antigravity.py`**（目标将主连接文件从 855 行降至约 550 行以内）：将无状态模型目录解析、配置提取、路径规范化与图片编码辅助提取至独立子模块 `src/wx_clawbot/agents/antigravity_codec.py`（或 `antigravity_models.py`），使 `antigravity.py` 聚焦会话与 ACP 协议状态机。
  - **收口后端分流逻辑**：引入轻量 `BackendPolicy` / 后端调度辅助（如 `src/wx_clawbot/agents/registry.py`），统一封装：
    - 运行时就绪文案、队列名称文案、电脑接手提示格式化、受管会话键计算；
    - 目标后端解析顺序（`command.agent` → `target.agent` → `default_agent` → 唯一就绪后端）；
    - `controller.py` 中 `/cd`、`/new` 的创建与复用流程按策略委托，减少 `controller.py` 体积与重复分支；
    - `native_controls.py` 中共享验证／`ControlJournal` 骨架，减少 Codex 与 Antigravity 控制分支的重复样板。
  - **重构红线**：仅做等价结构收敛，不引入重量级插件框架或动态导入魔法，不改变任何既有测试依赖的公开方法签名。

---

### G03：全量测试补齐与离线验证（R-06）

- [x] **G03.1 补充 R-01 至 R-05 专项回归测试**
  1. `tests/test_admission_ops.py`（或 `test_multi_agent.py`）：
     - `agy` `unknown` 任务 `admission-report` 输出 `agent: "antigravity"` 与准确摘要；
     - `admission-release --apply` 在停服与匹配摘要下释放占用、保留 `state == "unknown"`、写入审计证据；
     - 关键失败路径：摘要不匹配拒绝、缺少理由拒绝、消费者锁占用拒绝、混合 Codex + Antigravity 批次拒绝。
  2. `tests/test_multi_agent.py`：
     - **微信单图 → Antigravity 端到端离线链路**：验证入站图片经 `Controller.prepare()` → 返回「尚未进入桥接队列」→ `ImagePreparer` 准备 → `Execution.drain_admission()` → `AntigravityConnection.submit_idle()` 携带合法 `image` 块 → 终态正文入 Outbox；
     - **`BridgeRuntime.watch_agy()` 完整生命周期集成测试**：启动连接 → 派发与审批注册 → 模拟 ACP 子进程崩溃断连 → 核验 `catalog.sessions` 已清空 `antigravity` 项、`ACP_APPROVAL` broker 已断开、任务转 `unknown` 且 Codex 正常 → 模拟自动重连 → `restore_agy_target()` 自动恢复原聚焦会话；
     - **Antigravity `/model set` `ControlJournal` 测试**：验证同 `message_id` 重放直接返回原冻结回执（RPC 仅发 1 次）、同 `message_id` 不同参数拒绝、无变更返回 `unchanged`、第二步失败落盘 `unknown` 且不重试；
     - **纯 `agy` 独立启动测试**：`codex_home` 不存在时，配置 `default_agent = "antigravity"` 的 `serve()` 可正常初始化与运行。
  3. `tests/test_antigravity_acp.py`：
     - 更新原 `list_all_sessions` 测试为 `canonicalize_agy_cwd` + `list_active_sessions` + `.tmp` 过滤 + 24 小时闲置回收测试，确保无死代码残留引用。
- [x] **G03.2 运行完整离线验证门禁**
  - 执行 `.venv/bin/python scripts/check.py --report-dir .tmp/v020-check`（含全量 `unittest`、`compileall`、`pip check`、`git diff --check`、`documents`）。
  - 预期：发现测试数 `>= 1068` 项，0 失败、0 错误、0 跳过，全部 5 项检查 exit 0。

---

### G04：本机隔离动态与真机自测步骤

以下自测全部在 `.tmp/v020-live-verify/` 隔离目录运行，**不触碰生产账本、不发送未经授权的微信消息、不改动用户全局配置**：

- [x] **G04.1 本机 `agy 1.5.14` 隔离全功能自测**
  1. 启动真实 `AntigravityConnection.connect()`，刻意**空闲等待 6.5 秒**确认 `_pump_task` 存活；
  2. `/cd sample-v020 agy`：验证返回独立 ```` ```sh\nagy --conversation <uuid>\n``` ```` 代码块；
  3. `/model list`（在 Codex 同时在线时）：验证输出 `Antigravity 可用模型`；
  4. `/model set gemini-3.8-flash low`：验证写入成功且在私有 `native-controls/` 下生成对应 `ControlJournal` 审计文件，重复发送同 `message_id` 不触发第二次 RPC；
  5. `/sessions`：验证只列活跃会话并正确标注 `〔agy〕` / `〔codex〕`；
  6. 发送文本指令：验证返回准确正文；
  7. 发送真实 64×64 红色 PNG 单图：验证返回准确颜色识别正文；
  8. `/stop` 中断长输出任务：验证返回 `interrupted` 终态；
  9. 模拟 `agy` 异常退出变为 `unknown` 后，在隔离状态目录执行真实 CLI `wx-clawbot admission-report` 与 `wx-clawbot admission-release --apply`，验证占用释放且任务仍保持 `unknown`。
- [x] **G04.2 纯 `agy` 无 `codex_home` 隔离自测**
  - 传入不存在的 `--codex-home .tmp/v020-live-verify/nonexistent-codex` 与 `default_agent: "antigravity"`，验证 `BridgeRuntime` 启动不崩溃且 `antigravity` 进入 `ready`。
- [x] **G04.3 清理隔离自测目录**
  - 验证完成后立即删除 `.tmp/v020-live-verify/` 与 `.tmp/v020-check/`。

---

### G05：全量跨文档同步、架构图重渲染与视觉检查（R-02）

对照 [docs/README.md](../docs/README.md) 维护触发矩阵逐一更新并核对跨文档一致性：

- [x] **G05.1 更新架构文档与重渲染派生架构图**
  - 更新 [docs/architecture-design.md](../docs/architecture-design.md)：
    - 顶部版本说明更新至 `0.2.0`（多 Agent 架构：Codex + Antigravity）；
    - 第 1、2、3 节同步多 Agent 上下文、进程边界（`agy acp --stdio` 独立子进程）与模块协作表；
    - 更新第 8 节为「多 Agent 适配与扩展架构」，准确反映当前 `agents/` 分层与 `Capabilities` 门禁；
    - 更新 F01（系统上下文）、F02（运行进程与部署）、F03（模块协作）Mermaid 源码，加入 Antigravity ACP 路径。
  - 重新渲染 `docs/diagrams/architecture-F01.svg`、`architecture-F02.svg`、`architecture-F03.svg`（不手工改 SVG、不嵌入系统字体），并对渲染结果进行实际图像视觉检查（确认文字无重叠、无截断、连线清晰）。
- [x] **G05.2 更新全部受影响专题与操作文档**
  - [docs/native-controls.md](../docs/native-controls.md)：补充 Antigravity `/model` 读写、`/model list [codex|agy]`、`/agy status`、`/agent status`、`ControlJournal` 对称机制、`/fast` 拒绝边界及能力对照。
  - [docs/operations.md](../docs/operations.md)：补充 `--agy-executable`、`--default-agent`、纯 `agy` 独立运行前置、`status` 三组件输出、`admission-release` 处置 `agy` `unknown` 占用的操作步骤。
  - [docs/testing.md](../docs/testing.md)：补充多 Agent 与 ACP 离线回归入口、本机 `agy` 隔离真机自测步骤与边界（区分离线通过与真实权限审批未真机触发的边界）。
  - [docs/product-design.md](../docs/product-design.md) / [docs/protocol-baseline.md](../docs/protocol-baseline.md) / [docs/command-contract-proposal.md](../docs/command-contract-proposal.md) / [docs/technical-decisions.md](../docs/technical-decisions.md)：复核共同事实，更新 `0.2.0` 能力基线与 ADR-12（补充策略解耦与 `admission-release` 决策）。
  - [config/config.example.json](../config/config.example.json) 与 [README.md](../README.md)：同步 `0.2.0` 版本说明、多 Agent 配置说明与命令示例。

---

### G06：版本推进至 `0.2.0`、冻结制品验证与交付归档

- [x] **G06.1 版本号推进至 `0.2.0`**
  - 更新 `pyproject.toml` (`version = "0.2.0"`) 与 `src/wx_clawbot/__init__.py` (`__version__ = "0.2.0"`)；
  - 刷新开发安装元数据：`.venv/bin/python -m pip install --no-deps -e .`。
- [x] **G06.2 全量检查 + 冻结制品构建与同包验证**
  - 运行 `.venv/bin/python scripts/check.py` 全部通过；
  - 使用 `scripts/build_release.py` 构建 `0.2.0` 独立非 editable 冻结制品至 `.tmp/v020-release-verify/`，核对 `release.json`（`version == "0.2.0"`、`editable == false`、`source_sha256`、`wheel_sha256`、`lock_sha256`），并使用隔离 `.venv` 运行 `wx-clawbot --version` 与同包核心测试验证；
  - 执行公开内容与隐私扫描：核对 `git diff`、新建文件及 wheel/sdist 清单中零私人路径、零真实项目名、零凭据／token。
- [x] **G06.3 编写交付验证文档并同步 `ROADMAP.md`**
  - 新建交付文档 `docs/validation/v020-multi-agent-release.md`，记录：
    - `0.2.0` 变更摘要与 8 项审查问题逐项闭环证据；
    - 离线全量测试数、耗时与 `scripts/check.py` 结果；
    - 本机 `agy 1.5.14` 隔离真机自测与纯 `agy` 启动自测脱敏证据；
    - 架构图重渲染与视觉复核结论；
    - 明确的验收边界声明（如真实 `agy` 权限弹窗尚未因本机策略触发、手机微信二轮实测已验证核心链路等，不夸大覆盖面）；
    - `0.2.0` 冻结制品摘要（`source_sha256` / `wheel_sha256` / `lock_sha256`）。
  - 同步更新 [ROADMAP.md](../ROADMAP.md)（严格保持「最近完成」与「最近验证」各 `<= 20` 条，北京时间通过 `TZ=Asia/Shanghai date "+%Y-%m-%d %H:%M"` 获取）与本施工清单执行记录区；
  - 再次运行 `.venv/bin/python scripts/check.py` 确认全部通过后，清理 `.tmp/v020-release-verify/` 并汇报本人等待收尾指示。

---

## 五、 验收标准与关键失败路径清单

| 类别 | 验收项 | 预期结果 | 关键失败路径（必须验证拒绝／保护） |
| :--- | :--- | :--- | :--- |
| 运维解锁 | `admission-release` 处置 `agy` `unknown` | 前台停服 + 核对摘要后释放占用，任务保持 `unknown`，写入审计记录 | 消费者仍在运行、摘要过期、缺少理由、混入 Codex 任务时一律拒绝 |
| 设置审计 | `agy` `/model set` 走 `ControlJournal` | 写前落盘、写后回读核验、冻结回执；同 `message_id` 重放幂等不重发 RPC | 同 `message_id` 不同参数拒绝；第二步 `thought_level` 失败留痕 `unknown` 不自动回滚／重放 |
| 独立运行 | 纯 `agy` 缺省 `codex_home` 启动 | `default_agent="antigravity"` 且无 `~/.codex` 时服务正常启动，`antigravity` ready | `codex` 与 `agy` 均不可用时明确失败退出 |
| 生命周期 | `watch_agy()` 崩溃与自动重连 | 断连清 `catalog.sessions` + 断审批 broker + 仅 `agy` 任务转 `unknown`；重连自动恢复聚焦 `agy` 会话 | Codex 运行中任务不受影响；旧 `ACP_APPROVAL` 请求不可再应答 |
| 多 Agent 重构 | 策略层拆分后全量回归 | 代码行数与分支收敛，100% 既有 Codex 与 Antigravity 行为不变 | 既有 `SimpleNamespace` 桩测试零回归，全量 `unittest` 零失败零跳过 |
| 微信单图 | 单图入站走 `agy` 全链路 | 回执「尚未进入桥接队列」→ 解密落盘 → base64 提交 ACP → 准确识别文本入 Outbox | 多图／非 PNG/JPEG 拒绝；准备异常不拖垮主循环 |
| 文档与制品 | 跨文档 + 架构图 + `0.2.0` 冻结包 | `scripts/check.py` 全绿，F01–F03 SVG 视觉清晰，`0.2.0` wheel 隐私扫描零泄露 | 不出现未同步单后端表述、失效链接或私人信息泄露 |

---

## 六、 施工后交付文档清单

1. **本施工清单（完成态）**：[goals/20261123-2225-v020-multi-agent-hardening-and-release.md](20261123-2225-v020-multi-agent-hardening-and-release.md) -- 勾选全部检查点并附逐阶段执行记录。
2. **版本验证与发布归档**：`docs/validation/v020-multi-agent-release.md` -- 完整记录 8 项问题闭环证据、离线／真机／冻结包验证结果、架构图复核与能力边界（后续标准收尾时追加 Git commit / tag / 生产部署结果）。
3. **现行架构与派生图**：[docs/architecture-design.md](../docs/architecture-design.md) + 重渲染的 `docs/diagrams/architecture-F01.svg`、`architecture-F02.svg`、`architecture-F03.svg`。
4. **同步更新的核心与专题文档**：
   - [README.md](../README.md)（`0.2.0` 入口说明）
   - [ROADMAP.md](../ROADMAP.md)（进度快照、最近完成与最近验证）
   - [docs/native-controls.md](../docs/native-controls.md)（双后端控制与 `ControlJournal` 契约）
   - [docs/operations.md](../docs/operations.md)（多 Agent 启动、诊断与 `admission-release` 运维操作卡）
   - [docs/testing.md](../docs/testing.md)（多 Agent 离线与隔离真机测试指南）
   - [docs/protocol-baseline.md](../docs/protocol-baseline.md) / [docs/command-contract-proposal.md](../docs/command-contract-proposal.md) / [docs/technical-decisions.md](../docs/technical-decisions.md) / [docs/product-design.md](../docs/product-design.md) / [config/config.example.json](../config/config.example.json)

---

## 七、 执行记录区

- `2026-11-23 22:25` **[清单编制完成]**：基于架构师与项目负责人整体审查报告（2 项 P1、4 项 P2、2 项 P3），形成 `0.2.0` Goal 模式完整施工清单；当前未修改业务代码或生产状态，待本人审阅确认后启动 `G00`。
- `2026-11-23 22:37` **[G00–G03 实施与回归通过]**：完成 `admission-release` Antigravity 审计解锁、`watch_agy()` 断连清理 `catalog.sessions`、Antigravity `/model set` 接入 `ControlJournal`、解耦纯 `agy` 启动与 `doctor` 判定、清理死代码 `agent_label()` 与 `list_all_sessions()`、拆分 `agents/antigravity_codec.py` 与 `agents/registry.py` 并补齐 5 项端到端回归测试（95 项专项回归全绿）。
- `2026-11-23 22:39` **[G04 隔离真机自测通过]**：本机 `agy 1.5.14` 隔离 9 步自测（含 6.5 秒空闲存活、可复制 `sh` 代码块、`/model list`、`/model set` + `ControlJournal`、`V020_LIVE_OK`、64×64 红色 PNG 识别、`admission-release` 释放 `agy` `unknown` 占用、纯 `agy` 无 `codex_home` 独立启动）全部通过，临时目录已清理。
- `2026-11-23 22:45` **[G05–G06 文档、架构图、`0.2.0` 冻结包与归档完成]**：同步全量受影响文档并重渲染视觉复核 F01–F03 SVG，版本推进至 `0.2.0`，完成独立非 editable 冻结制品（`source e11a11fb294a` / `wheel d7356c74be88`）验证、隐私扫描及 `docs/validation/v020-multi-agent-release.md` 归档，同步 `ROADMAP.md` 并执行最终全量 `scripts/check.py`。
- `2026-11-23 23:20` **[`0.2.0` 标准收尾交付完成]**：功能提交 `d87587e` 落盘 `dev`、`main` 快进、创建 annotated tag `v0.2.0`（`6422db13`）并原子推送远端独立核验一致；停服完成 13 表一致性备份后，本机切换至同一正式独立制品 `0.2.0-d7356c74be88`，1.307 秒恢复就绪（PID `79593`），旧数据与 12 注册项完整保护。
