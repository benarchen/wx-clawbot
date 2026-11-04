# 当前进度

唯一项目进度源。设计文档与施工清单描述范围及要求，不作为完成声明。

## 当前阶段

ENG01 已验收交付，原生 Goal 已实际 complete：本机已运行独立非 editable 0.1.3／schema 6，父子制品、唯一消费者及 host／native ready 核验通过；根工作区 680 项／43.102 秒、两轮 120 秒负载及真实原生组件关卡通过。旧冻结／unknown／配置保持，自有终端清理；测试微信零，正常恢复通知一条 API accepted。本人后续授权的 50 文件完整提交 425fda5、main 正常合并、annotated v0.1.3 及 GitHub 原子推送已完成，独立远端核验一致；仅追加实际结果文档，不移动标签。[清单](goals/20261103-2356-engineering-hardening.md)、[交付记录](docs/validation/engineering-hardening.md)、[Git 发布记录](docs/validation/eng01-publication.md)。

上一公开版本 `0.1.2`／schema 6 的 ASK01 修复已完成 625 项回归、120 秒负载、真实原生、构建／安装和一次 Android 手机双向验收；当时原路由恢复、测试终端归零、旧冻结／unknown／配置保持。该原生 Goal 已实际 complete，main／dev 与 annotated v0.1.2 已公开同步；其后 ENG01 已另行完成 v0.1.3 公开发布。[分版本本机记录](docs/validation/local-release.md)。

自有代码和文档的 MIT 许可、第三方清单及包元数据已随 v0.1.2 提交并公开推送，第三方依赖保持原授权；完整组合产品的发行边界不因自有 MIT 声明改变。[许可记录](docs/validation/mit-license.md)、[版本发布](docs/validation/ask01-publication.md)。

ASK01 已验收交付，原生 Goal 于 2026-11-03 21:31 实际 complete。G00 至 G09、T01 至 T32、A01 至 A12 按本人接受的异步补充模式通过；跨端可能同时被接受，桥接单次提交和冲突提示，不承诺暂停或全局首答独占。[使用契约](docs/async-questions.md)、[交付证据](docs/validation/async-questions.md)。

W00 至 W07、IMG01 单图、HOST01、MD01 Android 和 PERF01 必要范围已验收。W08 必要范围已验收交付，本机上线及 dev／main 正常公开同步完成，原生 Goal 已完成；生产工作区保持 `dev`，稳定 `main` 由独立工作树合并，避免切分支影响运行。后置的自然失效触发、Mac 完整排版及同消息图文不改写为通过；W08 当时未创建 tag 或 GitHub Release。

2026-11-03 日常准入阻塞已由 [REC01](goals/20261103-0020-admission-recovery-closeout.md)解决：任务结果与仓库占用分离，安全自动核验、带审计处置和有界等待生效。G00 至 G09、T01 至 T27、A01 至 A12 必要范围通过，最终核对后原生 Goal 已实际 complete；无需本人追加操作。本人后续授权的完整提交、main 正常合并、v0.1.1 标签及 GitHub 公开推送已完成；结果见[版本交付](docs/validation/rec01-publication.md)。

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

## 交付状态与运行说明

- W00 至 W08、IMG01、HOST01、MD01 和 PERF01 原 13 个工作包按当时确认范围交付；REC01 已验收交付并消除对应准入阻塞。新增 ASK01 修复已加载且必要真人交付通过，原有后置能力继续保留；不将旧交付扩写为所有 CLI 交互均已支持。
- 本轮之前的 0.1.1／schema 5 已发布记录保留：生产工作区为 `dev`；功能提交 `387e7ac` 已正常合并 main，两个分支和 annotated v0.1.1 公开推送、独立远端核验通过。随后仅归档实际发布结果，不移动标签或改变运行代码；未创建 GitHub Release，无需再次重启已健康加载的服务。
- 初次公开推送曾被自动审批要求具体确认；本人随后明确授权公共目的地与完整内容，正常推送及远端核验成功。该门禁已解决，不再列为当前阻塞。
- 历史 unknown 2 结果保留不重放，现已按准确原生终态解除占用，不再阻塞项目；原等待任务唯一 completed。原生 hook 告警仍按历史证据保留，本轮不修改全局 hook。[REC01 实际记录](docs/validation/admission-recovery.md)。

## 待办事项

- 原生中断后的队列继续：0.166.0 专用验收中，一个准确已入队输入在原生 idle 状态保持 queued、零 turn；已准确取消该测试项，没有强制启动或重放。现桥接保留原生队列权威，后续应独立核对客户端暂停／显式继续语义，再决定是否增加受控恢复能力；不混入 ENG01 的性能和制品隔离范围。[阶段记录](docs/validation/engineering-hardening.md)。

- 第三方组合发行边界：iterm2 SDK 保持 GPLv2+。若后续需要承诺完整产品可闭源再发行，须先核清适用条件、取得额外授权或评估替代实现；当前未作该兼容性保证，不影响本项目自有作品采用 MIT。[第三方声明](THIRD_PARTY_NOTICES.md)。

- W08 后续观察：自然上下文失效和实际拒绝后恢复尚未触发，已获本人明确后置，不阻塞当前必要验收；183.069 小时旧值仍被 API 接受。不再预约／续发或推定固定 TTL；后续真实观察须有新授权，跨天调度先验证持久化与重启恢复。[证据](docs/validation/w08.md#2026-11-01-上下文收尾)。


- MD01 后续：Mac 完整排版与复制。本人于 2026-10-31 明确暂时后置，不阻塞本次 Android 交付；现 Mac 4.1.15.22 的复杂代码 M01／M03 仅复制 33／37、25／37 字节，M04 无代码块复制入口，三种括号链接写法均显示多余后缀。已保留原始复制／照片摘要和人工最小复现，恢复时先核对客户端／协议可行性，不沿用 API accepted 冒充通过。[完整证据](docs/validation/wechat-markdown.md)。


- IMG01 后续：同消息图文。本人于 2026-10-29 明确后置，不阻塞本次单图交付；当前客户端把一起发送的图片和文字拆为两条，只有解析覆盖，尚无单条图文真机证据。后续先确认可实际发送的客户端／协议形态，再验证一条原始消息对应一次带图文提交；不得用合成 inbox 或跨消息自动拼接冒充通过。[原 A03 要求](goals/20261028-1135-image-input.md)。

## 最近完成

- 2026-11-04 22:46 ENG01 0.1.3 Git 交付：50 文件功能提交 425fda5、独立工作树 main 快进合并、annotated v0.1.3 及 main／dev／标签原子推送完成，独立远端引用核对一致。注释明确变更／验证／性能取舍及能力边界；仅归档结果文档，不移动标签、不重启服务。[发布记录](docs/validation/eng01-publication.md)。

- 2026-11-04 13:36 ENG01 工程交付：R01 至 R07、独立非 editable 0.1.3／schema 6 本机切换完成；680 项、真实原生组件及最终两轮负载通过。旧数据／配置保持，自有终端清理；临时模型精确恢复，无需本人追加配合，Git 未执行。原生 Goal 已实际 complete。[交付记录](docs/validation/engineering-hardening.md)。

- 2026-11-04 00:05 ENG01 施工清单制定：将全面审查前四项收敛为 G00 至 G10、T01 至 T36、A01 至 A14，冻结停止候选、有界发现、非 editable 制品、性能测量门槛及交付文档；生产切换／必要配合置后，新增功能和 Git 发布不在本次计划授权内。仅编写清单与导航，未创建 Goal、改实现、部署或发送微信。[清单](goals/20261103-2356-engineering-hardening.md)。

- 2026-11-03 21:52 0.1.2 Git 交付：41 文件功能提交 ab8f8b9 纳入 ASK01 与自有 MIT 许可；main 独立工作树快进合并，main／dev／annotated v0.1.2 原子推送并独立远端核验通过。标签固定功能提交，随后仅归档结果文档；运行源码及本机健康保持，无重启或额外微信发送。[发布记录](docs/validation/ask01-publication.md)。

- 2026-11-03 21:31 ASK01 完整交付：结构化异步即时通知、准确原轮次答复、严格辅助输入及竞争／重启／迁移保护完成。625 项回归、120 秒负载、真实原生和 Android 手机 8 条回执闭环通过；0.1.2／schema 6 已加载，旧 530 冻结／2 unknown／配置保持、原路由恢复、测试终端归零，G00 至 G09／T01 至 T32／A01 至 A12 通过，原生 Goal 实际 complete。未提交／推送。[交付](docs/validation/async-questions.md)。

- 2026-11-03 10:49 ASK01 施工清单制定：明确先验证原生双向路径，再实现异步问题通知、准确答复、辅助输入关联、状态／恢复、迁移与最终验收，列出 G00 至 G09、T01 至 T32、A01 至 A12 和交付文档。同步当前异步能力缺口；只完成文档，未开工、未创建原生 Goal，不改运行程序或服务，原 MIT 工作区成果保留。[清单](goals/20261103-1038-async-question-bridge.md)。

- 2026-11-03 09:49 MIT 许可本地落实：新增完整 LICENSE 与 10 个锁定依赖的第三方清单，补齐 SPDX／随包元数据及受影响文档；官方 SDK 原包和固定源码核对保留 GPL 边界。源码包／wheel／隔离安装与 580 项回归通过，54 个源码模块与依赖锁保持。未提交、合并、推送、移动标签或重启服务。[记录](docs/validation/mit-license.md)。

- 2026-11-03 08:07 REC01 版本归档及公开发布：本人明确授权后完整 47 文件提交 387e7ac、独立工作树正常合并 main，annotated v0.1.1 指向功能交付；dev／main／标签原子推送成功且独立远端引用一致。随后仅同步实际发布结果文档，不移动标签、不强推、不创建 Release；当前 0.1.1／schema 5 源码及健康保持，无需重启。[发布记录](docs/validation/rec01-publication.md)。

- 2026-11-03 03:25 REC01 完整交付：分离未知结果与占用，准确原生终态自动释放两条历史占用，原 received 原目标唯一 completed、冻结结果精确且 API accepted。580 项、真实原生、120 秒负载及全仓／制品／隐私检查通过，原入口加载 0.1.1／schema 5、9 个旧业务表迁移精确、旧回执／配置保护、自有终端清理；G00 至 G09／T01 至 T27／A01 至 A12 通过，原生 Goal 已实际 complete。本轮 44 文件未提交／推送。[交付](docs/validation/admission-recovery.md)、[全项目检查](docs/validation/project-closeout.md)。

- 2026-11-03 00:29 REC01 施工清单制定完成：明确任务结果与仓库占用分离、自动核验与安全释放、人工处置和有界等待，列出 G00 至 G09、T01 至 T27、A01 至 A12、全仓检查及交付文档。本轮只更新计划与当前进度，修复和上线尚未执行；不将旧交付状态用于否认当前阻塞。[清单](goals/20261103-0020-admission-recovery-closeout.md)。

- 2026-11-02 21:20 W08 最终正式交付：本人明确公共仓库及完整内容授权后，获批 a6960eb 的 main／dev 正常原子推送成功，远端引用相同、默认 main；后续仅发布结果文档同步。545 项／本机 `0.1.0`／schema 4／原数据与配置保护通过，所有必要 D01 至 D07 完成，原生 Goal complete；三项后置范围保持。[交付记录](docs/validation/local-release.md)。

- 2026-11-02 00:49 W08 本机 `0.1.0` 上线与本地交付完成：整合 545 项、性能／持续负载／迁移及完整隐私审查通过，原桥接正常停服 236.731 秒后健康恢复，真实 schema 3→4 备份／业务行精确，81 条任务／463 条回执与配置保持。源码提交并正常合并本地 main，运行工作区始终 dev；公开推送因自动审批要求具体确认未执行，W08 Goal 尚未完成。[实际记录](docs/validation/local-release.md)。

- 2026-11-01 23:53 W08 上下文必要范围收尾：按本人决定后置不可控的自然失效触发，先修订契约／清单，再交付即时一次验收器及 8 项有效回归。183.069 小时旧值单次 API accepted，无需真人追加操作；完整工作区 520 项通过，结果保留／新上下文明确重试／任务不重跑／unknown 不重试已验证。原 case／旧预约／生产账本与配置保持，未继续长等、部署或执行 Git 发布。[记录](docs/validation/w08.md#2026-11-01-上下文收尾)。

- 2026-10-31 23:32 PERF01 隔离开发交付：有界事件／结果和临时 CPU 子进程、单调用 SDK 目录复用、schema 4 三索引／显式迁移、提交后发送唤醒及等价渲染完成。537 项、100 次重叠追问、120 秒负载／60 秒闲时、真实 SDK／原生及交付检查通过；完整源码补丁／文件摘要／原始数据齐全。日常源码／schema 3／81 条任务及 448 条回执保持，临时配置逐字恢复、自有终端清理；未部署、迁移、提交或外发微信。[交付](docs/validation/performance-optimization.md)。

- 2026-10-31 17:52 本地版本管理整理：以 `dev` 当前可验证状态归档单图输入、宿主恢复、托管、双版本协议兼容及 Android 排版，源码／测试／依赖与 512 项通过摘要一致。保留 `0.1.0.dev0` 开发版本和 W08 未完成状态，私有运行数据、截图、原复制文件与任务临时目录排除；不合并、推送或创建发布标记。

- 2026-10-31 17:10 MD01 Android 范围完工：G00 至 G06、T01 至 T23、A01 至 A12 通过，512 项完整回归；最终真人文字五段、单图／准确追问、37／56 字节复制及旧同文长结果证据齐全。修正已加载，日常目标／观察与临时设置恢复、自有测试终端清理，旧 412 条冻结及 76 条任务保持，原生 Goal 实际 complete。Mac 完整要求后置、W08 未完成项保留，不提交／推送。[交付](goals/20261029-1217-wechat-markdown-rendering.md)、[证据](docs/validation/wechat-markdown.md)。

- 2026-10-30 07:47 HOST01 完工：G00 至 G06、A01 至 A12 通过，最终 456 项回归；真机应用恢复、按需启动、原会话连续性、交互／控制、0.166.0 单图及换代只读终态对账通过。临时信任及自有终端已清理，日常唯一托管消费者／两项目配置恢复，最后本人收件与链接／隐私检查通过，原生 Goal complete。W08 未通过项保留，不提交／推送；MD01 待本人确认。[交付](goals/20261029-1038-host-lifecycle-recovery.md)、[验证](docs/validation/host-lifecycle-recovery.md)。

- 2026-10-29 21:02 桥接持续运行补救交付：按本人授权恢复原配置微信收发，部署唯一用户级 launchd、异常限速重启、正常停止及有界私有诊断。443 项回归和独立真实 launchd 退出策略通过，正式交接原配置／schema／任务摘要保持，托管后本人 `/sessions`／`/status` 收件通过。HOST01 应用生命周期仍联试，不启动 MD01，不提交或推送。[运维](docs/operations.md)、[交付证据](docs/validation/bridge-supervision.md)。

- 2026-10-29 07:57 IMG01 单图输入交付：本人明确后置同消息图文，A03 进入待办；其余必要关卡及文档验收完成，原生 Goal complete。支持本人单张 JPEG／PNG 的原线程看图、连续追问、固定路由、FIFO、取消／中断及不重放恢复；真实账本备份升级到 3，日常配置和选择已恢复。388 项离线通过，未提交、合并、推送或部署；W08 原关卡保留。[指南](docs/image-input.md)、[验收](docs/validation/image-input.md)、[施工交付](goals/20261028-1135-image-input.md)。

- 2026-10-28 08:01 修复日常启动被新版原生运行时拒绝：为现场 0.165.0 补齐 33 份桥接协议定义核对和版本基线，保留未知版本拒绝；真实握手与正式配置 doctor 通过，323 项离线回归通过。前台持续运行及微信任务尚未重测，未操作用户终端或发送测试消息；自然失效／恢复仍等待。[范围](docs/protocol-baseline.md)。

## 最近验证

- 2026-11-04 22:46 ENG01 发布前后核验：680 项（39.681 秒）及编译／依赖／差异／文档通过；251 份公开文本与全部 1118 个可达对象、2637 个私密候选值扫描零匹配。双分支／标签远端准确，服务实际进程／代次／源码保持，host／native ready。[机器记录](docs/validation/eng01-publication.json)。

- 2026-11-04 13:30 ENG01 根目录最终检查：680 项（43.102 秒）、编译／依赖／差异／文档通过；准确 manifest／父子源码／实际 PID／cwd／唯一消费者和 host／native ready 核对。原 539／当前 540 冻结、两条 unknown 及其他业务表保持；最终负载 p95 22.646／19.252、最大 179.893／203.267 毫秒。[机器摘要](docs/validation/engineering-hardening.json)。

- 2026-11-04 09:19 ENG01 冻结制品离线核对：全新工程副本未复制旧临时产物／editable 环境，676 项（47.512 秒）、编译／依赖／文档通过；同制品托管隔离、单消费者、SIGTERM、错误摘要拒绝及 0.1.2 兼容读取新合成行通过。真实原生、性能最终门槛与生产切换仍未完成；零真实微信及 Git 写操作。[阶段证据](docs/validation/engineering-hardening.md)。

- 2026-11-04 00:07 ENG01 清单核对：G00 至 G10／T01 至 T36／A01 至 A14 编号连续，35 项施工步骤均未勾选；本清单及两份导航的本地路径、最近记录条数和差异格式检查通过。业务代码、测试、依赖、AGENTS 和 README 保持；仅文档验证，未重跑回归、创建 Goal、切换服务或外发微信。[清单](goals/20261103-2356-engineering-hardening.md)。

- 2026-11-03 21:26 ASK01 最终手机／收尾核对：本人确认实收并回答，准确原 turn／两 client 各一次、observed／completed、精确冻结与 8 条 accepted 通过；旧 530 冻结／2 unknown／配置保持，原路由恢复、测试终端归零，0.1.2／schema 6／原 Label ready。额外清理重载的原因和备份分列，源码未变、无额外测试消息；待 Goal 返回登记。[证据](docs/validation/async-questions.md)。

- 2026-11-03 15:01 ASK01 候选及本机核验：625 项回归（37.652 秒）零失败／错误／跳过；120 秒负载、100 次通知 p95 2.187 毫秒、3952 次控制 p95 4.142 毫秒及真实原生唯一答案通过。原 Label 已加载 0.1.2／schema 6，迁移旧 12 表精确，530 旧冻结／2 unknown／配置保持；零真实测试外发，手机关卡待授权。[证据](docs/validation/async-questions.md)。

- 2026-11-03 12:47 ASK01 辅助输入归属审查：核对在线映射、桌面任务收养、普通／外部／换代恢复及独立占用释放路径；隔离候选四项既有合并／重复 client 保护测试通过，属于 580 项基线的定向复核，不增加总数。明确后续准确辅助分类约束，未修改业务代码或越过 G01；产品边界仍待确认。[记录](docs/validation/async-questions.md)。

- 2026-11-03 12:39 ASK01 原生准入调查：六个真实合成问题任务证明单题／自由文字／多题答案进入原 turn，错误及已结束 turn 拒绝；但两端相反答案均被接受且有 ACK 后不可见窗口，G01 保持未通过。580 项旧基线（36.448 秒）通过、异步最小反例单列预期失败；两自有终端已清理，原源码／配置和 12 张生产业务表摘要保持，schema 5／原服务健康。[证据](docs/validation/async-questions.md)。

- 2026-11-03 10:49 ASK01 计划核对：10 个 G、32 个 T、12 个 A 编号完整，38 个施工执行项均未勾选；清单与相关文档本地链接、差异格式及隐私内容检查通过。8 份其他既有改动文件摘要保持，未修改业务代码、执行运行测试、迁移、重启、外发微信或 Git 写操作；先前原生字段证据不冒充新能力验收。[清单](goals/20261103-1038-async-question-bridge.md)。

- 2026-11-03 09:49 MIT 交付核对：580 项离线回归（35.976 秒）、编译／依赖／差异检查通过；隔离源码包和 wheel 均含两份原文声明，MIT 元数据及六项直接依赖准确，独立目标安装可读取许可证。10 个锁定运行发行包与 12 份许可文件逐项核对，制品无内置依赖或私有运行数据；SDK 专用授权例外未取得，不将自有 MIT 扩大为组合产品闭源许可。[机器摘要](docs/validation/mit-license.json)。

- 2026-11-03 08:07 公开提交与标签核验：218 文件、974 可达对象（42 commit／629 blob／1 tag）与 2422 个私密值／密钥格式核对无匹配；140 份源码／测试／锁与 580 项已测候选相同，编译／依赖／差异／JSON／本地链接通过。GitHub public／默认 main／推送权限及远端三引用独立核对通过，运行摘要与托管进程一致，未执行额外重启。[机器记录](docs/validation/rec01-publication.json)。

- 2026-11-03 03:25 REC01 最终本机复核：唯一托管消费者、host／native ready、schema 5／加载摘要／doctor 0.166.0 通过；原任务 client／turn 各一次、completed／空队列、最终冻结渲染精确且 accepted，unknown 2 保留且已释放。旧 502 回执等原始行保持，路由仅 revision／时间变化，5 个自有测试终端不存在；140 份源码／测试／锁与已测候选相同，215 文本／2422 个私密值无泄露、本地无断链、差异格式通过。[数据](docs/validation/admission-recovery.json)。

- 2026-11-03 02:59 REC01 开发验收：580 项回归（36.153 秒）、编译／依赖锁／全新 wheel 安装及隔离渲染通过；真实原生两任务及资源清理、120 秒固定种子负载、10 万行迁移与查询通过。215 份文本／373 个实际私密候选值无泄露、无本地断链；原等待目标和两旧 turn 只读复核通过。真实账本仍 schema 4，准备按既有授权受控切换。[证据](docs/validation/admission-recovery.md)。

- 2026-11-03 00:31 REC01 文档检查：10 个 G 检查点、27 个 T 自测和 12 个 A 验收编号完整，施工项均未勾选；清单及 ROADMAP 本地链接有效、最近记录各不超过 20 条，清单无真实私人路径，差异格式通过。仅文档核验，未运行代码回归、操作微信、迁移账本或部署。[清单](goals/20261103-0020-admission-recovery-closeout.md)。

- 2026-11-02 21:20 最终公开交付核对：201 文件和所有历史与 313 个实际私密候选值／密钥格式核对无匹配；a6960eb 时 906 个可达对象、577 个 blob、40 个 commit 通过。SSH 读取远端 main／dev 均为获批提交，GitHub API 确认为 public、默认 main；运行源码摘要未变，后续纯交付文档再复核。[数据](docs/validation/local-release.json)。

- 2026-11-02 00:49 首版最终本地复核：545 项（35.872 秒）、父／子包加载、编译／依赖、doctor 0.166.0、唯一托管消费者／host／native ready、schema 4／索引及原业务行通过；提交后 896 个可达对象／572 个 blob／39 个 commit 与实际私密值核对无匹配。未操作微信 UI、外发样例或派发原生任务，公共仓库推送未执行。[数据](docs/validation/local-release.json)。

- 2026-11-01 23:53 W08 即时观察与失败恢复：冻结新意图单次发送、实际源年龄 183.069 小时、API accepted，非本人收件证明；新值恢复前置未发生故未发送第二条。520 项（37.101 秒）、编译／差异检查通过；81 条任务与 463 条回执、schema 3、原始记录和配置摘要保持。[机器证据](docs/validation/context-recovery.json)。

- 2026-11-01 09:48 W08 七天观察结果核对：只读检查冻结计划／case／独立启动记录、响应文件和准确旧 PID；进程不存在，追加尝试 0、无发送意图／第四次响应，原三次 accepted 保持。窗口已过，未补发或重建；没有七天拒绝／接受结论，V06 保留未通过。[记录](docs/validation/w08.md#自然过期观察)。

- 2026-10-31 23:32 PERF01 最终候选：537 项（35.494 秒）、编译／依赖、SDK 目录刷新与身份拒绝、schema 支持链／回滚、28 文件补丁与摘要检查通过。同机领取查询 409.214→0.023625 毫秒，普通／标题最大纯渲染 -31.27％／-52.99％，实际异步路径另测；100/100 CPU 重叠追问 p95 1.472 毫秒、最大 7.734 毫秒，60 秒领取 12 次。原生准确追问 resolved，两专用任务 completed 并清理，真实微信发送为 0；真实账本／配置摘要保持。[原始证据](docs/validation/performance-optimization.json)。

- 2026-10-31 17:55 本地阶段提交前核对：178 个候选版本文件／16 份 JSON、当前全部 502 个可达历史 blob 与本项目真实私密候选值比对无泄露，0 合并标记；102 份变更文本／10 份 JSON／290 个本地链接通过。源码／测试／依赖与已通过的 512 项回归摘要一致，复用该结果，不重复运行真实微信验收；编译、依赖完整性、包目录及托管模板检查通过。当前只归档 `dev` 开发阶段，W08 未完成，不合并／推送或打发布标签。
