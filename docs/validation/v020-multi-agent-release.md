# V020：多 Agent 架构全面加固与 `0.2.0` 验证归档

- **记录时间**：2026-11-23 22:45（北京时间 `Asia/Shanghai`）
- **版本与存储基线**：`0.2.0` / SQLite `schema 6` / 路由快照 `version 2`
- **对应施工清单**：[V020 施工清单](../../goals/20261123-2225-v020-multi-agent-hardening-and-release.md) 、[AGY01 初始清单](../../goals/20261122-2143-antigravity-agent-support.md)
- **当前交付阶段**：`0.2.0` 已正式完成标准收尾 -- 功能提交 `d87587e` 已合入 `main`、固定 annotated tag `v0.2.0`（`6422db13`）、双分支与标签原子推送至 `origin` 并独立核验一致；本机托管服务 `local.wx-clawbot` 已切换至同一冻结制品 `0.2.0-d7356c74be88` 并恢复就绪。

---

## 一、 8 项审查问题逐项闭环证据（8/8）

| 编号 | 级别 | 闭环改动摘要 | 验证证据 |
| :--- | :--- | :--- | :--- |
| **R-01** | P1 | `occupancy.release_rows()` 新增 `operator_verified_antigravity` 审计证据通道；`admission_ops.report()` 输出 `agent` 字段；`admission_ops.release()` 在消费者锁（停服）、准确 `confirm_report` 摘要与显式理由下释放 Antigravity `unknown` 占用并保留 `state == "unknown"`，拒绝混合 Agent 批次与运行中消费者 | `test_admission_ops.py` 11/11 通过；`G04_8_ADMISSION_RELEASE_AGY_OK` 实测通过 |
| **R-02** | P1 | 同步更新 `README.md`、`ROADMAP.md`、`docs/architecture-design.md`、`docs/native-controls.md`、`docs/operations.md`、`docs/testing.md`、`docs/product-design.md`、`docs/technical-decisions.md`（ADR-12）、`docs/command-contract-proposal.md`、`docs/protocol-baseline.md`、`config/config.example.json`；使用隔离 Mermaid CLI 12.2.0 重渲染 `architecture-F01.svg`、`F02.svg`、`F03.svg` 并逐张视觉检查通过 | `scripts/check.py` `documents` 通过；三幅 PNG 人工／视觉检查无遮挡无裁切 |
| **R-03** | P2 | `runtime_lifecycle.py` `watch_agy()` `finally` 断连时同步清除 `controller.catalog.sessions` 中的 `antigravity` 残留条目并断开 `ACP_APPROVAL` broker | `test_watch_agy_crash_cleans_catalog_and_brokers_and_reconnect_restores_focus` 通过 |
| **R-04** | P2 | `native_controls.py` `_write_antigravity()` 接入同一 `ControlJournal`（`native-controls/`）：写前落盘 `intent`、同值返回 `unchanged`、同 `message_id` 重放返回冻结回执不重发 RPC、异参数拒绝、部分写入失败留痕 `unknown` 不自动回滚／重放 | `test_agy_model_set_uses_control_journal_for_idempotency_and_partial_write_unknown` 通过；`G04_4_MODEL_SET_JOURNAL_OK` 实测生成 `confirmed` 审计文件 |
| **R-05** | P2 | `service.py` 允许 `agy_executable` 可用时 `codex_home` 缺省不报错；`BridgeRuntime.run()` 在无 `codex_home` 且无 `socket` 时静默维持 `unavailable` 不阻塞 `watch_agy()`；`cli.doctor()` 在配置 `default_agent="antigravity"` 时按 Antigravity 可用性判定健康状态 | `test_default_agent_antigravity_doctor_passes_without_codex` 通过；`G04_9_PURE_AGY_NO_CODEX_HOME_OK` 实测通过 |
| **R-06** | P2 | 补齐微信单图入站经 `ImagePreparer` → `drain_admission` → `AntigravityConnection` 全链路回归、`watch_agy()` 崩溃清理与重连恢复回归、`ControlJournal` 幂等／部分写回归、`admission-release` 与纯 `agy` 诊断回归 | 新增 5 项高价值端到端回归测试，全量离线测试增至 1064 项 |
| **R-07** | P3 | 删除 `agents/base.py` 零引用死代码 `agent_label()` / `AGENT_LABELS`，删除 `agents/antigravity.py` 生产无调用的 `list_all_sessions()` 与孤立缓存 `self._listed` | 全仓零残留引用，测试全部通过 |
| **R-08** | P3 | 提取 `src/wx_clawbot/agents/antigravity_codec.py` 与 `src/wx_clawbot/agents/registry.py` 收口无状态编解码、模型目录构建、后端标签、队列／运行时文案、受管会话键、电脑接手代码块及控制后端解析策略，`antigravity.py` 由 855 行收敛至约 470 行 | 全量 1064 项离线测试与非 editable 冻结包验证零回归 |

---

## 二、 验证结果汇总

### 1. 离线全量门禁（`scripts/check.py`）
- `unittest`：**1064 项**（0 失败 / 0 错误 / 0 跳过）
- `compile`（`compileall -q src tests scripts`）：exit 0
- `dependencies`（`pip check`）：exit 0（零新增第三方依赖）
- `diff`（`git diff --check`）：exit 0
- `documents`（JSON、Markdown 相对链接与标题锚点、`pyproject.toml` 与 `__init__.py` 版本一致、`ROADMAP.md` 条数上限）：exit 0

### 2. 本机 `agy 1.5.14` 隔离真机自测（`.tmp/v020-live-verify/`，已清理）
- `G04_1_IDLE_SURVIVAL_OK`：连接 `agy 1.5.14` 后刻意空闲等待 6.5 秒，`_pump_task` 保持存活未退出。
- `G04_2_CD_FENCED_HANDOFF_OK`：`/cd sample-v020 agy` 返回带复制入口的独立 ```` ```sh\nagy --conversation <uuid>\n``` ```` 代码块。
- `G04_3_MODEL_LIST_OK`：在 Codex 同时在线时，`/model list` 准确跟随聚焦 `agy` 返回 Antigravity 模型目录。
- `G04_4_MODEL_SET_JOURNAL_OK`：`/model set gemini-3.8-flash low` 写入确认，并在 `native-controls/` 下落盘 `phase == "confirmed"` 审计 JSON。
- `G04_5_SESSIONS_TAG_OK`：`/sessions` 仅列当前活跃会话并带 `〔agy〕` 标签。
- `G04_6_TEXT_OK`：文本指令准确返回正文 `V020_LIVE_OK`。
- `G04_7_PNG_OK`：64×64 红色 PNG 单图识别准确返回「红色」。
- `G04_8_ADMISSION_RELEASE_AGY_OK`：模拟 `agy` `unknown` 占用任务，真实运行 `admission_ops.report()` 与 `admission_ops.release(..., apply=True)` 成功释放占用且任务保持 `unknown`。
- `G04_9_PURE_AGY_NO_CODEX_HOME_OK`：传入无 `codex_home` 配置，`BridgeRuntime` 稳定进入 `antigravity: ready` / `native: unavailable`。

### 3. 架构图重渲染与视觉复核
- 工具：隔离安装于 `.tmp/v020-diagram-render/`（已清理）的 Mermaid CLI `12.2.0` + 本机无界面 Chrome；不嵌入系统字体、不手工修改 SVG。
- 源摘要：
  - `docs/diagrams/architecture-F01.svg`：`source SHA256 d3b90cb4c33e`（34,437 B）
  - `docs/diagrams/architecture-F02.svg`：`source SHA256 b2e80a0c9348`（39,977 B）
  - `docs/diagrams/architecture-F03.svg`：`source SHA256 d8c458d5c18`（48,808 B）
- 视觉检查：三幅 2x PNG 逐张核对，中文标签、边界框、双后端连线及箭头全部清晰完整，无重叠或裁切。

### 4. `0.2.0` 独立非 editable 冻结制品与隐私核验
- 构建入口：`scripts/build_release.py --output .tmp/v020-release-verify --apply`（验证后已清理）
- 版本：`0.2.0`、`schema: 6`、`editable: false`
- `source_sha256`：`e11a11fb294a27acfc0ee7f05eba03b5b5fe7ee2ca9453abb498b529bf36b1cf`
- `wheel_sha256`：`d7356c74be8805d82692442a06208401a588bc944f75d53e7b8afe047b05d903`
- `lock_sha256`：`0bea01a999e40181a487494415f90ce0ce198a0d6e7df4b99cb0f18ccb78db96`
- 隔离冻结 `.venv` 实测 `wx-clawbot --version` 返回 `0.2.0`，`-I` 模式运行 `test_multi_agent.py` 12/12 通过。
- 隐私扫描：全量 `git diff` 与新增模块扫描私人路径、真实项目名与凭据模式，结果为 0 处匹配（`PRIVACY_CLEAN`）。

---

## 三、 验收范围与明确边界声明

- **已验证真机微信链路**：本人已于 2026-11-23 在手机／桌面微信对候选版本完成 `/cd <proj> agy`、可复制 `sh` 代码块、`/model list`、`/model set`、`/agy status`、文本对话、单图上下文识别、`/stop` 中断、`/fast` 拒绝、`/sessions` 仅列活跃会话与 `〔agy〕`/`〔codex〕` 标签实测通过。
- **未覆盖／保留边界**：真实 `agy 1.5.14` 进程触发 `session/request_permission` → 微信 `/approve` `/deny` 因本机用户全局策略未弹窗，当前仅通过离线 ACP 协议与 `InteractionBroker` 回归验证，本记录不将其扩写为已通过真机弹窗审批验收。
- **正式发布与本机切换结果（2026-11-23 23:20 北京时间）**：
  - **Git 发布与远端核验**：发布提交 `d87587e89b2edc02953d59ccc357fa2b8cfe4d22`（`d87587e`）已在 `dev` 提交、`main` 正常快进合并，并在 `main` 上创建 annotated tag `v0.2.0`（标签对象 `6422db13228735a1783e6ab50364f091de2457de`，解引用至 `d87587e89b2edc02953d59ccc357fa2b8cfe4d22`）；双分支与 `v0.2.0` 原子推送至 `origin` 后经 `git ls-remote` 独立核验完全一致，既有历史 tag 未移动。
  - **一致性备份**：正常停服并确认 `stopped` 与 `consumer_busy: false` 后，通过 SQLite `Connection.backup` 完成 13 表一致性备份（`schema 6`、`PRAGMA integrity_check=ok`、`foreign_key_check` 0 异常，161 条任务、894 条 Outbox），同步备份私有配置、凭据、`native-controls/` 与 `local.wx-clawbot.plist`（目录 `0700` / 文件 `0600`）。
  - **正式制品切换与复核**：将同一已验冻结包安装至独立非 editable 目录 `0.2.0-d7356c74be88`（`source_sha256: e11a11fb294a...`、`wheel_sha256: d7356c74be88...`、`lock_sha256: 0bea01a999e4...`），原子更新 `local.wx-clawbot.plist` 并经 `plutil -lint` 校验后重载；**1.307 秒**恢复 `native: ready` 与 `antigravity: ready`，PID `79593`，`cli --version` 为 `0.2.0`，`managed.json` 源码摘要与冻结 manifest 精确一致；12 项注册项目、161 条历史任务（含 2 条历史 `unknown` 未重放）、894 条 Outbox 回执全部完整保持。
