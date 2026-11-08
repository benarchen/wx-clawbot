# 需求、实现、测试与证据追溯

适用应用 0.1.9。P01 至 P14 的需求与验收以 [PRD](product-design.md#8-首版验收)为准，V00 至 V08 以[开发契约](development-contracts.md#9-关键接口验证关卡)为准。本表定位实现与已有证据，不宣称所有历史关卡在本轮或每个原生版本重新执行；当前进度只见 [ROADMAP](../ROADMAP.md)，逐能力版本和手机范围见[协议矩阵](protocol-baseline.md)。

## 核心产品需求

测试列中的方法均来自现有源码，可在对应文件搜索；列举代表性失败路径，其他回归按测试指南选择。所有证据按其当时版本和前置解读，TGT02 的无读屏语义取代旧身份要求，但不倒改旧实测。

| 需求 | 命令／旅程与技术设计 | 实现入口 | 现有离线测试及关键断言 | 动态／手机证据与范围 |
| --- | --- | --- | --- | --- |
| P01 本人收发 | 首次绑定；[微信协议](wechat-protocol.md)；V06 | [login](../src/wx_clawbot/channels/login.py)、[messages](../src/wx_clawbot/channels/messages.py)、[state](../src/wx_clawbot/channels/state.py) | [wechat_login](../tests/test_wechat_login.py)：unconfirmed_owner；[wechat_state](../tests/test_wechat_state.py)：unknown_identity、cursor_and_inbox_rollback | [W04](validation/w04.md)：本人扫码／绑定／往返，不证明固定自然过期时间 |
| P02 多项目 | `/cd` 与返回；[架构第 5 节](architecture-design.md#5-项目目录与上下文)；V02／V05 | [config](../src/wx_clawbot/config.py)、[routing](../src/wx_clawbot/routing.py)、[controller](../src/wx_clawbot/controller.py) | [routing](../tests/test_routing.py)、[controller](../tests/test_controller.py)、[independent_target](../tests/test_independent_target.py)：cd_reuses_managed_a | [W05](validation/w05.md)临时项目、[W08](validation/w08.md)获授权真实项目；规则责任按 AUD01，非逐轮重载 |
| P03 目录边界 | `/cd` 真实解析；V05 | [config](../src/wx_clawbot/config.py)、[routing](../src/wx_clawbot/routing.py) | [config](../tests/test_config.py)、[routing](../tests/test_routing.py)、[visible_launch](../tests/test_visible_launch.py)：registered_path_replaced_with_symlink | W05 特殊路径／注入；不是操作系统权限隔离证明 |
| P04 发现／单发 | `/sessions`、`/send`；[身份](native-session-identity.md)；V01／V02 | [catalog](../src/wx_clawbot/catalog.py)、[sessions](../src/wx_clawbot/sessions.py)、controller | [native_identity](../tests/test_native_identity.py)：fork_shared_native_session_root、not_loaded；[native_target_lifecycle](../tests/test_native_target_lifecycle.py)：all_native_operations_trap_screen_identity_reads | [W02](validation/w02.md)原多轮；[TGT02](validation/native-session-no-footer.md)无 ID 首次接入，后台不对应当前窗口 |
| P05 聚焦／退出 | `/focus`、`/unfocus`、`/sessions`；[命令](command-contract-proposal.md) | routing、controller、[subscriptions](../src/wx_clawbot/subscriptions.py) | [independent_target](../tests/test_independent_target.py)：desktop_switch_preserves_focus、unloaded_original；[routing](../tests/test_routing.py)列表保留目标；[controller](../tests/test_controller.py)纯查询／订阅／失败／并发回归 | [TGT01](validation/wechat-independent-target.md)、TGT02：A／B 切换及卸载拒绝；查询边界的新验证见 ROADMAP，旧记录保留当时语义 |
| P06 可见新建 | `/cd`／`/new`；架构 F05；V05 | [visible](../src/wx_clawbot/hosts/visible.py)、[launcher](../src/wx_clawbot/launcher.py)、controller | [visible_launch](../tests/test_visible_launch.py)：lost_host_ack、duplicate_nonce、ready_requires_actual_boot_provenance_and_unique_completed_native_handshake | W05、[冷启动](validation/iterm-cold-start-live.md)、TGT02；新窗口不代表 ready，失败意图不重复 |
| P07 实际工作 | 场景 A／B；原生队列；V02 | [execution](../src/wx_clawbot/execution.py)、[queue](../src/wx_clawbot/agents/queue.py) | [controller](../tests/test_controller.py)、[native_queue](../tests/test_native_queue.py)关联、结果和错误 | [W08](validation/w08.md)临时项目文件／测试及真实项目只读关卡；不授予后续项目写权限 |
| P08 同步决定 | `/approve`／`/deny`／`/answer r-...`；V03 | [interactions](../src/wx_clawbot/interactions.py)、execution | [interactions](../tests/test_interactions.py)、[interaction_acceptance](../tests/test_interaction_acceptance.py)、[recovery_state](../tests/test_recovery_state.py)：uncertain_answer_cannot_be_reopened | [W03](validation/w03.md)、W08、[HOST01](validation/host-lifecycle-recovery.md)各同步场景；跨端首答不延伸至异步 |
| P09 队列／取消 | 微信／桌面专用队列、`/stop`；V04 | queue、execution、[admission](../src/wx_clawbot/admission.py) | [native_queue](../tests/test_native_queue.py)：unknown_add_outcome、cancel_requires_matching、wrong_active_turn；[engineering_boundaries](../tests/test_engineering_boundaries.py)：released_unknown 不混入候选 | W03 专用队列／TUI 反例；W08、HOST01 原生中断；不保证杀全部子进程或自动解除暂停 |
| P10 重复／故障 | 冻结目标、unknown 不重放；V07 | runtime_state、execution、[delivery](../src/wx_clawbot/delivery.py) | [wechat_state](../tests/test_wechat_state.py)、[recovery_state](../tests/test_recovery_state.py)、[delivery_state](../tests/test_delivery_state.py) | [W06](validation/w06.md)、REC01、ENG01 各故障点；API accepted 不是手机已读 |
| P11 长结果 | 架构 F04；[排版](wechat-markdown.md)；V08 | [output](../src/wx_clawbot/output.py)、[results](../src/wx_clawbot/results.py)、delivery | [markdown_rendering](../tests/test_markdown_rendering.py)、[markdown_delivery](../tests/test_markdown_delivery.py)、[render_worker](../tests/test_render_worker.py)保真／冻结／回收 | [MD01](validation/wechat-markdown.md)：Android 显示和实际复制；Mac 缺陷保留，不能补为全兼容 |
| P12 保护边界 | [安全](../SECURITY.md)、[规则](project-rules.md)；V00／V05／V07 | [private](../src/wx_clawbot/channels/private.py)、[http](../src/wx_clawbot/channels/http.py)、release 等 | [wechat_http](../tests/test_wechat_http.py)、[image_media](../tests/test_image_media.py)、[release](../tests/test_release.py)、[rules_native](../tests/test_rules_native.py) | W02／W05 单次授权历史，AUD01 规则反例、各发布隐私核对；不是全面安全审计 |
| P13 重启恢复 | 状态、依赖生命周期；V07 | [runtime_lifecycle](../src/wx_clawbot/runtime_lifecycle.py)、[operations](../src/wx_clawbot/operations.py)、controller.restore | [runtime_lifecycle](../tests/test_runtime_lifecycle.py)、[native_target_lifecycle](../tests/test_native_target_lifecycle.py)：v2_restore、runtime_or_native_session_change | HOST01、TGT02 同代次重启／宿主缺席及卸载拒绝；历史结果恢复不授予路由 |
| P14 扩展边界 | 能力声明／unsupported；[适配契约](development-contracts.md#3-规范化对象与接口) | [agents/base](../src/wx_clawbot/agents/base.py)、controller、subscriptions | [controller](../tests/test_controller.py)：unsupported_agent_refuses_before_durable_task_admission；[subscriptions](../tests/test_subscriptions.py)：unsupported_agent | 替身验证边界，无第二真实 Agent 的兼容验收，不宣称通用插件系统 |

## 后续纳入的能力与质量要求

| 主题 | 产品行为／设计 | 实现／现有测试 | 证据与未覆盖边界 |
| --- | --- | --- | --- |
| IMG01 | 单静态图、固定目标、FIFO、准备与执行分离；[指南](image-input.md) | [images](../src/wx_clawbot/images.py)、[media](../src/wx_clawbot/channels/media.py)、image_controller／image_media／image_schema 测试 | IMG01／HOST01 真机；同消息图文和新版手机专项不能由解析测试补足 |
| HOST01 | 通道独立、按需宿主、代次／授权截止 | hosts/lifecycle、runtime_lifecycle；host_connection／host_lifecycle 测试 | HOST01；冷启动后由 0.167.0 专用复测补证，不等于每次新建无限成功 |
| REC01 | 结果／占用分离、等待／处置 | [admission_recovery](../src/wx_clawbot/admission_recovery.py)、occupancy；[对应测试](../tests/test_admission_recovery.py)：merged_terminal_history、busy_idle_alone、late_native_activity | [REC01](validation/admission-recovery.md)；无超时自动解锁或 force |
| ASK01 | 原轮次补充、单次意图、竞争提示 | [async_questions](../src/wx_clawbot/async_questions.py)、async_state；[对应测试](../tests/test_async_questions.py)：foreign_after_accepted、expiry_599_valid_and_600_invalid、unsupported_version | [ASK01](validation/async-questions.md)原生＋真人；矩阵门禁保留，异步非审批 |
| ENG01 | 运行隔离、CPU 资源、容量和控制响应 | release／render_worker／managed；release、engineering_boundaries／async_model、performance 测试 | [ENG01](validation/engineering-hardening.md)合成负载／真实原生／切换分列；本地基准非 SLA |
| TGT01／TGT02 | 微信独立选择、无页脚首次接入、准确 v1／v2 兼容 | sessions／catalog／controller；independent_target／native_identity／native_target_lifecycle／visible_launch | 对应功能证据及[0.1.8 发布](validation/native-session-release.md)；没有移动 ID 到标题或修改官方 CLI |
| 原生规则 | 不保证热刷新、检测或自动阻断 | sessions／execution；rules_native 及真实实验入口 | [AUD01](validation/native-diagnostics-rules.md)的 0.166.0 实验与本人接受契约；不推广为所有版本内部缓存事实 |
| 微信上下文 | 不猜 TTL、未知投递保护 | channels／delivery；context_observation／context_recheck 测试 | W04、W08 已记录观察和确定性故障；自然失效触发仍未验证 |

## 使用与维护

增加／改变核心行为时更新对应需求、命令、设计、模块、测试及适用证据；没有真实证据就保留缺口，不用测试名称填作已通过。测试文件链接只保证可定位，验证执行结果须另记录。当前表按 DOC01 从源码与历史记录逐项核对；本轮未重新执行功能、原生或手机测试。
