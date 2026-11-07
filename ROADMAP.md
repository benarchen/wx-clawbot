# 当前进度

唯一项目进度源。设计文档与施工清单描述范围及要求，不作为完成声明。

## 当前阶段

TGT02 已随 0.1.8 发布并完成本机切换：38 文件功能提交 `f2de0ef`、main 快进合并、annotated v0.1.8、双分支／标签原子推送及独立远端核验通过。同一冻结独立非 editable 制品实际加载／父子来源／唯一消费者／host、native ready 通过；756 项／40.883 秒及必要检查通过。旧 managed 正常退出 0，13 表备份、587 旧回执／投递尝试、两条 unknown、原未聚焦状态及配置保持，schema 6 无迁移，路由快照 v1→v2，请求停止至验收 17.423 秒。首次接入不再依赖状态栏或标题 ID；本轮未修改全局显示。结果文档另行正常同步，不移动标签。[发布与切换](docs/validation/native-session-release.md)。

TGT02 工程 Goal 已完成：G00 至 G09、T01 至 T32 适用范围及 A01 至 A12 通过，双路径首次接入、同进程桌面切换、桥接重启、关闭仍加载及卸载拒绝有真实原生证据；D01 至 D07 齐备。工程候选当时未部署，后续已按新授权随 0.1.8 交付，状态以上条为准。[清单](goals/20261107-1453-native-session-no-footer.md)、[功能证据](docs/validation/native-session-no-footer.md)、[身份契约](docs/native-session-identity.md)。

TGT01 微信独立选择已随 0.1.7 发布部署：26 文件功能提交 `219912c`、main 快进合并、annotated v0.1.7、双分支／标签原子推送及独立远端核验通过。同一冻结非 editable 制品已本机加载，723 项／40.526 秒与必要检查、实际 argv／cwd／manifest／父子来源／唯一消费者、host／0.167.0 native ready 均通过；正常退出 0、13 表备份，原路由、587 旧回执、两条 unknown 及配置保持，请求停止至验收 7.692 秒。桌面切换不改微信目标；准确 A 续接、显式 B 与失效提示真实通过，首次发现仍依赖准确页脚。实际结果文档另行正常同步，不移动标签。[施工清单](goals/20261107-1027-wechat-independent-target.md)、[功能证据](docs/validation/wechat-independent-target.md)、[发布记录](docs/validation/wechat-independent-release.md)。

0.1.6 兼容版发布／部署已完成：15 文件功能提交 bcc3c40、main 快进合并与双分支原子推送、独立远端核验通过；随后本机已加载同一独立非 editable 制品，host／0.167.0 native ready。712 项／40.498 秒及实际加载／旧数据保护通过；旧 584 回执／两条 unknown 保持，旧失效选择清除且唯一自然恢复通知 API accepted。stopped 至首次 ready 1.748 秒，请求停止至最终验收 69.574 秒。[交付记录](docs/validation/codex-0167-release.md)。

真实冷启动复测已通过：2026-11-07 07:40，iTerm2 起初缺席，隔离候选一条 `/cd` 在 11.772 秒内创建并核验一个真实可见 Codex 会话，启动轮次 completed、队列空，自有端点已清理。本人授权的 0.167.0 核验与核心适配已完成，38 份契约及 712 项回归通过；兼容改动随后已随 0.1.6 发布部署，生产原生连接恢复 ready。[证据](docs/validation/iterm-cold-start-live.md)。

冷启动修复发布／上线已完成：功能提交 165d375、main 正常快进合并、annotated v0.1.5 与双分支／标签原子推送、独立远端核验通过；本机已加载同一冻结的独立 0.1.5／schema 6。711 项独立制品回归、实际进程／cwd／manifest、父子加载和单消费者／host、native ready 通过；576 旧回执、两条 unknown、路由和配置保持，stopped 至验收 117.064 秒。只归档实际结果，不移动标签。[发布与切换记录](docs/validation/iterm-cold-start-release.md)。

iTerm2 冷启动修复已实现并上线：显式按需连接先在准确进程下有界等待无授权 UI 的 API 传输就绪，最多 5 秒并计入原连接期限；超时／换代／取消停止，授权及创建不自动重试。后续真实冷启动已在 0.167.0 兼容候选通过，准确范围以上述新记录为准。[根因与修复](docs/validation/iterm-cold-start-investigation.md)。

AUD01 当次本机切换已完成：本人明确授权后，日常托管进程已从独立 0.1.3 切换到已发布的独立非 editable 0.1.4／schema 6，正常停服至验收 26.119 秒。准确进程／cwd／manifest、父子加载、唯一消费者和 host／native ready 通过；568 条旧回执、两条 unknown、原路由与配置保持，无迁移或额外测试消息。本次仅部署与同步文档，未再次执行 Git 写操作。[切换记录](docs/validation/aud01-local-deployment.md)、[机器摘要](docs/validation/aud01-local-deployment.json)。

AUD01 后续 Git 交付已完成：22 文件功能提交 88ba09f、main 正常快进合并、annotated v0.1.4 和 main／dev／标签原子推送通过，独立远端引用一致。该次代码与本机版本为 0.1.4／schema 6，后续已由冷启动修复升级为 0.1.5；只归档实际发布结果，不移动版本标签。[发布记录](docs/validation/aud01-publication.md)。

AUD01 已按本人明确接受的原生限制方案完成候选与契约验收：有界脱敏故障日志、702 项全量、真实断连／恢复、同一原会话九轮规则实验及十轮历史审计通过。项目规范与设计／使用文档已同步，最终审计通过，原生 Goal 已实际 complete；工程验收时未部署或执行 Git 写操作，后续 Git 交付已按新授权完成，未外发微信。[清单](goals/20261104-2338-native-diagnostics-rules.md)、[交付记录](docs/validation/native-diagnostics-rules.md)、[原生限制契约](docs/project-rules.md#已确认的原生限制契约)。

ENG01 已验收交付，原生 Goal 已实际 complete：当时本机已运行独立非 editable 0.1.3／schema 6，父子制品、唯一消费者及 host／native ready 核验通过；根工作区 680 项／43.102 秒、两轮 120 秒负载及真实原生组件关卡通过。旧冻结／unknown／配置保持，自有终端清理；测试微信零，正常恢复通知一条 API accepted。本人后续授权的 50 文件完整提交 425fda5、main 正常合并、annotated v0.1.3 及 GitHub 原子推送已完成，独立远端核验一致；仅追加实际结果文档，不移动标签。[清单](goals/20261103-2356-engineering-hardening.md)、[交付记录](docs/validation/engineering-hardening.md)、[Git 发布记录](docs/validation/eng01-publication.md)。

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
| AUD01 | 日志候选和原生限制契约已验收，原生 Goal 实际 complete；702 项及真实原生通过；v0.1.4 双分支／标签已公开同步，独立 0.1.4 本机切换及保护核验通过：[清单](goals/20261104-2338-native-diagnostics-rules.md)、[交付记录](docs/validation/native-diagnostics-rules.md) |

## 交付状态与运行说明

- W00 至 W08、IMG01、HOST01、MD01 和 PERF01 原 13 个工作包按当时确认范围交付；REC01 已验收交付并消除对应准入阻塞。新增 ASK01 修复已加载且必要真人交付通过，原有后置能力继续保留；不将旧交付扩写为所有 CLI 交互均已支持。
- 本轮之前的 0.1.1／schema 5 已发布记录保留：生产工作区为 `dev`；功能提交 `387e7ac` 已正常合并 main，两个分支和 annotated v0.1.1 公开推送、独立远端核验通过。随后仅归档实际发布结果，不移动标签或改变运行代码；未创建 GitHub Release，无需再次重启已健康加载的服务。
- 初次公开推送曾被自动审批要求具体确认；本人随后明确授权公共目的地与完整内容，正常推送及远端核验成功。该门禁已解决，不再列为当前阻塞。
- 历史 unknown 2 结果保留不重放，现已按准确原生终态解除占用，不再阻塞项目；原等待任务唯一 completed。原生 hook 告警仍按历史证据保留，本轮不修改全局 hook。[REC01 实际记录](docs/validation/admission-recovery.md)。

## 待办事项


- 0.167.0 后续验收：核心兼容已随 0.1.6 提交、main 合并、推送并部署，712 项及真实冷启动／运行保护通过。新版异步问题动态验收与图片手机整链路仍未完成，保持各自门禁与范围，不把核心通过扩写为全部功能通过。[记录](docs/validation/codex-0167-release.md)。


- 原生中断后的队列继续：0.166.0 专用验收中，一个准确已入队输入在原生 idle 状态保持 queued、零 turn；已准确取消该测试项，没有强制启动或重放。现桥接保留原生队列权威，后续应独立核对客户端暂停／显式继续语义，再决定是否增加受控恢复能力；不混入 ENG01 的性能和制品隔离范围。[阶段记录](docs/validation/engineering-hardening.md)。

- 第三方组合发行边界：iterm2 SDK 保持 GPLv2+。若后续需要承诺完整产品可闭源再发行，须先核清适用条件、取得额外授权或评估替代实现；当前未作该兼容性保证，不影响本项目自有作品采用 MIT。[第三方声明](THIRD_PARTY_NOTICES.md)。

- W08 后续观察：自然上下文失效和实际拒绝后恢复尚未触发，已获本人明确后置，不阻塞当前必要验收；183.069 小时旧值仍被 API 接受。不再预约／续发或推定固定 TTL；后续真实观察须有新授权，跨天调度先验证持久化与重启恢复。[证据](docs/validation/w08.md#2026-11-01-上下文收尾)。


- MD01 后续：Mac 完整排版与复制。本人于 2026-10-31 明确暂时后置，不阻塞本次 Android 交付；现 Mac 4.1.15.22 的复杂代码 M01／M03 仅复制 33／37、25／37 字节，M04 无代码块复制入口，三种括号链接写法均显示多余后缀。已保留原始复制／照片摘要和人工最小复现，恢复时先核对客户端／协议可行性，不沿用 API accepted 冒充通过。[完整证据](docs/validation/wechat-markdown.md)。


- IMG01 后续：同消息图文。本人于 2026-10-29 明确后置，不阻塞本次单图交付；当前客户端把一起发送的图片和文字拆为两条，只有解析覆盖，尚无单条图文真机证据。后续先确认可实际发送的客户端／协议形态，再验证一条原始消息对应一次带图文提交；不得用合成 inbox 或跨消息自动拼接冒充通过。[原 A03 要求](goals/20261028-1135-image-input.md)。

## 最近完成

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

- 2026-11-04 22:46 ENG01 0.1.3 Git 交付：50 文件功能提交 425fda5、独立工作树 main 快进合并、annotated v0.1.3 及 main／dev／标签原子推送完成，独立远端引用核对一致。注释明确变更／验证／性能取舍及能力边界；仅归档结果文档，不移动标签、不重启服务。[发布记录](docs/validation/eng01-publication.md)。

- 2026-11-04 13:36 ENG01 工程交付：R01 至 R07、独立非 editable 0.1.3／schema 6 本机切换完成；680 项、真实原生组件及最终两轮负载通过。旧数据／配置保持，自有终端清理；临时模型精确恢复，无需本人追加配合，Git 未执行。原生 Goal 已实际 complete。[交付记录](docs/validation/engineering-hardening.md)。

- 2026-11-04 00:05 ENG01 施工清单制定：将全面审查前四项收敛为 G00 至 G10、T01 至 T36、A01 至 A14，冻结停止候选、有界发现、非 editable 制品、性能测量门槛及交付文档；生产切换／必要配合置后，新增功能和 Git 发布不在本次计划授权内。仅编写清单与导航，未创建 Goal、改实现、部署或发送微信。[清单](goals/20261103-2356-engineering-hardening.md)。

- 2026-11-03 21:52 0.1.2 Git 交付：41 文件功能提交 ab8f8b9 纳入 ASK01 与自有 MIT 许可；main 独立工作树快进合并，main／dev／annotated v0.1.2 原子推送并独立远端核验通过。标签固定功能提交，随后仅归档结果文档；运行源码及本机健康保持，无重启或额外微信发送。[发布记录](docs/validation/ask01-publication.md)。

- 2026-11-03 21:31 ASK01 完整交付：结构化异步即时通知、准确原轮次答复、严格辅助输入及竞争／重启／迁移保护完成。625 项回归、120 秒负载、真实原生和 Android 手机 8 条回执闭环通过；0.1.2／schema 6 已加载，旧 530 冻结／2 unknown／配置保持、原路由恢复、测试终端归零，G00 至 G09／T01 至 T32／A01 至 A12 通过，原生 Goal 实际 complete。未提交／推送。[交付](docs/validation/async-questions.md)。

## 最近验证

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

- 2026-11-05 14:14 AUD01 最终自主核验：独立候选 702 项／39.514 秒及编译／依赖／文档通过，最终常量复用另经 12 项定向；九轮规则任务及一次启动握手均 completed／零工具，队列前后变更证据准确，真实客户端断连／重连通过。制品源一致、公开 16 文件／6 私密候选零匹配；未部署，A06 待决定。[摘要](docs/validation/native-diagnostics-rules.json)。

- 2026-11-05 08:11 AUD01 测试启动根因与回归：私有堆栈确认 GUI 残留 manifest 与开发解释器冲突，测试父子显式对齐并保留版本校验；8 项工具门禁、独立候选完整 698 项／39.410 秒及编译／依赖／差异／文档通过。宿主 API 在失败后再次不可用，等待关闭可能的警告后原生验收；不修改配置、不重复启动。[记录](docs/validation/native-diagnostics-rules.md)。

- 2026-11-05 07:52 AUD01 启动失败定位：本人截图确认测试会话快速退出警告；配置自定义命令、解释器导入及 argv 初查通过，专用启动包装增加私有错误捕获，6 项工具自测及编译／差异通过。新全量请求因自动审批服务 502 未执行，不替换此前 695 项结果；未绕过审核或修改用户配置。[记录](docs/validation/native-diagnostics-rules.md)。

- 2026-11-05 00:34 AUD01 恢复核验：本人启动 iTerm2 后脚本／API connected，原有 1 窗口／2 终端；仅新增一个已登记测试端点，180 秒握手超时退出，无 boot／binding，后续宿主传输探测不可用。未重复启动、未操作原终端，保留现场等待提示原文，不计原生验收通过。[记录](docs/validation/native-diagnostics-rules.md)。

- 2026-11-05 00:25 AUD01 阻塞审计：当前 695 项离线关卡通过，仍缺 A05／A06／A07 的真实原会话证据与路径决定；同一认证前置连续三轮未获解除证据，无自有 case／窗口或存活实验句柄。未重复请求认证，原生 Goal 实际 blocked，等待本人配合后继续，不标完成。[记录](docs/validation/native-diagnostics-rules.md)。

- 2026-11-05 00:24 AUD01 实验门禁复核：重复 run／过早 cleanup 在认证前拒绝，两个新增反例先失败后通过，工具门禁共 5 项；独立候选当前全量 695 项／40.758 秒及编译／依赖／差异／文档通过。生产源码制品不变，未重试认证、无原生任务／测试窗口，现场验收仍待配合。[记录](docs/validation/native-diagnostics-rules.md)。
