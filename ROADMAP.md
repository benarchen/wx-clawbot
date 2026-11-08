# 当前进度

唯一项目进度源。设计文档与施工清单描述范围及要求，不作为完成声明。

## 当前阶段

PRJ01 已验收，现已获授权整合为 0.1.11 并提交／合并／打 tag／推送及正式部署。冻结发布包 835 项及预装／预检通过，正进行 Git 发布，尚未切换，本机仍为下述旧 0.1.10；本轮状态见[发布记录](docs/validation/project-management-release.md)。

MVP 已按确认范围交付。最近一次已记录的日常部署为独立非 editable 0.1.10／schema 6，路由快照 version 2；dev／main 和 annotated v0.1.10 已公开同步，实际加载与旧数据保护通过。[发布／切换证据](docs/validation/help-release.md)。这是一份进度快照，不代表每次读文档均实时探测服务。

微信独立选择且首次接入无需状态栏／标题 ID：后台按注册根及已知准确 cwd 发现，准确原生身份／loaded／订阅复验；可见新建保留自有 boot 与唯一完成握手。桌面切换不改投，关闭窗口后以原生可用性为准，unknown 不重放。[当前身份契约](docs/native-session-identity.md)、[TGT02 验收](docs/validation/native-session-no-footer.md)。

DOC01 文档整理已验收交付：标准 PRD、五类实际渲染／视觉检查的架构图、现行技术与 ADR、开发／测试／安全／运维、导航及需求追溯齐备。16 个共同事实、22 项冲突／范围问题已复核关闭，113 个原文件逐项有处置。原生 Goal 已实际 complete，成果已随 0.1.9 公开交付。[施工清单](goals/20261108-0130-project-documentation-restructure.md)、[报告](docs/validation/documentation-restructure.md)。

`/sessions` 纯查询与 `/help` 核对已随 0.1.9 发布并本机加载：保留输入目标／观察／任务，不启动宿主或触发对账；退出输入目标使用 `/unfocus`。帮助覆盖 15 个命令及 6 个别名，开发阶段 765 项及最终版本 771 项检查通过。[修复与核对记录](docs/validation/sessions-query-help.md)。

冷启动零额外 Shell 修复已随 0.1.9 发布并本机加载：AppKit noop 首事件与退出即失效的启动参数，不写持久偏好；一次应用启动、一个窗口、双项目两个 Codex 标签、重复 cd 复用与自有终端清理通过，冻结制品 771 项通过。首轮失败保留，发布部署没有重复操作用户终端。[验收记录](docs/validation/iterm-single-window.md)。

`/help` 已随 0.1.10 发布并在本机加载，进一步精简为短说明：15 条命令及 6 个别名保持，每条说明最长 17 字，正文 578 字符；参数记号、列表期限和 ID 提示保留，详细边界仍见[命令契约](docs/command-contract-proposal.md)。文档收尾规范与相关版本／历史时点修正一并交付；结果见[发布记录](docs/validation/help-release.md)。

## 交付状态与运行说明

- W00 至 W08、IMG01 单图、HOST01、MD01 Android 必要范围、PERF01，以及 REC01、ASK01、ENG01、AUD01、冷启动与 TGT01／TGT02 已按各自确认范围交付；不扩写为所有客户端、原生版本和交互全部通过。
- 当前 0.1.10 的冻结制品、实际 argv／cwd／manifest、父子来源、唯一消费者及旧数据保护见[发布记录](docs/validation/help-release.md)，771 项检查通过。仅版本和 HELP 常量变化，原生 ready，iTerm2 保持退出；0.1.9 的 771 项及 0.1.8 的 756 项属于各自历史阶段，DOC01 文档整改阶段未重跑功能测试，不混为同一阶段。
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

- 2026-11-08 23:48 PRJ01 交付齐备：一层初始化、双端 project 子命令与旧入口、即时生效、取消保护／零项目；835 项、专用原生及本人 12 条手机闭环通过。正常重启取消项不复活，测试终端准确清理，原日常版本／配置恢复且新增任务／回执保持。原生 Goal 已实际 complete，未提交或正式发布。[清单](goals/20261108-2048-project-management.md)、[报告](docs/validation/project-management.md)。

- 2026-11-08 22:10 PRJ01 补齐独立进程落盘后退出／启动锁与真实 socket 回执丢失证据，修复提前断开导致关闭回调 BrokenPipe，强化回调异常判失败及资源上限验证。仅隔离测试，手机仍后置，未切换／发布；[报告](docs/validation/project-management.md)。

- 2026-11-08 21:49 PRJ01 T05 后续补修：合成目录复现禁止范围大小写变体漏排除，改为统一路径判定并在扫描元数据前复用；专项 54 项通过，新冻结候选替代此前候选，原生协议／任务模块不变。手机仍由本人后置，未切换／提交／部署；[报告](docs/validation/project-management.md)。

- 2026-11-08 21:40 PRJ01 工程交付收尾：双端管理、注册一致性／保护、兼容／零项目及专用原生主流程已形成冻结候选，相关专题、架构图、安全／运维与新旧模板完成核对。本人后置手机验收，Goal 不标完成，未提交／部署；[报告](docs/validation/project-management.md)。

- 2026-11-08 21:31 PRJ01 工程候选及专用原生主流程形成：配置／双端子命令／私有 IPC／快照撤销与取消保护实现，A／B 原对话分别 completed、一个测试窗口／两个终端已准确清理；G07 手机与真实忙碌验收待完成，不宣称 Goal 完成或已部署。[记录](docs/validation/project-management.md)。

- 2026-11-08 20:52 PRJ01 施工清单已保存：C01 至 C06／E01 至 E10／G00 至 G09／T01 至 T34／A01 至 A15／D01 至 D08 覆盖初始化、双端管理、一致性与并发保护、回归／真实验收和交付文档。仅计划交付，工程未开工；[施工清单](goals/20261108-2048-project-management.md)。

- 2026-11-08 17:19 0.1.10 已公开发布并本机加载：功能提交 03b9259、main 快进、固定 annotated v0.1.10 及双分支／标签原子推送与独立核验完成；正常切换及旧数据保护通过。帮助每条最长 17 字，收尾规范和相关文档同步；[记录](docs/validation/help-release.md)。

- 2026-11-08 17:16 0.1.10 发布准备：帮助精简和文档收尾规范完成；冻结独立制品及同一 wheel 预装、空闲与来源检查通过。尚未提交／推送／切换，本机仍为 0.1.9；[记录](docs/validation/help-release.md)。

- 2026-11-08 17:03 help 短说明：按本人要求将正文从 1475 字符缩至 578 字符，15 条命令说明最长 17 字，保留全部参数及 6 个别名；分组使用简短加粗标题，保留共用输入提示，详细行为文档不删减。命令契约和测试指南同步，未提交、部署或操作微信。

- 2026-11-08 15:47 文档收尾规则与遗留表述修正：AGENTS 明确每次功能优化、修复或迭代必须同步受影响文档并跨文档核对，交付说明范围、结果和未覆盖项；当前运行说明改指 0.1.9／771 项，发布记录明确标签未创建及旧实例状态属于发布前核对时点。仅文档修改，未提交、推送或部署。

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

## 最近验证

- 2026-11-09 07:45 0.1.11 发布准备：同一冻结 wheel 835 项／46.367 秒及必需检查通过，较已验 PRJ01 仅版本元数据差异；预装、当前 0.167.0 协议／空闲／父子来源与公开审计通过。日常仍旧 0.1.10，尚未 Git 发布或切换。[记录](docs/validation/project-management-release.md)。

- 2026-11-08 23:48 PRJ01 手机终验：选中及 unfocus 后运行任务均阻止 remove，completed 后成功，check／list 与正常重启后手机查询一致；准确原生仅一次 sleep，清理后其他终端保持，旧配置／制品恢复及新账本保留通过。[报告](docs/validation/project-management.md)。

- 2026-11-08 23:36 PRJ01 最新冻结候选 835 项／46.362 秒及必需检查通过；初始化入口两条回归先失败后通过。正常临时切换、13 表备份／旧回执／unknown／原目标保护和真实 IPC 专用初始化通过；手机实收及真实忙碌待验收，无 Git 发布。[报告](docs/validation/project-management.md)。

- 2026-11-08 22:14 PRJ01 收尾审计：833 项完整检查与工程证据齐备，同一手机／真实忙碌验收依赖连续三个 Goal 回合仍缺，原生 Goal 已实际标记 blocked；G07／G09、T34、A13／A15 未完成。没有运行中的手机切换，日常配置和版本保持；[报告](docs/validation/project-management.md)。

- 2026-11-08 22:10 PRJ01 同一最新冻结包 833 项／46.252 秒及编译／依赖／文档／diff 通过；真实子进程退出 73 后恢复不复活旧选择，启动竞争不回退直写，成功回执丢失不二次写入，未处理项目回调异常为零。相较原生已验候选另有关闭处理变化，原生模块不变；[摘要](docs/validation/project-management.json)。

- 2026-11-08 21:49 PRJ01 最新冻结候选 825 项／46.030 秒、编译／依赖／文档／diff 通过；T05 元数据探针先失败后通过。相较真实原生已验候选，仅两个禁止路径判定及未使用导入差异，其他 57 包文件一致；未新增真实原生动作。[摘要](docs/validation/project-management.json)。

- 2026-11-08 21:40 PRJ01 最终独立候选 824 项／46.074 秒、编译／依赖／文档／diff 通过；仅一个未使用导入与原生验收候选不同，AST 及其他 58 个包文件一致。两图实际渲染／视觉及跨文档核对通过，日常实际版本仍为旧 0.1.10；手机／真实忙碌验收待本人继续。[摘要](docs/validation/project-management.json)。

- 2026-11-08 21:31 PRJ01 同一冻结候选 819 项／46.105 秒与 51 项补充边界通过；原生 0.167.0 即时 add／发现／保留 A、双原会话派发、选中 B 阻止 remove／unfocus 后成功及清理复验通过。F02／F03 SVG／PNG 渲染和视觉核对通过，公开内容审计零匹配；零微信发送／生产写入，手机未验。[摘要](docs/validation/project-management.json)。

- 2026-11-08 20:52 PRJ01 清单核对：对照 0.1.10 的配置／CLI／路由／目录发现／生命周期入口，编号连续、目标与失败路径／验收／交付齐备；JSON／本地链接／锚点／版本／记录上限及 diff 检查通过。仅文档验证，未重跑功能测试、连接原生或微信；[施工清单](goals/20261108-2048-project-management.md)。

- 2026-11-08 17:19 0.1.10 实际部署：正常退出 0，13 表备份完整性／外键及实际 argv／cwd／父子 manifest、唯一消费者通过；639 条旧回执、2 条 unknown 和原选择保持，停服至验收 13.707 秒。原生 ready、iTerm2 保持退出，无迁移／数据恢复／重放或额外测试消息；[摘要](docs/validation/help-release.json)。

- 2026-11-08 17:16 0.1.10 冻结制品 771 项／40.379 秒、编译／依赖／文档／diff 通过；帮助 15 命令／6 别名、每条最长 17 字及单段渲染通过。首轮 socket 沙箱限制保留，同一制品正常权限重跑通过；包差异仅版本和 HELP，公开审计零匹配。原生 ready，iTerm2 退出状态保留；[摘要](docs/validation/help-release.json)。

- 2026-11-08 17:03 help 精简：8 项命令／别名解析覆盖、逐条说明长度及实际渲染检查通过，15 条说明均不超过 20 字，输出单段且无“【二级标题】”标记；完整 771 项／40.330 秒、编译／依赖／文档／diff 通过。核对命令契约、测试指南及现行／历史验收记录的适用阶段；无手机实收或部署验收。

- 2026-11-08 15:47 文档修正：对照 README、当前进度及 0.1.9 发布记录复核版本、测试阶段和发布前／后时点，AGENTS 收尾要求与既有文档权威及历史保留规则一致；documents 的 JSON／链接／锚点／版本／记录上限检查和 git diff --check 通过。未改源码、图或运行配置，未重跑功能测试。

- 2026-11-08 14:07 0.1.9：冻结制品 771 项／40.413 秒、编译／依赖／文档／diff 通过，56 个非版本包文件与真实验收候选相同；85 份 Markdown、1003 个本地链接／锚点通过。13 表一致性备份及外键／完整性、实际 argv／cwd／父子 manifest、唯一消费者、原生准确路由与旧行保护通过。新增提交／tag、公开文件与两份制品私密值审计零匹配，最终归档继续复核。[摘要](docs/validation/maintenance-release.json)。

- 2026-11-08 13:50 第二冻结候选真实冷启动：四条合成 cd、两个唯一 completed 握手，launch／wait_ready／connect 各一次、终端创建两次；核验阶段 26.344 秒。两个自有终端清理并复验缺席，收尾零窗口／终端，受保护配置及持久启动偏好保持。冻结包 771 项／40.319 秒及编译／依赖／文档／diff 通过，源码一致；无真实微信或生产账本直接写入。[摘要](docs/validation/iterm-single-window.json)。

- 2026-11-08 13:06 冷启动窗口候选：两个新断言在旧 lifecycle 实现均预期失败；34 项宿主、771 项／40.418 秒及编译／依赖／文档／diff 通过。iTerm2 3.7.7 启动脚本实际编译，已运行应用 launch 后 PID、两个窗口／标签／终端和受保护配置保持。双项目显式入口 help／编译通过，真实冷启动未执行。[记录](docs/validation/iterm-single-window.md)。

- 2026-11-08 12:46 sessions：3 个新回归在旧实现均复现预期失败；最终 765 项／40.097 秒、编译／依赖／文档／diff 通过。focused／managed、各订阅、空结果／失败／换代／并发、无宿主查询及卸载不改投覆盖；help 渲染单段 1499 字符。初次 17 项 Unix socket 沙箱拒绝后正常权限重跑通过；没有真实原生／手机／部署验收。[记录](docs/validation/sessions-query-help.md)。

- 2026-11-08 02:16 DOC01：16 条 CLI／构建 help、五图实际解析／SVG／PNG 渲染与视觉检查、源码事实／13 表／原章节去向、三类读者纸面走查、现有 documents、扩展链接／锚点／JSON／历史正文／示例语法／公开内容模式及 diff 检查通过。未重跑旧 756 项或真实原生／微信／部署验收，专项未测边界保持。[机器摘要](docs/validation/documentation-restructure.json)。

- 2026-11-08 01:36 DOC01 清单核对：G00 至 G10／T01 至 T26／A01 至 A14／D01 至 D08／B01 至 B12／F01 至 F05 编号连续，目标、边界、PRD／图形专项、历史保全及跨文档验收齐备。四份一手结构资料已打开核对；文档 JSON／链接／锚点、记录数量及差异格式通过，仅校验清单，没有执行整改、自测矩阵或运行时操作。[清单](goals/20261108-0130-project-documentation-restructure.md)。

- 2026-11-07 17:37 0.1.8 冻结独立制品 756 项／40.883 秒及编译／依赖／文档通过，56 个非版本包文件与无 ID 原生验收候选相同。实际 argv／cwd／manifest／父子来源／单消费者、schema 6、13 表备份及旧数据核验通过；路由快照 v1→v2，未重定向或通知。公开文件／两份制品／完整可达历史隐私审计零匹配，配置／凭据／全局设置与原生进程保持。[摘要](docs/validation/native-session-release.json)。
