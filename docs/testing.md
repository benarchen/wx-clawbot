# 测试与验收指南

本文说明如何选择验证、如何判断通过及哪些结果不能相互替代。需求以 [PRD](product-design.md)为准，V00 至 V08 的稳定定义见[开发契约](development-contracts.md#9-关键接口验证关卡)，覆盖映射见[需求追溯](requirements-traceability.md)。测试证据必须带基线、方法、实际结果与限制，不把旧测试数量写成每次已重跑。

## 测试层次

| 层次 | 当前入口与对象 | 能证明／不能证明 |
| --- | --- | --- |
| 静态协议／文档 | fixture、版本匹配 schema、documents 检查 | 字段／门禁／链接一致；不能证明运行时竞争或手机收件 |
| 离线单元与契约 | `tests/test_*.py`，fake API／native、私有合成 SQLite／Unix 对端 | 确定性行为、事务、拒绝与竞态；不等于真实平台支持 |
| 合成本地负载／制品 | engineering_performance、engineering_release 等显式入口 | 本地时延、资源上界、隔离导入和制品一致；不含模型／公网 SLA |
| 真实原生 | `tests/integration/` 对应专用验收器 | 准确 daemon／thread、队列、双端交互与来源；fake 微信不能代表本人手机 |
| 微信本人真机 | 专门安排的内容、条数和本人截图／复制结果 | 实际接收、显示／复制与交互；API accepted 不能替代 |
| 发布后本机 | 冻结制品、实际 argv／cwd、manifest、唯一消费者、旧数据和依赖 | 已加载准确制品及保护结果；不能代替尚未执行的专项功能验收 |

`tests/integration/` 同时含合成和真实脚本，不用目录名决定执行权限；先读入口、参数、具体 Goal 和前置。原生版本逐能力见[兼容矩阵](protocol-baseline.md)，不机械在 0.167.0 执行只核验过 0.166.0 的异步全阶段脚本。

## 默认离线检查

PRJ01 专项入口为 `tests/test_project_registry.py`、`tests/test_project_runtime.py`，覆盖真实目录、配置原子写、真实子进程落盘后退出／启动锁、Unix socket 成功回执丢失／提前断开／资源上限、双端一致性、取消注册竞争和崩溃收敛；未处理回调异常也必须令用例失败。显式真实原生入口 `tests/integration/project_management_native.py` 的 prepare 不运行任务，run／cleanup 须有专用资源授权；两个临时项目／一个窗口／两个标签，无真实微信发送。逐 T／A 状态及手机范围见[PRJ01 清单](../goals/20261108-2048-project-management.md)。

项目列表展示另由 `tests/test_project_display.py` 覆盖：正常／异常、别名与目录不同、旧格式／空清单、Markdown 字面值及 256 项分段；`test_project_runtime.py` 核验三个列表入口输出一致、check 保留详情且查询不写注册或路由。渲染器和 Markdown 解析验证不等于微信手机实收，实际手机显示与部署范围在 ROADMAP 分别记录。

NCM01 的 `tests/test_native_controls.py`、连接／控制器专项核语法、准确 route、loaded-only 查询与用量；`test_native_control_writes.py` 核联合模型／推理及单字段 Fast 设置、早到／缺失／冲突通知、忙碌与未知，`test_control_journal.py` 核持久化／权限／容量，`test_native_control_process.py` 用真实合成 Unix socket 和崩溃子进程证明最多一次写入。历史单字段 903 项及原生结果保留原范围；现行联合命令／展示去重候选已通过同包 932 项，0.169.0 专用原生和本人手机功能关卡另有准确设置／turn／清理证据。驱动空闲轮询缺陷已复现修正，恢复只读对账不重放；离线不能替代手机实收，逐项验收与历史展示缺口见[验证记录](validation/native-controls.md)。

`tests/integration/native_controls_probe.py prepare` 只建专用夹具；`bridge-run` 使用 `native_control_bridge.py`，通过实际 Controller／Execution／RuntimeState 接入真实原生，全部微信输入为本机合成，本人客户端不被操作。新一轮 run／bridge-run／cleanup 须取得具体授权；`test_native_controls_probe.py` 验证重复执行、换代与精确 sleep 包装保护。候选原生／手机层级和具体操作卡见[阶段记录](validation/native-controls.md)。

在项目根和项目 venv 执行：

```sh
.venv/bin/python scripts/check.py
```

执行非零且无跳过的 unittest、compileall、pip check、Git diff 和 documents，报告在项目 `.tmp/check/`。不安装依赖、不连接微信／原生、不维护生产状态。基础命令亦可分别运行：

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q src tests
.venv/bin/python -m pip check
git diff --check
```

纯文档改动可只运行现有 documents 函数与 diff，另检查本轮 JSON、引用、语义、隐私及架构图；不为措辞无理由重复功能测试：

```sh
.venv/bin/python -I -c 'from pathlib import Path; import runpy; runpy.run_path("scripts/check.py").get("documents")(Path.cwd())'
git diff --check
```

documents 当前验证 JSON、本地链接／标题锚点、包版本、README 必需格式语义提示及 ROADMAP 两个最近节各不超 20 条；它不解析架构图或穷尽语义冲突。新 SECURITY 等根文档也需检查链接，不能假设默认检查已覆盖全部新入口。

## 按风险选回归

| 变化 | 重点失败路径／测试入口 |
| --- | --- |
| 路由／身份／发现 | independent_target、native_identity、native_target_lifecycle、catalog、routing；同 cwd 多对话、fork 共 sessionId、换代、notLoaded、不完整分页、宿主缺席、旧快照拒绝 |
| 查询／帮助 | controller、runtime_lifecycle、commands；sessions 保留 focused／managed 与订阅／任务，空结果／筛选／失败／换代不清目标，查询期间可发原目标，离线不拉起宿主；help 全部命令、参数及别名与解析器一致，逐条复查简短说明的含义和长度，经实际输出渲染链核对完整性 |
| 新建／宿主恢复 | visible_launch、host_connection、host_lifecycle；意图先落盘、丢 ACK、重复 nonce、无 boot／缺 completed、进程变化、授权截止和取消回收 |
| 排队／准入／恢复 | native_queue、admission*、recovery_state；提交边界未知、完整队列／准确终态、合并输入不伪完成、占用 revision 过期拒绝、unknown 不重放 |
| 同步／异步交互 | interactions、interaction_acceptance、async_questions、async_question_repro；原生裁决／跨端竞争、答案格式、期限边界、原 turn 已结、未知答案不可重试 |
| 通道／媒体／投递 | wechat_*、image_*、delivery_state；本人身份、游标原子、防重／冲突、SSRF／重定向／媒体超限、同会话顺序、发送未知及重复风险确认 |
| 账本／维护 | schema、image_schema、performance_schema、retention；消费者锁、绑定、备份、失败回滚、旧行保持、unknown 保护 |
| 展示／性能／制品 | markdown_*、output、render_worker、performance、release、engineering_*；代码／链接语义、源切片重建、取消回收、冻结历史、manifest／非 editable |

文件名均为 `tests/test_<名称>.py`，精确测试方法可从追溯入口定位。修改实现后跑相关最小回归，再完成项目必要离线检查；只有新增修改、失败或具体疑点才扩大／重复。

## 真实原生验收

先明确本轮输入与范围，登记一个专用 iTerm2 窗口、至多两个命名标签、准确归属、临时项目和独立合成账本／假微信端。不得接入用户工作对话凑验证。版本、原生二进制／socket、项目规则／信任、模型条件和实际来源全部先核对；修改临时模型或全局配置不能用确认参数替代本人授权。

| 场景 | 显式脚本与证据入口 |
| --- | --- |
| 初始身份／多轮 | `w02_verify.py`；[W02](validation/w02.md) |
| 同步／队列 | `w03_verify.py`；[W03](validation/w03.md)、[W08](validation/w08.md) |
| 可见项目路由 | `admission_native.py` 等对应 case；[W05](validation/w05.md) |
| 恢复／投递 | `w06_recovery.py`、`w06_delivery.py` 等；[W06](validation/w06.md) |
| 单图 | `image_input.py`；[IMG01](validation/image-input.md)、HOST01 后续范围 |
| 异步 | `async_questions_native.py`／`engineering_async_model.py`；[ASK01](validation/async-questions.md)，仅匹配能力门禁 |
| 工程串联 | `engineering_native.py`；[ENG01](validation/engineering-hardening.md)，具体子阶段前提必须满足 |
| 独立选择／无读屏 | `independent_target_native.py`、`native_session_no_footer.py`、`native_session_no_footer_flow.py`；[TGT01](validation/wechat-independent-target.md)、[TGT02](validation/native-session-no-footer.md) |
| 冷启动零额外 Shell | `iterm_single_window.py`；本人保存并退出 iTerm2 后，以准确非 editable manifest 在两个临时项目验证一次应用启动、一个自有窗口、重复 cd 复用及安全清理；[记录](validation/iterm-single-window.md) |

这些是定位入口，不构成“全部直接跑”的命令集。先 `--help` 和只读 report 确认具体 case，再按对应 Goal 准备、执行、核验和清理。每次外部动作前登记意图；已有未知意图先只读核对，不删除 case、修改 phase 或重跑。清理前核准确终端／原 thread／终态／空队列，只清自有资源。

## 本人手机与显示验收

本人手动操作微信。先冻结准确原生结果与 Outbox，再按明确内容／条数安排输入、显示截图、链接目标及代码实际复制。短样、长分段、真实任务分别记录客户端版本和结果。复制按钮、源文可重建、接口 accepted 互不替代。

当前 Android 验收和 Mac 已知失败见[排版](wechat-markdown.md)；同消息图文、自然上下文失效触发和新版专项限制见 ROADMAP／矩阵。不用合成 Inbox 冒充手机，也不为等待自然过期阻塞已确认必要范围。

## 性能和冻结制品

`engineering_performance.py` 的 measure／load／compare 使用合成输入和假发送端，load 至少 120 秒；对比要求准确基线／候选解释器、源码摘要和冻结 manifest，交替组及预热规则见[运维交接](operations.md#eng01本地检查性能与真实原生交接)与原 Goal。失败样本不参与提速比，慢样本不删除。

`engineering_release.py` 在全新合成状态根检查隔离导入、子进程、错误 manifest、单消费者及停止；不能替代真实 launchd 切换。发布部署按运维，构建／安装、实际加载、原生可用和真人收件分列。

## 通过、失败和证据格式

每轮记录：需求／关卡 ID、时间、准确代码／制品／原生／客户端版本、前置、动作意图、预期、实际、结果、证据位置和限制。失败应保存原始私有 case，公开报告只保留脱敏摘要及关联方法，不公开身份、路径、正文或私人截图。

关键验收通过要求：无错误目标、无未知自动重投、无伪造原生成功；适用版本的动态／手机关卡完成；必要离线检查通过；运行切换另核旧数据与实际制品。无法验证标未验证；经本人明确后置的项目保留范围，不把它补成通过。纯文档完成不代表产品全部专项重验。

统一 model set 的目录默认、联合字段确认、部分应用 unknown 和崩溃不重放均有离线覆盖；0.169.0 专用原生及本人手机联合设置／桌面后续采用／busy／清理已核验，旧单字段结果只限原候选。展示优化增加 `test_command_display.py`：默认字段、中文状态、未知／队列、多桶／北京时间、模型分段／字面值、同名去重及完整操作编号。最终冻结包 932 项／47.553 秒及编译／依赖／文档／diff 通过，已核源码与实际加载一致；本地 360 px 预览和本人微信实收分别验收，末轮四图及三个准确命令回执补齐去重、8 个模型和完整帮助。分层结果见 [NCM01 记录](validation/native-controls.md)。

账号额度由 test_native_control_quota.py 核剩余比例／原生时长／重置、缺失／非法／多桶／身份脱敏、失败与代次；test_native_controls.py 核 status 真实调用路径及其他查询不访问账号。真实同运行时只读快照、手机截图和任务实际采用分别记录，账号额度不作为某模型或本会话专属指标。

0.169.0 衔接由 test_codex_connection.py 核当前账号范围、附属 thread 拒绝、无环境覆盖的 loaded-only 读；test_native_controls.py／test_native_control_writes.py 核 provider 目录及联合写字段保持；test_native_0169_output.py 核审核／展示指令不透传正文或错误。真实原生与手机仍独立验收，版本静态证据见 [比较](validation/codex-0169.json)。
