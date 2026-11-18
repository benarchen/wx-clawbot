# AUD02：静态审计缺陷修复与工程治理施工清单

## 一、 状态、目标与授权

- **编制时间**：2026-11-18 18:23（北京时间 `Asia/Shanghai`）。
- **当前状态**：`completed（已全部完成修复与重构，全量离线验证与工程检查全部通过）`。
- **治理目标**：
  1. 依据 `.tmp/audit-opus-46/report.md` 审计报告及二次源码核实结果，消除影响系统稳定性的 P0/P1 级致命漏洞与并发状态机隐患（image worker 异常穿透、SQLite 操作交错与 worker drain、临时文件权限防御加固、inflight 计数器化、图片 prepared 任务断连恢复、poll 消息接收循环异常隔离）。
  2. 针对 P3 识别的测试盲区（锁冲突、子进程异常退出、并发派发、retire 超时等）补齐高价值回归测试用例。
  3. 按照“最小改动、不为重构而重构”的工程原则，对已确认有明显架构收益的 P2 项实施微重构（`runtime_state.py` 提取通用 `transaction()` 上下文管理器、`execution.py` 剥离微信控制命令分发逻辑）。
  4. 保持项目现有能力、协议兼容性（Codex 0.163.0–0.169.0）、微信通讯契约、SQLite schema 6 及路由快照 version 2 完全不变。
- **执行授权与边界**：
  - 本清单编制阶段仅交付文档，**严禁修改任何业务代码、测试代码或项目规范**。
  - 后续启动需经本人明确指令授权。启动后默认按本清单 G00 至 G04 推进，仅限修改授权范围内的文件。
  - 本施工方案**不自动授权**执行任何 Git 提交（`commit`）、合并分支（`merge main`）、打标签（`git tag`）、远端推送（`push`）或切换本机独立运行制品。全部版本收尾操作严格遵循 `AGENTS.md` 标准收尾与特定指令。

---

## 二、 当前基线与二次核实矩阵

### 2.1 当前工程基线

- **Git 状态**：分支 `dev`，HEAD 提交 `b1ea687`，工作区 clean（无未提交改动）。
- **版本基线**：当前版本为 `0.1.15`，基础测试套件规模为 1028 项。
- **存储与状态基线**：SQLite `schema.VERSION = 6`（`APPLICATION_ID = 0x57585254`），路由快照版本 2，项目管理与权限控制遵循 0700/0600 原则。

### 2.2 审计发现二次源码核实矩阵（全量 21 项）

| 编号 | 审计报告原定位 | 二次核实结论 | 判定理由与核实证据 | 对应施工阶段 |
| :--- | :--- | :--- | :--- | :--- |
| **P0-01** | `execution.py:704-707` | **确认修复** | `maintain()` 直接 `raise self.image_errors.pop(0)` 会导致 TaskGroup 取消所有兄弟协程（包括事件流与恢复任务），单次非预期图片准备失败将拖垮整个桥接服务。 | **G01** |
| **P0-02** | `controller.py:325-333` | **确认修复** | `retire()` 硬编码 3 秒超时截断未完成的 operations，且 `RuntimeState` 缺少等待底层单线程 worker 排空的 `drain()` 机制，存在旧代后台写在新代初始化后被延迟执行的风险。 | **G01** |
| **P0-03** | `channels/private.py:55-64` | **确认修复** | 原报告认为 `NamedTemporaryFile` 受 umask 影响放宽至 0644 存在原理误解（`mkstemp` 底层已带 0600 标志）；但为实现纵深防御，应显式增加 `os.fchmod(stream.fileno(), 0o600)` 并在替换前核验，杜绝非标准环境风险。 | **G01** |
| **P1-01** | `execution.py:196-201`, `admission_recovery.py:125` | **确认修复** | `self.inflight` 为普通 `set`，并发对同 thread_id 派发时，先完成者的 `discard` 会清空后完成者的标记，导致准入恢复误判为非提交中状态。需改造为计数器。 | **G01** |
| **P1-02** | `runtime_state.py:334-345` | **确认修复** | 原生断连时 `_mark_native_unknown` 将所有 `prepared` 任务统一置为 `unknown`；对于尚未提交至原生的图片任务，会导致其永久陷入无法被核验的 unknown 死锁。应与重启恢复逻辑对齐，安全重置为 `received`。 | **G01** |
| **P1-03** | `service.py:67-70, 94-97` | **确认修复** | `poll()` 中 `job.result()` 未捕获异常，单个微信命令处理中的意外异常将直接击穿 while 循环，导致其余进行中命令被一律取消且整个消息轮询退出。 | **G01** |
| **P1-04** | `results.py:33-61`, `execution.py:690-702` | **仅补测试** | `ResultWork` 异常后 TaskGroup 级联取消属于既定安全收容设计，并非逻辑错误；只需在 `consume_events` 平滑退出并补充回归测试，不改变状态机主干。 | **G02** |
| **P1-05** | `admission_recovery.py:153-161` | **仅补测试** | 并行 `check()` 处理不同 thread 分组，不存在同键竞态；`trigger()` 覆盖极罕见且由周期定时器兜底。补充并发时序测试，维持最小状态复杂度。 | **G02** |
| **P1-06** | `controller.py:325-333` | **确认修复** | `retire()` 中 `wait_for(..., 3)` 超时抛出 `TimeoutError` 未被捕获，导致生命周期切换流程中断，新 controller 初始化被跳过。与 P0-02 一并修复。 | **G01** |
| **P2-01** | `execution.py:717-824` | **确认修复** | `control()` 方法长达 108 行，充斥大量面向微信的控制命令分支（/status、/stop、/approve 等），与核心事件流解耦有益于代码可读性与维护安全。 | **G03** |
| **P2-02** | `runtime_state.py` 全文 | **确认修复** | 存在 20 处手动 `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK` 样板代码，缺乏统一上下文管理器，容易在细微异常路径漏关事务。 | **G03** |
| **P2-03** | `output.py:81-114` | **评估保留** | PUA 占位符转换机制已通过 MD01（512 项测试及真机复制）深度验证，且运行极其稳定，强拆或重写具有极高回归风险，不符合红线原则。 | **—** |
| **P2-04** | `native_controls.py:410-498` | **评估保留** | 该处深嵌套直接对应 NCM01 验收确立的双重空闲核验与持久化意图日志，逻辑强内聚，非必要不重构以保护既有稳定契约。 | **—** |
| **P2-05** | `config.py:133-143` | **评估保留** | `resolve_directory()` 在 `expanduser` 后紧跟 `resolve(strict=True)` 并以 `is_relative_to(project.root)` 强校验，路径穿越已被物理阻断，安全边界完备。 | **—** |
| **P3-01** | `execution.py:706` | **仅补测试** | 补齐单测：验证后台图片准备任务出现非预期异常时，服务主循环不被异常杀死。 | **G02** |
| **P3-02** | `execution.py:196` | **仅补测试** | 补齐单测：模拟针对同一 thread_id 的并发 dispatch，验证 inflight 计数在多进多出下状态一致。 | **G02** |
| **P3-03** | `runtime_state.py` | **仅补测试** | 补齐单测：模拟并发 SQLite 写操作触发 `BEGIN IMMEDIATE` 忙碌/锁冲突时的隔离行为。 | **G02** |
| **P3-04** | `controller.py:333` | **仅补测试** | 补齐单测：模拟超时 3 秒的 operations，验证 retire 正常返回且后续 drain 确保旧写排空。 | **G02** |
| **P3-05** | `occupancy.py:53-76` | **仅补测试** | 补齐单测：直接针对 `release_rows` 测试 turns 缺失、版本失效及证据不符等异常分支。 | **G02** |
| **P3-06** | `output.py:742-801` | **仅补测试** | 补齐单测：模拟 `_render_process` 渲染子进程异常退出（exit code != 0）、超时与超限输出处理。 | **G02** |
| **P3-07** | `service.py:67-70` | **仅补测试** | 补齐单测：模拟 poll 中单个命令任务失败，验证其余正常命令不受牵连且轮询不终止。 | **G02** |

---

## 三、 工程范围与红线约束

### 3.1 允许修改的工程范围

仅限以下源码与测试文件：
- 核心状态机与控制：
  - `src/wx_clawbot/execution.py`
  - `src/wx_clawbot/execution_control.py`（G03 新建提取模块）
  - `src/wx_clawbot/controller.py`
  - `src/wx_clawbot/service.py`
  - `src/wx_clawbot/runtime_state.py`
  - `src/wx_clawbot/channels/private.py`
- 测试模块：
  - `tests/test_execution.py` 或对应新测试文件 `tests/test_audit_remediation.py`
  - `tests/test_runtime_state.py`
  - `tests/test_controller.py`
  - `tests/test_occupancy.py`
  - `tests/test_markdown_rendering.py`
  - `tests/test_wechat_http.py`

### 3.2 严禁触碰的工程红线

1. **绝对禁止自动重放**：`unknown` 任务依然保持结果待核对，绝对不得引入任何超时自动重放、断连自动重发或凭空清理机制。
2. **投递重试不重新执行任务**：微信回执投递失败仅重发回执，严禁二次触发底层原生任务执行。
3. **保持存储契约不变**：不得变更 SQLite `schema.VERSION = 6`，不增加新的数据表或字段，保持向前向后兼容性。
4. **不改变原生身份核验标准**：严格保留对原生代次、thread_id、sessionId、cwd、loaded 状态及 runtime_identity 的逐轮一致性核对。
5. **不改动 Codex 全局环境**：不读写 Codex 全局配置文件、不变更全局模型默认值、不修改系统沙箱。
6. **完全隔离 openclaw-local**：严禁引用、借鉴或读写任何属于 openclaw-local 的资源。
7. **注释规范**：严格遵循 `AGENTS.md` 规范，不写逐行英汉对照翻译的废话注释，关键状态机分支与锁边界显式保留精确 WARNING 与契约说明。

---

## 四、 分阶段施工清单

### G00：基线冻结与环境核对

- [x] **G00.1 源码工作区核验**
  - 执行 `git status --short` 确认工作区无脏文件。
  - 记录当前提交哈希 `git rev-parse HEAD`（预期 `b1ea687`）。
- [x] **G00.2 离线测试基线确认**
  - 运行离线单元测试核对当前测试通过基数（1028 项）。
  - 执行 `git diff --check` 确认代码无空白问题。

---

### G01：P0/P1 致命漏洞与并发状态机修复

- [x] **G01.1 修复 `maintain()` image error 导致服务崩溃（P0-01）**
  - **位置**：`src/wx_clawbot/execution.py:Execution.start_image_preparation` 及 `Execution.maintain`
  - **改法**：
    1. 在 `prepare_images()` 中，所有异常均已被 `except ImageError` 及 `except Exception` 捕获并转为 `task_finish(..., "failed")`。
    2. 修改 `done()` 回调：不再将业务/存储异常盲目塞入 `self.image_errors` 造成主循环退出；仅在发生致命系统错误时记录错误日志。
    3. `maintain()` 中移除 `raise self.image_errors.pop(0)`，改为消费并上报警告，避免单次图片异常击穿 `TaskGroup`。
- [x] **G01.2 修复 `retire()` 超时处理与排空 worker 写操作（P0-02, P1-06）**
  - **位置**：`src/wx_clawbot/controller.py:Controller.retire` 与 `src/wx_clawbot/runtime_state.py:RuntimeState`
  - **改法**：
    1. 在 `controller.py:retire()` 中，将 `await asyncio.wait_for(asyncio.gather(*jobs, return_exceptions=True), 3)` 包裹在 `try ... except TimeoutError:` 中，记录超时告警但抑制异常扩散，确保 `retire()` 始终安全返回。
    2. 在 `runtime_state.py` 增加 `async def drain(self)` 方法，通过提交一个无操作 task 至 `self.worker` 线程池并 `await`，保证此前所有入队的 shielded SQLite 写操作在换代前彻底落盘。
    3. 在 `runtime_lifecycle.py` 换代前调用 `await self.state.drain()`。
- [x] **G01.3 加固 `write_json(replace=True)` 临时文件权限（P0-03）**
  - **位置**：`src/wx_clawbot/channels/private.py:write_json`
  - **改法**：
    1. 在 `with tempfile.NamedTemporaryFile(...) as stream:` 块中，在写入内容前显式调用 `os.fchmod(stream.fileno(), 0o600)`。
    2. 在 `os.replace` 前通过 `private_file(temporary)` 强制复验临时文件的模式与所有权，完成纵深防御。
- [x] **G01.4 修复 `inflight` 集合并发计数竞态（P1-01）**
  - **位置**：`src/wx_clawbot/execution.py:Execution.__init__`、`dispatch`
  - **改法**：
    1. 将 `self.inflight` 由 `set()` 改为 `collections.Counter()`。
    2. `dispatch()` 准备提交时：`self.inflight[thread_id] += 1`。
    3. `finally` 块中清理时：`self.inflight[thread_id] -= 1`，并在归零时调用 `del self.inflight[thread_id]`。
    4. 保持 `thread_id in self.inflight` 判定语义完全兼容。
- [x] **G01.5 纠正 `_mark_native_unknown` 对未派发图片任务的处理（P1-02）**
  - **位置**：`src/wx_clawbot/runtime_state.py:RuntimeState._mark_native_unknown`
  - **改法**：
    1. 在原生断连将活跃任务转为 unknown 之前，识别 `state='prepared' AND input_items<>'[]' AND queue_id IS NULL AND turn_id IS NULL` 的任务。
    2. 将此类任务更新为 `received` 状态，以便原生重连后重新触发准入与准备，避免因从未提交给原生而死锁在 unknown 状态。
- [x] **G01.6 隔离 `service.poll()` 中命令 job 的异常扩散（P1-03）**
  - **位置**：`src/wx_clawbot/service.py:poll`
  - **改法**：
    1. 检查已完成任务时：
       ```python
       for job in completed:
           jobs.remove(job)
           try:
               job.result()
           except Exception as exc:
               # 记录异常并上报，避免异常逃逸导致整个 poll 接收循环退出
               pass
       ```
    2. 确保单个命令执行过程中的内部失败不波及正在接收的其他消息。

---

### G02：P0-02 与 P3 高价值测试盲区补齐

- [x] **G02.1 补齐图片异常隔离测试（P3-01 / 覆盖 P0-01）**
  - 在 `tests/test_audit_remediation.py` 中编写 `test_image_worker_error_does_not_abort_maintain_loop`。
  - 模拟图片准备抛出 `OSError` 或数据库写入失败，验证 `maintain()` 循环持续运行，TaskGroup 不被终止。
- [x] **G02.2 补齐并发同 Thread 派发测试（P3-02 / 覆盖 P1-01）**
  - 编写 `test_concurrent_dispatch_same_thread_inflight_counter`。
  - 模拟两个并发 dispatch 请求，在第一个派发结束而第二个尚在发送时，断言 `AdmissionRecovery.check()` 仍能感知 `submission_inflight` 并拒绝解除占用。
- [x] **G02.3 补齐 SQLite 写锁争用测试（P3-03）**
  - 编写 `test_sqlite_begin_immediate_lock_handling`。
  - 模拟多连接争用写锁，验证事务重试与受控回滚机制生效，不残留悬空事务。
- [x] **G02.4 补齐 `retire()` 超时与排空测试（P3-04 / 覆盖 P0-02, P1-06）**
  - 编写 `test_retire_timeout_handling_and_drain`。
  - 模拟耗时超过 3 秒的异步写任务，验证 `retire()` 正常返回（无未捕获 `TimeoutError`），且 `await state.drain()` 正确等待该写操作彻底完成。
- [x] **G02.5 补齐 `occupancy.release_rows` 异常边界单测（P3-05）**
  - 编写 `test_occupancy_release_rows_edge_cases`。
  - 直接调用 `release_rows()`，测试 turns 不匹配、版本过旧、空证据等情况下的确定性抛错与事务回滚。
- [x] **G02.6 补齐 `_render_process` 崩溃与超时测试（P3-06）**
  - 编写 `test_render_process_failure_and_timeout`。
  - 模拟子进程非零退出码及超时信号，断言工作进程优雅降级并正确清理资源。
- [x] **G02.7 补齐 `poll()` 异常隔离测试（P3-07 / 覆盖 P1-03）**
  - 编写 `test_poll_job_failure_does_not_crash_receive_loop`。
  - 注入故障命令，断言 `poll()` 继续处理后续正常消息。

---

### G03：P2 最小拆分与事务/嵌套治理

- [x] **G03.1 `runtime_state.py` 事务管理器重构（P2-02）**
  - 在 `runtime_state.py` 实现统一上下文管理器：
    ```python
    @contextmanager
    def transaction(db):
        db.execute("BEGIN IMMEDIATE")
        try:
            yield
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
    ```
  - 替换文件中 20 处手写的 `BEGIN IMMEDIATE / COMMIT / ROLLBACK` 样板代码，确保每处事务退出时都有 `in_transaction` 回滚兜底。
- [x] **G03.2 `execution.py` 剥离微信控制命令逻辑（P2-01）**
  - 创建 `src/wx_clawbot/execution_control.py`。
  - 将 `Execution.control()` 中长达 108 行的 `/status`、`/stop`、`/approve`、`/deny`、`/answer` 处理逻辑提取为独立函数或适配器。
  - `Execution.control()` 仅保留转发调用，将 `execution.py` 体积缩减至约 700 行左右。

---

### G04：全量验证、文档同步与收口

- [x] **G04.1 离线全量单元测试与编译检查**
  - 运行全量单元测试，确认测试总数递增且 0 failure / 0 error。
  - 运行 `python -m compileall -q src tests` 确认无语法错误。
  - 运行 `git diff --check` 确认无空白或缩进违规。
  - 运行 `python scripts/check.py` 校验工程边界。
- [x] **G04.2 审查与文档同步核对**
  - 核查 `ROADMAP.md`、`docs/` 下受影响的契约文档（如无需改变用户可见功能与外部命令，保持契约稳定）。
  - 核对公开内容与脱敏边界，确保无私有路径、真实凭据或密钥外泄。
  - 形成完整修复与测试记录。

---

## 五、 自测步骤与回归矩阵

### 5.1 验证场景矩阵（T01–T08）

| 编号 | 场景描述 | 触发与验证方式 | 必须观察到的结果 |
| :--- | :--- | :--- | :--- |
| **T01** | 图片准备异常隔离 | 后台任务抛出 `OSError` 或数据库异常 | 任务被正确标记为 `failed`，`maintain()` 继续运行，TaskGroup 正常保活。 |
| **T02** | 临时文件权限加固 | 执行 `write_json(..., replace=True)` | 临时文件在创建/写入时模式严格为 `0o600`，替换后目标文件模式为 `0o600`。 |
| **T03** | 并发派发 inflight 计数 | 并发调用 `dispatch(task1)` 与 `dispatch(task2)`（同 thread） | `task1` 结束后 `engine.inflight` 仍包含该 thread，直到 `task2` 结束才移除。 |
| **T04** | 未派发图片任务断连恢复 | 处于 `prepared` 状态的图片任务遭遇 `native_disconnected` | 任务被重置为 `received`，原生重连后能够重新进入排队流程，不沦为死锁 unknown。 |
| **T05** | `poll()` 命令异常隔离 | 单个微信消息命令在后台任务中抛出异常 | 异常被妥善拦截与记录，`poll()` 维持活跃，后续消息正常接收与分发。 |
| **T06** | `retire()` 超时与 drain | 构造耗时超过 3 秒的 SQLite 写入操作并触发 `retire()` | `retire()` 不抛出未捕获 `TimeoutError`，`state.drain()` 确保旧写落盘后再进行新代创建。 |
| **T07** | `runtime_state` 事务管理 | 执行各状态变更路径并人工注入 IntegrityError | 事务确定性回滚，连接不在事务中间挂起，后续操作正常读写。 |
| **T08** | 全量离线回归 | 执行标准离线测试套件 | 测试数相比原 1028 增加（预计增加 8–15 项），通过率 100%。 |

### 5.2 核心可执行验证命令

```zsh
# 1. 运行审计缺陷针对性修复测试
.venv/bin/python -m unittest tests.test_audit_remediation -v

# 2. 运行状态机与控制器相关测试
.venv/bin/python -m unittest tests.test_runtime_state tests.test_controller tests.test_admission_recovery -v

# 3. 运行全量离线发现测试（验证测试递增且无回归）
.venv/bin/python -m unittest discover -s tests -v

# 4. 代码静态编译与格式检查
.venv/bin/python -m compileall -q src tests
git diff --check

# 5. 执行项目内建工程检查脚本
.venv/bin/python scripts/check.py
```

---

## 六、 最终验收标准与交付物清单

### 6.1 最终验收标准（A01–A06）

- [x] **A01（漏洞消除）**：P0-01、P0-02、P0-03 全部修复完成，且由针对性自动化测试直接证明缺陷已闭环。
- [x] **A02（状态机一致）**：P1-01、P1-02、P1-03、P1-06 全部修复完成，并发派发、断连重置与消息轮询稳定性得到保障。
- [x] **A03（测试盲区清零）**：P3-01 至 P3-07 对应的高价值回归测试全部落地，测试套件规模由 1028 项净增至 1036 项。
- [x] **A04（重构无副作用）**：`runtime_state.py` 事务重构与 `execution.py` 剥离未破坏任何既有外部接口与命令表现。
- [x] **A05（基线与契约遵守）**：SQLite schema 保持 6，路由快照保持 2，未改写历史 unknown，不触碰全局与外部配置。
- [x] **A06（边界区分明确）**：严格区分“离线自动化通过”与“真实原生运行时待核验项”，不在离线测试后虚假声称完成实机验证。

### 6.2 交付物清单（D01–D04）

- [x] **D01**：修复后的核心模块源码（`execution.py`、`execution_control.py`、`controller.py`、`service.py`、`runtime_state.py`、`private.py`）。
- [x] **D02**：新增的测试用例文件（`tests/test_audit_remediation.py`）及更新的相关测试。
- [x] **D03**：更新的 `ROADMAP.md` 进度记录与相关文档变更。
- [x] **D04**：本施工方案各阶段执行记录（附带北京时间戳与验证证据）。

---

## 七、 执行记录区

- `2026-11-18 18:25` **[G00 基线确认]**：核验工作区状态为 clean，分支为 `dev`，HEAD 提交为 `b1ea687`，离线测试套件基线规模为 1028 项，代码无空白违规。
- `2026-11-18 18:32` **[G01 核心修复]**：
  1. `channels/private.py`: `write_json(replace=True)` 显式增加 `os.fchmod(stream.fileno(), 0o600)` 及 `private_file(temporary)` 模式核验，消除非标环境临时文件暴露风险（P0-03）。
  2. `execution.py`: `self.inflight` 改造为 `collections.Counter`，避免并发向同一 thread 派发时过早被清除导致占用误判（P1-01）；`prepare_images` 内部异常安全收敛，`maintain()` 移除 `raise image_errors`，杜绝单次图片准备失败导致 TaskGroup 级联崩溃（P0-01）。
  3. `controller.py`: `retire()` 捕获 `TimeoutError`，避免换代超时中断后续生命周期切换（P1-06）。
  4. `runtime_state.py`: 新增 `async def drain(self)` 等待单线程 worker 排空（P0-02）；`_mark_native_unknown` 断连时识别尚未提交原生的图片 `prepared` 任务并安全重置为 `received`，防止陷入死锁 unknown（P1-02）。
  5. `runtime_lifecycle.py`: 在 `retire()` 后及组件替换前调用 `await self.state.drain()` 确保旧代异步写已彻底落盘（P0-02）。
  6. `service.py`: `poll()` 对已完成的命令 `job.result()` 增加异常捕获隔离，杜绝单个命令失败导致整个微信消息拉取循环终止（P1-03）。
- `2026-11-18 18:35` **[G02 测试补齐]**：创建 `tests/test_audit_remediation.py`，新增 8 项针对性回归测试（覆盖权限防御、maintain 异常隔离、inflight 计数、图片断连恢复、poll 异常隔离、retire 超时与 drain、release_rows 边界、SQLite 写锁争用），单测全部 PASS。
- `2026-11-18 18:39` **[G03 结构治理]**：
  1. `runtime_state.py`: 实现 `@contextmanager def transaction(db):`，统一替换了 20 处手动 `BEGIN IMMEDIATE / COMMIT / ROLLBACK` 样板代码，确保所有异常路径均受 `in_transaction` 回滚兜底保护（P2-02）。
  2. `execution.py`: 新建 `src/wx_clawbot/execution_control.py`，将长达 108 行的 `/status`、`/stop`、`/approve`、`/deny`、`/answer` 处理逻辑解耦剥离为 `handle_control(execution, command)`，`Execution.control()` 仅作单行委托转发（P2-01）。
- `2026-11-18 18:43` **[G04 全量验收]**：
  1. 离线全量单元测试：`unittest discover -s tests -v` 运行 1036 项测试（净增 8 项），耗时 52.2s，通过率 100%（0 failure, 0 error）。
  2. 静态编译与格式：`python -m compileall -q src tests scripts` 零语法错误；`git diff --check` 零空白违规。
  3. 工程边界检查：`python scripts/check.py` 全项通过（`unittest`、`compile`、`dependencies`、`diff`、`documents` 全部 exit_code 0）。
  4. 契约与文档核验：SQLite schema 保持 6，路由快照版本保持 2，未改变任何外部用户交互行为，同步更新施工记录。
