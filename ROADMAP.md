# 当前进度

唯一项目进度源。设计文档与施工清单描述范围及要求，不作为完成声明。

## 当前阶段

MVP 已按确认范围交付。最近一次已记录的日常部署为独立非 editable 0.1.9／schema 6，路由快照 version 2；dev／main 和 annotated v0.1.9 已公开同步，实际加载与旧数据保护通过。[发布／切换证据](docs/validation/maintenance-release.md)。这是一份进度快照，不代表每次读文档均实时探测服务。

微信独立选择且首次接入无需状态栏／标题 ID：后台按注册根及已知准确 cwd 发现，准确原生身份／loaded／订阅复验；可见新建保留自有 boot 与唯一完成握手。桌面切换不改投，关闭窗口后以原生可用性为准，unknown 不重放。[当前身份契约](docs/native-session-identity.md)、[TGT02 验收](docs/validation/native-session-no-footer.md)。

DOC01 文档整理已验收交付：标准 PRD、五类实际渲染／视觉检查的架构图、现行技术与 ADR、开发／测试／安全／运维、导航及需求追溯齐备。16 个共同事实、22 项冲突／范围问题已复核关闭，113 个原文件逐项有处置。原生 Goal 已实际 complete，成果已随 0.1.9 公开交付。[施工清单](goals/20261108-0130-project-documentation-restructure.md)、[报告](docs/validation/documentation-restructure.md)。

`/sessions` 纯查询与 `/help` 核对已随 0.1.9 发布并本机加载：保留输入目标／观察／任务，不启动宿主或触发对账；退出输入目标使用 `/unfocus`。帮助覆盖 15 个命令及 6 个别名，开发阶段 765 项及最终版本 771 项检查通过。[修复与核对记录](docs/validation/sessions-query-help.md)。

冷启动零额外 Shell 修复已随 0.1.9 发布并本机加载：AppKit noop 首事件与退出即失效的启动参数，不写持久偏好；一次应用启动、一个窗口、双项目两个 Codex 标签、重复 cd 复用与自有终端清理通过，冻结制品 771 项通过。首轮失败保留，发布部署没有重复操作用户终端。[验收记录](docs/validation/iterm-single-window.md)。

## 交付状态与运行说明

- W00 至 W08、IMG01 单图、HOST01、MD01 Android 必要范围、PERF01，以及 REC01、ASK01、ENG01、AUD01、冷启动与 TGT01／TGT02 已按各自确认范围交付；不扩写为所有客户端、原生版本和交互全部通过。
- 最新版本的冻结制品、实际 argv／cwd／manifest、父子来源、唯一消费者、旧任务／unknown／冻结回执保护见 0.1.8 发布记录。原 756 项是该次冻结制品验证，本轮文档整改未重跑功能测试或操作日常服务。
- 长期分版本发布与本机证据见[本机交付索引](docs/validation/local-release.md)和各带日期记录；旧候选／已部署历史不再堆入当前阶段。初始工作包验收入口如下，后置范围仍见待办。
- 自有 MIT 及第三方原许可已公开同步；组合发行边界见[第三方声明](THIRD_PARTY_NOTICES.md)。历史 unknown 保留，准确占用释放不等于执行结果改成完成。

| 工作包 | 当前状态 |
| --- | --- |
| W00 | 已验收：[施工记录](goals/20261024-1644-w00-bootstrap.md) |
| W01 | 已验收：[施工记录](goals/20261024-1648-w01-protocol-baseline.md) |
| W02 | 已验收：[施工记录](goals/20261024-1653-w02-native-session.md)、[现场证据](docs/validation/w02.md) |
| W03 | 已验收：[施工记录](goals/20261024-2145-w03-interactions-queue.md)，专用入口 V03／V04 通过，原 TUI 反例保留 |
| W04 | 阶段验收完成：[施工记录](goals/20261025-0050-w04-wechat-text.md)，核心真机流程通过，自然过期项经本人确认转入 W08 |
| W05 | 已验收：[施工记录](goals/20261025-0906-w05-project-routing.md)、[真实证据](docs/validation/w05.md) |
| W06 | 已验收：[施工记录](goals/20261025-1702-w06-recovery-delivery.md)、[V07／V08 证据](docs/validation/w06.md) |
| W07 | 已验收：[施工记录](goals/20261025-2134-w07-foreground-operations.md)、[前台操作证据](docs/validation/w07.md) |
| W08 | 545 项整合、本机上线、稳定合并及远端公开交付完成，原生 Goal 已实际 complete，自然失效触发本人明确后置：[施工记录](goals/20261025-2148-w08-product-acceptance.md)、[本轮证据](docs/validation/w08.md#2026-11-01-上下文收尾) |
| IMG01 | 单图范围已验收交付：[施工清单](goals/20261028-1135-image-input.md)，单图真机、388 项离线及交付检查通过，原生 Goal complete，A03 本人后置；[实际证据](docs/validation/image-input.md)、[使用指南](docs/image-input.md) |
| HOST01 | 已验收交付，原生 Goal complete：[施工清单](goals/20261029-1038-host-lifecycle-recovery.md)，A01 至 A12、456 项回归通过，原日常配置已恢复；[证据](docs/validation/host-lifecycle-recovery.md) |
| MD01 | Android 必要范围已验收交付，原生 Goal complete：[施工清单](goals/20261029-1217-wechat-markdown-rendering.md)、[证据](docs/validation/wechat-markdown.md)、[排版规则](docs/wechat-markdown.md)。G00 至 G06／T01 至 T23／A01 至 A12、512 项回归及最终真人闭环通过，日常状态恢复；Mac 完整要求本人后置 |
| PERF01 | 隔离开发验收完成：[施工清单](goals/20261031-2132-performance-optimization.md)、[交付与数据](docs/validation/performance-optimization.md)。G00 至 G07／T01 至 T19／A01 至 A10、537 项回归及自动 SDK／原生通过；开发原生 Goal 已实际 complete，已由 W08 整合为 0.1.0／schema 4，后续本机沿用其能力并继续升级，准确版本见本页当前阶段 |
| REC01 | 已验收交付，原生 Goal complete：[任务准入恢复与项目完整收尾](goals/20261103-0020-admission-recovery-closeout.md)。G00 至 G09／T01 至 T27／A01 至 A12、580 项回归、本机 0.1.1／schema 5、原任务唯一 completed 通过；本轮完整 Git 提交／main 合并／v0.1.1 标签公开推送完成 |
| ASK01 | 0.1.2／schema 6 已本机加载，625 项／真实原生及负载通过；手机双向与 Git 公开归档完成，原生 Goal complete：[清单](goals/20261103-1038-async-question-bridge.md)、[证据](docs/validation/async-questions.md) |
| ENG01 | G00 至 G10／T01 至 T36／A01 至 A14 必要范围通过，原生 Goal 实际 complete；独立 0.1.3 已加载，680 项／原生／性能／保护检查通过，v0.1.3 和双分支已公开同步：[清单](goals/20261103-2356-engineering-hardening.md)、[记录](docs/validation/engineering-hardening.md) |
| AUD01 | 日志候选和原生限制契约已验收，原生 Goal 实际 complete；702 项及真实原生通过；v0.1.4 双分支／标签已公开同步，独立 0.1.4 本机切换及保护核验通过：[清单](goals/20261104-2338-native-diagnostics-rules.md)、[交付记录](docs/validation/native-diagnostics-rules.md) |


## 待办事项

- 0.167.0 后续验收：核心兼容已随 0.1.6 提交、main 合并、推送并部署，712 项及真实冷启动／运行保护通过。新版异步问题动态验收与图片手机整链路仍未完成，保持各自门禁与范围，不把核心通过扩写为全部功能通过。[记录](docs/validation/codex-0167-release.md)。

- 原生中断后的队列继续：0.166.0 专用验收中，一个准确已入队输入在原生 idle 状态保持 queued、零 turn；已准确取消该测试项，没有强制启动或重放。现桥接保留原生队列权威，后续应独立核对客户端暂停／显式继续语义，再决定是否增加受控恢复能力；不混入 ENG01 的性能和制品隔离范围。[阶段记录](docs/validation/engineering-hardening.md)。

- 第三方组合发行边界：iterm2 SDK 保持 GPLv2+。若后续需要承诺完整产品可闭源再发行，须先核清适用条件、取得额外授权或评估替代实现；当前未作该兼容性保证，不影响本项目自有作品采用 MIT。[第三方声明](THIRD_PARTY_NOTICES.md)。

- W08 后续观察：自然上下文失效和实际拒绝后恢复尚未触发，已获本人明确后置，不阻塞当前必要验收；183.069 小时旧值仍被 API 接受。不再预约／续发或推定固定 TTL；后续真实观察须有新授权，跨天调度先验证持久化与重启恢复。[证据](docs/validation/w08.md#2026-11-01-上下文收尾)。

- MD01 后续：Mac 完整排版与复制。本人于 2026-10-31 明确暂时后置，不阻塞本次 Android 交付；现 Mac 4.1.15.22 的复杂代码 M01／M03 仅复制 33／37、25／37 字节，M04 无代码块复制入口，三种括号链接写法均显示多余后缀。已保留原始复制／照片摘要和人工最小复现，恢复时先核对客户端／协议可行性，不沿用 API accepted 冒充通过。[完整证据](docs/validation/wechat-markdown.md)。

- IMG01 后续：同消息图文。本人于 2026-10-29 明确后置，不阻塞本次单图交付；当前客户端把一起发送的图片和文字拆为两条，只有解析覆盖，尚无单条图文真机证据。后续先确认可实际发送的客户端／协议形态，再验证一条原始消息对应一次带图文提交；不得用合成 inbox 或跨消息自动拼接冒充通过。[原 A03 要求](goals/20261028-1135-image-input.md)。

## 最近完成

- 2026-11-08 14:07 0.1.9 公开交付与本机切换：49 文件功能提交 666cf93、main 快进、annotated v0.1.9 及双分支／标签原子推送完成，GitHub API 独立核验通过。同一独立制品实际加载，唯一消费者及 host／native ready，638 条旧回执、两条 unknown 和原输入目标保持；正常停止至验收 16.231 秒，无迁移／数据恢复／重放或额外测试消息。结果文档单独归档，标签固定。[记录](docs/validation/maintenance-release.md)。

- 2026-11-08 13:50 冷启动默认 Shell 修复开发验收：改用 AppKit noop 与进程临时 startup 参数，沿用 SDK 创建及唯一原生握手；iTerm2 3.7.7／daemon 0.167.0 真实一次拉起、一个窗口／两个 Codex 标签、两次 cd 复用及安全清理通过，零额外 Shell。首轮失败保留；与此前 sessions／DOC01 一样尚未提交或部署。[记录](docs/validation/iterm-single-window.md)。

- 2026-11-08 12:46 sessions 纯查询与 help 核对：分离查询和选择事务，刷新／筛选不清目标、不释放订阅、不启动宿主、不触发创建或任务对账；显式 unfocus 保留观察和任务。补齐 15 命令／6 别名的前置、快照／ID、停止与答复格式，现行文档交叉同步；未提交、部署或处理多余 Shell。[记录](docs/validation/sessions-query-help.md)。

- 2026-11-08 02:16 DOC01 文档全面整理验收交付、原生 Goal 已实际 complete：G00 至 G10、T01 至 T26、A01 至 A14、D01 至 D08 齐备；标准 PRD、五类架构图及 SVG、9 条 ADR、真实接口／13 表、开发测试安全运维和需求追溯完成。16 事实／22 冲突关闭，历史正文与入口保全；仅文档改动，无 Git 发布或部署。[报告](docs/validation/documentation-restructure.md)、[清单](goals/20261108-0130-project-documentation-restructure.md)。

- 2026-11-08 01:36 DOC01 施工清单编制完成：明确标准 PRD、五类架构图、文档职责、产品边界、11 个检查点、26 项自测、14 条验收及 8 类交付，要求事实／冲突台账和跨文档复核。本轮只保存计划与同步进度，未创建原生 Goal、整改正文或更改运行环境。[清单](goals/20261108-0130-project-documentation-restructure.md)。

- 2026-11-07 17:37 TGT02 的 0.1.8 交付完成：38 文件提交 `f2de0ef`、main 快进、annotated v0.1.8、双分支／标签原子推送与远端核验通过；本机同一独立制品已加载，单消费者及 host／native ready。13 表备份、587 旧回执／两条 unknown／原未聚焦状态保护通过，17.423 秒请求停止至验收；无全局显示修改或额外测试消息。[交付](docs/validation/native-session-release.md)。

- 2026-11-07 16:15 TGT02 无状态栏 ID 候选交付：原生身份／稳定编号、有界发现、无页脚可见握手、v2 快照与旧指纹／历史结果兼容完成，schema 6 保持；真实双路径、切换／恢复及关闭／卸载通过，D01 至 D07 齐备。正式仍原 0.1.7，未发布、部署或改全局配置。[施工清单](goals/20261107-1453-native-session-no-footer.md)、[交付](docs/validation/native-session-no-footer.md)。

- 2026-11-07 14:59 TGT02 Goal 施工清单完成：定义无 ID 首次接入的两条路径、原生身份与可选宿主来源、稳定编号／恢复／旧记录及准确 cwd 范围，包含 10 个检查点、32 项自测、12 条验收与 7 类交付；先自主完成，必要本人配合集中收尾。本轮仅计划与 ROADMAP，未创建原生 Goal、改实现或操作生产。[清单](goals/20261107-1453-native-session-no-footer.md)。

- 2026-11-07 11:12 TGT01 的 0.1.7 发布部署完成：提交 `219912c`、main 快进、annotated v0.1.7 及双分支／标签原子推送、独立远端核验通过；同一冻结制品实际加载、单消费者及 host／native ready，原路由／587 旧回执／两条 unknown／配置保护通过，正常退出与 13 表备份完成，7.692 秒请求停止至验收。[发布交付](docs/validation/wechat-independent-release.md)。

- 2026-11-07 10:50 TGT01 微信独立选择候选交付：规范、首次关联／后续复验分离、旧绑定目录保留、受管恢复、失效提示及回归完成；0.167.0 原 A 上下文续接与 B 不串投、显式切换和关闭拒绝真实通过，723 项及必要检查通过。首次发现保留页脚依赖；未提交或部署。[清单](goals/20261107-1027-wechat-independent-target.md)、[交付](docs/validation/wechat-independent-target.md)。

- 2026-11-07 07:56 0.1.6 核心兼容发布部署：提交 bcc3c40、main 快进合并、双分支推送及独立远端核验后，切换同一冻结制品。host／0.167.0 native ready，旧回执与 unknown 保持；清除失效旧选择，唯一自然恢复通知 API accepted，无任务重放／新标签。[记录](docs/validation/codex-0167-release.md)。

- 2026-11-07 07:40 真实冷启动复测及 0.167.0 核心兼容候选完成：一条 `/cd`、真实应用／窗口创建各一次，11.772 秒就绪，准确身份／唯一 completed 启动轮次／空队列通过，自有端点清理，未发微信或直接写生产账本。协议 38 份逐字段核验及 712 项通过；未提交或部署。[记录](docs/validation/iterm-cold-start-live.md)。

- 2026-11-05 22:20 0.1.5 冷启动修复发布与本机切换：23 文件提交 165d375、main 快进合并、注释标签及双分支原子推送／独立远端核验完成；同一冻结制品已加载，host／native ready，原数据与配置保持。stopped 至验收 117.064 秒，真实冷启动未复测；仅结果文档后续归档，标签固定。[记录](docs/validation/iterm-cold-start-release.md)。

- 2026-11-05 22:06 iTerm2 冷启动开发修复：首次按需连接增加同进程有界传输等待及退避，授权／创建不重试，后台及未知任务语义保持。核心回归先失败后通过；新增命令链路验证首次 `/cd` 只创建一次且 `/help` 可响应。尚未部署或做真实冷启动复测。[记录](docs/validation/iterm-cold-start-investigation.md)。

- 2026-11-05 21:47 AUD01 本机独立 0.1.4 切换：复用冻结制品，旧实例退出 0、13 表备份与原 Label 重载完成；新实际加载／单消费者／host、native ready 通过，正常停服至验收 26.119 秒。旧回执／unknown／路由／配置保持，无迁移或 Git 写操作。[记录](docs/validation/aud01-local-deployment.md)。

- 2026-11-05 21:21 AUD01 0.1.4 Git 交付：22 文件功能提交 88ba09f、独立工作树 main 快进合并、annotated v0.1.4 及双分支／标签原子推送完成，独立远端引用核对一致；只归档结果文档，标签固定，本机仍运行独立 0.1.3。[发布记录](docs/validation/aud01-publication.md)。

- 2026-11-05 21:09 AUD01 整体候选交付：本人明确接受原生限制方案，项目规范／设计契约／使用运维与交付材料同步，G00 至 G07、T01 至 T26 适用范围及 A01 至 A12 通过，原生 Goal 实际 complete。日志修复未部署，未外发微信／执行 Git 写操作，无需追加配合。[清单](goals/20261104-2338-native-diagnostics-rules.md)、[交付](docs/validation/native-diagnostics-rules.md)。

- 2026-11-05 14:14 AUD01 自主交付和现场收尾：R01 真实断连入日志及第二代恢复、R02 同一原会话九轮反例／十轮历史核对完成；准确自有终端清理，原两终端／生产进程／四份配置保护通过。仅余 A06 责任契约由本人决定，整个 Goal 未完成，未部署／发布。[交付记录](docs/validation/native-diagnostics-rules.md)、[具体提案](docs/project-rules.md#已确认的原生限制契约)。

- 2026-11-05 00:21 AUD01 自主阶段交付：R01 修复及有界脱敏日志、规则源码证据／正式实验入口、候选 wheel／manifest 和阶段文档已准备；整个 Goal 未完成，原会话实验及路径决定待本人配合，未部署或发布。[记录](docs/validation/native-diagnostics-rules.md)。

- 2026-11-04 23:42 AUD01 施工清单制定：明确日志故障可见性及规则加载责任闭环的目标、边界、自测、验收和交付文档；原生能力不足时不得仅删承诺即宣告修复。仅编写清单与进度导航，未创建 Goal、修改实现、部署或外发微信。[清单](goals/20261104-2338-native-diagnostics-rules.md)。

## 最近验证

- 2026-11-08 14:07 0.1.9：冻结制品 771 项／40.413 秒、编译／依赖／文档／diff 通过，56 个非版本包文件与真实验收候选相同；85 份 Markdown、1003 个本地链接／锚点通过。13 表一致性备份及外键／完整性、实际 argv／cwd／父子 manifest、唯一消费者、原生准确路由与旧行保护通过。新增提交／tag、公开文件与两份制品私密值审计零匹配，最终归档继续复核。[摘要](docs/validation/maintenance-release.json)。

- 2026-11-08 13:50 第二冻结候选真实冷启动：四条合成 cd、两个唯一 completed 握手，launch／wait_ready／connect 各一次、终端创建两次；核验阶段 26.344 秒。两个自有终端清理并复验缺席，收尾零窗口／终端，受保护配置及持久启动偏好保持。冻结包 771 项／40.319 秒及编译／依赖／文档／diff 通过，源码一致；无真实微信或生产账本直接写入。[摘要](docs/validation/iterm-single-window.json)。

- 2026-11-08 13:06 冷启动窗口候选：两个新断言在旧 lifecycle 实现均预期失败；34 项宿主、771 项／40.418 秒及编译／依赖／文档／diff 通过。iTerm2 3.7.7 启动脚本实际编译，已运行应用 launch 后 PID、两个窗口／标签／终端和受保护配置保持。双项目显式入口 help／编译通过，真实冷启动未执行。[记录](docs/validation/iterm-single-window.md)。

- 2026-11-08 12:46 sessions：3 个新回归在旧实现均复现预期失败；最终 765 项／40.097 秒、编译／依赖／文档／diff 通过。focused／managed、各订阅、空结果／失败／换代／并发、无宿主查询及卸载不改投覆盖；help 渲染单段 1499 字符。初次 17 项 Unix socket 沙箱拒绝后正常权限重跑通过；没有真实原生／手机／部署验收。[记录](docs/validation/sessions-query-help.md)。

- 2026-11-08 02:16 DOC01：16 条 CLI／构建 help、五图实际解析／SVG／PNG 渲染与视觉检查、源码事实／13 表／原章节去向、三类读者纸面走查、现有 documents、扩展链接／锚点／JSON／历史正文／示例语法／公开内容模式及 diff 检查通过。未重跑旧 756 项或真实原生／微信／部署验收，专项未测边界保持。[机器摘要](docs/validation/documentation-restructure.json)。

- 2026-11-08 01:36 DOC01 清单核对：G00 至 G10／T01 至 T26／A01 至 A14／D01 至 D08／B01 至 B12／F01 至 F05 编号连续，目标、边界、PRD／图形专项、历史保全及跨文档验收齐备。四份一手结构资料已打开核对；文档 JSON／链接／锚点、记录数量及差异格式通过，仅校验清单，没有执行整改、自测矩阵或运行时操作。[清单](goals/20261108-0130-project-documentation-restructure.md)。

- 2026-11-07 17:37 0.1.8 冻结独立制品 756 项／40.883 秒及编译／依赖／文档通过，56 个非版本包文件与无 ID 原生验收候选相同。实际 argv／cwd／manifest／父子来源／单消费者、schema 6、13 表备份及旧数据核验通过；路由快照 v1→v2，未重定向或通知。公开文件／两份制品／完整可达历史隐私审计零匹配，配置／凭据／全局设置与原生进程保持。[摘要](docs/validation/native-session-release.json)。

- 2026-11-07 16:15 TGT02 冻结独立制品 756 项／40.640 秒、编译／依赖／文档及根差异通过，57 包文件与实际原生源码一致。0.167.0 无 ID 首次 A／B 接入、7 个准确业务 client／turn completed、同进程桌面变化不改目标、真实重启恢复及卸载拒绝通过；延迟卸载后只读续验，无业务重放。自有终端清理、配置摘要保持、正式原 manifest／双组件 ready；零微信发送／直接生产写入。[脱敏摘要](docs/validation/native-session-no-footer.json)。

- 2026-11-07 14:59 TGT02 清单核对：G00 至 G09／T01 至 T32／A01 至 A12／D01 至 D07 编号连续且均为未执行状态；目标、范围、失败路径、可行性关卡、自测、验收和交付齐备，本地文档链接／锚点、最近记录数量及差异格式检查通过。仅文档校验，不重跑代码测试、不连接原生或微信，不更改日常设置。[清单](goals/20261107-1453-native-session-no-footer.md)。

- 2026-11-07 11:12 0.1.7 独立制品 723 项／40.526 秒、编译／依赖／文档／diff 与 57 文件 manifest 通过；277 公开文件、2827 私密候选、两份制品及可达历史零匹配。实际 argv／cwd／父子来源／单消费者／双组件 ready，13 表备份完整性、原路由和 587 回执／投递尝试／两条 unknown／其余 10 表逐行保护通过。零迁移／恢复／额外微信测试／原生提交，远端双分支与注释标签独立复核。[机器摘要](docs/validation/wechat-independent-release.json)。

- 2026-11-07 10:50 TGT01 最终 723 项／40.393 秒、编译／依赖／差异／文档通过；初次全量的 17 项 Unix socket bind 被沙箱拒绝，正常权限下完整通过。0.167.0 持续订阅下 A→B 后原 A 唯一 client／turn completed 并回忆启动标记，B 历史／显示不变，显式 B completed，关闭后零新增任务且提示；断连卸载 A 的拒绝及并发目录登记先失败后通过。22 份变更的私有标识与格式检查零匹配，配置保护和专用端点清理通过，零微信测试发送／直接生产账本写入。[脱敏摘要](docs/validation/wechat-independent-target.json)。

- 2026-11-07 08:38 线程身份替代路线调研：核对本机 0.167.0 的 180 请求／86 通知及线程／初始化字段，结合官方 loaded/list、Hooks、标题说明；未证实桌面当前选择的后台接口，记录可行路线及待验收边界。仅研究文档，无代码／配置／UI／运行时改动。[记录](docs/validation/thread-identity-alternatives.md)。

- 2026-11-07 07:56 0.1.6 独立制品 712 项／40.498 秒及编译／依赖／文档／公开审计通过；57 包文件及真实冷启动候选仅版本声明差异。实际进程／cwd／manifest／父子加载／唯一消费者／双组件 ready，13 表备份、旧 584 回执及投递尝试、两条 unknown 和 10 业务表保持；自然通知发送后复验，无重启重发。[摘要](docs/validation/codex-0167-release.json)。

- 2026-11-07 07:40 0.167.0：匹配可执行文件生成 470 schema、核对 38 份契约，原基线摘要一致；新握手回归先失败后通过，712 项／40.529 秒及编译／依赖／文档通过。真实冷启动调用 launch／wait_ready／connect／create 各一次，配置保持、已关闭准确测试端点；生产仍原制品，候选与手机验收范围单列。[摘要](docs/validation/iterm-cold-start-live.json)。

- 2026-11-05 22:20 0.1.5 独立制品 711 项／51.851 秒及编译／依赖／文档通过；264 文件、2770 私密候选、两份制品与可达历史零匹配。实际 argv／cwd／manifest／父子加载及单消费者／host、native ready 通过；13 表备份，12 非路由表逐行一致，576 旧回执／两条 unknown／原路由与配置保持。正常退出状态初检竞态已核实并继续，无强杀或数据恢复。[摘要](docs/validation/iterm-cold-start-release.json)。

- 2026-11-05 22:06 冷启动修复：宿主／传输 28 项、命令 71 项、运行生命周期 20 项及完整 711 项／42.891 秒通过；编译／依赖／差异／文档通过，离线零微信／原生提交／生产写入。真实冷启动验收未执行，原独立 0.1.4 不变。[记录](docs/validation/iterm-cold-start-investigation.md)。

- 2026-11-05 21:57 iTerm2 冷启动调查：只读回执／启动登记与代码路径对照，首条命令在创建前约 0.245 秒失败，第二条才启动成功；真实 HostLifecycle 离线模拟复现一次连接失败即结束、下一请求成功。零真实启动／外发／任务，未改实现或重启；v0.1.3→v0.1.4 相关代码无变化。[记录](docs/validation/iterm-cold-start-investigation.md)。

- 2026-11-05 21:47 AUD01 部署核验：0.1.4 manifest／实际进程 argv／cwd／源码与父子隔离加载通过；12 张非路由表逐行一致、原路由角色与目标保持，568 旧回执和两条 unknown 保留。配置／凭据／全局设置／原生进程保持，schema 6、唯一消费者及 host／native ready，额外微信测试和原生提交均为零。[摘要](docs/validation/aud01-local-deployment.json)。

- 2026-11-05 21:21 AUD01 发布核验：独立非 editable 0.1.4 完整 702 项／39.968 秒及编译／依赖／文档通过；57 个包文件与新 manifest 一致，较真实验收候选仅版本声明变化。259 公开文件、2736 私密候选、两份制品及 1164 个可达对象零匹配；双分支／标签独立远端核验及生产保护通过。[摘要](docs/validation/aud01-publication.json)。

- 2026-11-05 21:09 AUD01 完工审计：702 项全量原始日志及最终 12 项定向、真实十轮历史／九轮规则实验／断连恢复与现场保护证据通过；57 个包文件与冻结制品一致，18 份公开变更／6 个私密候选零匹配，文档／JSON／链接／差异格式通过；已确认原生限制契约，Goal 实际 complete。[摘要](docs/validation/native-diagnostics-rules.json)。
