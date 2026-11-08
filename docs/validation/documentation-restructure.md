# DOC01 文档整理与交叉验收记录

适用基线：应用 0.1.8／schema 6／路由快照 version 2，开工 HEAD `8278de5645a57f2fc0348b746d59899bfe0bdadd`、dev。本人明确开工后，仅整理授权文档；正文、五类图、跨文档复核与交付物已完成，必要检查通过。原生 Goal 于 2026-11-08 02:16 实际 complete，关闭记录见施工清单。

施工入口：[DOC01](../../goals/20261108-0130-project-documentation-restructure.md)，现行导航见[文档入口](../README.md)。本页是带时点的审计证据，不成为第二份产品／协议／进度权威。[机器摘要](documentation-restructure.json)与本文同步，原始盘点、对比、渲染和检查仅在被忽略的项目临时目录。

## 盘点与保存策略

开工盘点根 README／AGENTS／ROADMAP／LICENSE／THIRD_PARTY_NOTICES 及 docs／goals 的全部正式文件，共 113 个，其中当前施工清单原为未跟踪文件，ROADMAP 原有规划差异保留。未改业务源码、测试、构建脚本、配置模板、依赖或许可证。

被重写的当前设计稿保留原文件路径；被引用锚点保留兼容标题。旧设计／一次性授权／测量不丢弃，以本地 Git 基线及下面固定公开提交追溯，逐原章节去向随机器摘要交付；历史 Goal 和原验证正文不改写；bridge-supervision 只增加阶段范围提示，原正文逐字保持。

| 整理前文档 | 主要去向／处置 | 完整原文 |
| --- | --- | --- |
| README | 当前最小使用路线；细节归命令、运维、兼容和测试专题 | [固定基线](https://github.com/benarchen/wx-clawbot/blob/8278de5645a57f2fc0348b746d59899bfe0bdadd/README.md) |
| 产品设计 | 当前标准 PRD；用户故事、范围、指标与 P01 至 P14；旧施工过程归对应历史证据 | [固定基线](https://github.com/benarchen/wx-clawbot/blob/8278de5645a57f2fc0348b746d59899bfe0bdadd/docs/product-design.md) |
| 架构设计 | 当前系统／部署／模块／运行视图，旧实施顺序归原 Goal | [固定基线](https://github.com/benarchen/wx-clawbot/blob/8278de5645a57f2fc0348b746d59899bfe0bdadd/docs/architecture-design.md) |
| 开发契约 | 真实对象接口与状态、V00 至 V08；旧 MD01 候选时点转历史证据入口 | [固定基线](https://github.com/benarchen/wx-clawbot/blob/8278de5645a57f2fc0348b746d59899bfe0bdadd/docs/development-contracts.md) |
| 技术决策 | ADR-01 至 ADR-09；旧 T01 至 T10 映射保留，原静态快照不冒充当前环境 | [固定基线](https://github.com/benarchen/wx-clawbot/blob/8278de5645a57f2fc0348b746d59899bfe0bdadd/docs/technical-decisions.md) |
| 运维 | 当前准备／启停／备份／发布／恢复路线；旧操作卡保留标题与历史证据 | [固定基线](https://github.com/benarchen/wx-clawbot/blob/8278de5645a57f2fc0348b746d59899bfe0bdadd/docs/operations.md) |
| 协议基线 | 逐版本逐能力与证据层级矩阵；历史采样及固定 fixture／JSON 继续可查 | [固定基线](https://github.com/benarchen/wx-clawbot/blob/8278de5645a57f2fc0348b746d59899bfe0bdadd/docs/protocol-baseline.md) |
| 其他专题 | 局部修正过时身份、版本和证据范围，未改历史试验结论；账本补 13 表总览 | 基线提交中各原路径；逐文件摘要和处置见机器摘要 |
| 旧 Goal／validation／reference | 保留原文／日期／失败；native-session-evidence 仅加历史提示，不再作为当前接入要求 | 各文件原路径 |

原文固定提交属于已存在历史，不需要依赖本任务临时目录或重新推送才能找回；本轮没有 Git 写操作。

## 结构参考

已实际打开 [Atlassian PRD](https://www.atlassian.com/agile/product-management/requirements)、[arc42](https://arc42.org/overview/)、[C4](https://c4model.com/diagrams)、[ADR](https://adr.github.io/) 一手页面。仅借鉴组织原则并按单用户产品裁剪，没有复制整份模板或宣称认证。

PRD 覆盖文档信息、问题／价值、用户环境、目标指标、MVP／非目标、概念、旅程、稳定需求、质量、约束、验收和未决边界。架构按不同读者视角分五图；决策保留来源和替代关系，不补造历史审批。

## 事实与冲突台账

同一当前行为按需求、源码、测试和适用证据三轮核对：逐批核对权威事实；正文形成后按主题检查所有消费者；修改后复查正文、图、例子、范围及引用。机器摘要保存完整字段、原文片段／基线行、处理与复核，下面是便于阅读的摘要。

| 事实 ID | 核对主题 | 权威维护页 |
| --- | --- | --- |
| K01 | 版本与数据格式 | `docs/state-schema.md` |
| K02 | 会话与原生身份 | `docs/native-session-identity.md` |
| K03 | 微信独立选择 | `docs/command-contract-proposal.md` |
| K04 | 输入与观察 | `docs/command-contract-proposal.md` |
| K05 | 列表／发现范围 | `docs/native-session-identity.md` |
| K06 | 可见创建 | `docs/development-contracts.md` |
| K07 | 排队／取消 | `docs/desktop-queue-contract.md` |
| K08 | 结果／占用／投递 | `docs/state-schema.md` |
| K09 | 同步与异步 | `docs/async-questions.md` |
| K10 | 版本与能力 | `docs/protocol-baseline.md` |
| K11 | 图片与客户端 | `docs/image-input.md` |
| K12 | 原生规则和全局设置 | `docs/project-rules.md` |
| K13 | 实际接口与账本 | `docs/development-contracts.md` |
| K14 | 部署／进程／备份 | `docs/operations.md` |
| K15 | 许可与安全范围 | `SECURITY.md` |
| K16 | 文档权威与历史 | `docs/README.md` |

| 冲突 ID | 问题／范围 | 处理与复核 |
| --- | --- | --- |
| C01 | 旧当前版本与包元数据不一致 | 改为 0.1.8，schema／快照分别解释；已关闭 |
| C02 | 旧恢复决策强制页脚与 TGT02 冲突 | ADR-02 明确替代旧映射，保留历史来源；已关闭 |
| C03 | 图片使用前提误要求显示 ID | 改为准确原生身份／加载／订阅，失败说明同改；已关闭 |
| C04 | 异步新输入仍要求宿主／可见身份 | 按原生身份、代次和准确 turn，宿主来源可选；已关闭 |
| C05 | 规则责任混入已取消显示门禁 | 保留原生限制、纠正身份前置；已关闭 |
| C06 | 代码准入与旧指南版本范围不一致 | 矩阵分代码／schema／原生／手机，保留 0.167 专项未测；已关闭 |
| C07 | 解析能力被写成产品手机交付 | 分清解析与已交付单图，保留同消息图文后置；已关闭 |
| C08 | 旧单次授权成为常驻执行规范 | 改为历史指针与不自动修改的稳定边界；已关闭 |
| C09 | 旧终端中心叙事误约束准确原生选择 | 当前五视图分离原生对象与可选宿主，旧稿固定提交保存；已关闭 |
| C10 | P02／旧规则文字可能导出逐轮加载保证 | P02 明确原生限制，规则变化需本人新建复验；已关闭 |
| C11 | 概念接口可能被当作现有 API | 列真实类／方法／能力，具体 Codex 队列独立类；已关闭 |
| C12 | 建议表与实际结构混杂 | 当前 13 表、逻辑关联与实际外键分明，配置／目录不造表；已关闭 |
| C13 | 已实现容量／保留期还称实施前待确认 | 数值以当前账本和身份专题维护，PRD 仅区分限制／样本／目标；已关闭 |
| C14 | 建议状态名与真实状态名不一致 | 明确 prepared／received／dispatching／stopping／unknown 及三类独立状态；已关闭 |
| C15 | 旧单次观察／候选 MD01 状态混入长期当前契约 | 保留日期证据与固定原稿，当前手册明确旧额度不继承；已关闭 |
| C16 | 当前阶段堆叠多次已流转发布叙事 | 收敛当前快照和历史索引，不删除版本证据；已关闭 |
| C17 | 旧客户端阶段数量／生产就绪被误读为实时状态 | 明确 MD01 当时样本与当前版本／部署源分离；已关闭 |
| C18 | 整改初稿错误画成 managed／serve 两常驻进程 | 按源码改为同进程入口，重渲染 F02 并视觉核验；已关闭 |
| C19 | 整改初稿订阅与持久化时序粒度不准确 | F04 先 received／准入再订阅复验，F05 创建与回执顺序校正，重渲染；已关闭 |
| C20 | 整改初稿将 sessions 清目标范围写窄 | 源代码核对后统一说明 managed／focused 都清输入目标，观察保留；已关闭 |
| C21 | HOST01 长期命令段残留强制终端核验 | 当前既有对象只需原生完整身份，旧宿主证据保留历史范围；已关闭 |
| C22 | 旧验证补充未限定当前时点，可能被误作最新部署 | 只加阶段范围提示及当前进度／运维入口，原正文逐字保持；已关闭 |

共 22 项关闭，其中 19 项来自原文档／历史范围，3 项来自本轮初稿自查（C18 至 C20），不把自行引入又修正的问题算作原项目缺陷。现行产品行为、安全、身份、数据与兼容高影响未关闭冲突为零；历史不同版本不强行统一，原反例和失败保留。

## 产品边界核验

| 边界 | 关联事实 | 结果 |
| --- | --- | --- |
| B01 | K03／K15 | 保持：本人、本机、Codex 与非目标保持 |
| B02 | K02／K03／K05 | 保持：原生会话不等于窗口，独立选择与准确发现 |
| B03 | K06 | 保持：可见来源及唯一握手，未知不替代 |
| B04 | K04／K07 | 保持：输入、观察和冻结队列分开 |
| B05 | K08 | 保持：结果／占用／投递分离，未知不重放 |
| B06 | K09 | 保持：同步／异步语义分开 |
| B07 | K10 | 保持：逐能力门禁与实测层级保持 |
| B08 | K11 | 保持：单图输入／文本输出，其他形态后置 |
| B09 | K12／K15 | 保持：原生规则限制和非沙箱说明 |
| B10 | K12 | 保持：旧单次全局配置授权非持续许可 |
| B11 | K01／K14 | 保持：版本对象、冻结制品和本机运行分开 |
| B12 | K10／K11／K15 | 保持：后置、未测、SLA 与许可边界保持 |

## 图形解析、渲染与视觉检查

五图均以当前架构 Mermaid 为唯一维护源，逐幅生成 SVG／PNG，修正后重新渲染并实际打开最终 PNG 查看中文、分组、箭头、失败分支和完整边缘，无截断或遮挡。渲染只使用独立无界面 Chrome 临时实例，未连接用户浏览器会话或外部网页。SVG 不嵌入系统字体、不含脚本或私人本地引用；源摘要与 SVG 头部记录一致。

工具版本：Mermaid CLI 12.2.0、Chrome 156.0.8078.80、Node v26.0.0、Python 3.14.5。隔离工具只在任务临时目录，未新增运行依赖或全局工具。

| 图 | 视图 | 交付与结果 |
| --- | --- | --- |
| F01 | 系统上下文 | [SVG](../diagrams/architecture-F01.svg)，解析／实际渲染／视觉通过 |
| F02 | 进程与部署 | [SVG](../diagrams/architecture-F02.svg)，解析／实际渲染／视觉通过 |
| F03 | 模块协作 | [SVG](../diagrams/architecture-F03.svg)，解析／实际渲染／视觉通过 |
| F04 | 既有任务执行／投递时序 | [SVG](../diagrams/architecture-F04.svg)，解析／实际渲染／视觉通过 |
| F05 | 可见新建握手时序 | [SVG](../diagrams/architecture-F05.svg)，解析／实际渲染／视觉通过 |

图形源／SVG／私有 PNG 摘要在机器摘要，可核对当前渲染对象。派生 SVG 便于放大查看，不另行维护；外部 Markdown 渲染器像素可能不同，不据此承诺所有渲染器外观完全一致。

## 自测、读者走查与验收

| 自测 | 实际结果 | 证据入口 |
| --- | --- | --- |
| T01 | 通过：完整盘点 113 个原文件，逐文件处置／原章节去向保存在 inventory；十类文档及新增入口有唯一职责。 | inventory；docs/README.md |
| T02 | 通过：PRD 十二类内容覆盖，合并于十节及文档信息／扩展契约；无空占位、假角色、审批或市场数据。 | docs/product-design.md |
| T03 | 通过：P01 至 P14 稳定编号、七条旅程及失败反馈、模块／现有测试／版本化证据逐项映射。 | docs/requirements-traceability.md |
| T04 | 通过：五类成功指标含口径／证据／限制，基准目标、当前容量与历史样本分明，无新遥测或 SLA。 | PRD 第 9 节；K01／K10 |
| T05 | 通过：B01 至 B12 全部核对，单用户本机／准确对话／媒体／非目标／未知保护保持。 | boundaries；fact_ledger |
| T06 | 通过：五幅 Mermaid 实际解析渲染 SVG／PNG，逐图打开查看；改图后重渲染复查，无裁切／遮挡。 | diagrams；render_tool |
| T07 | 通过：五视图按 managed／service／catalog／execution／visible 等源码核对，进程／模块／外部依赖清楚。 | K02／K06／K13／K14；C18／C19 |
| T08 | 通过：页脚／标题不参与原生路由，窗口退出不自动卸载或改投，不恢复 notLoaded。 | K02／K03；C02 至 C05／C21 |
| T09 | 通过：命令总表、sessions 清 managed／focused、send 单次、focus 与 observer、冻结目标一致。 | K03 至 K05；C20 |
| T10 | 通过：原生队列权威，TUI 专用入口、取消确认、暂停与子进程限制、unknown／占用分离一致。 | K07／K08 |
| T11 | 通过：同步回答数组与 q 键字符串、期限、裁决／补充及版本门禁分别核对。 | K09／K10 |
| T12 | 通过：兼容矩阵分代码／schema／真实原生／手机，同消息图文、Mac、图片输出边界明确。 | K10／K11；C06／C07／C17 |
| T13 | 通过：应用 0.1.8、schema 6、快照 2 对照源码；历史数量／版本有作用域。 | K01；C01／C16／C22 |
| T14 | 通过：实际 Protocol／类／方法与 13 表核对；逻辑关联不误报外键，旧建议状态改为实现枚举。 | K13；C11／C12／C14 |
| T15 | 通过：ADR-01 至 ADR-09 有记录日期／来源／状态／备选／理由／后果／重评及替代关系。 | docs/technical-decisions.md |
| T16 | 通过：开发接手纸面走查及真实入口核对通过，环境、锁、目录、合成数据和检查路线完整。 | reader_tasks R02；help_verification |
| T17 | 通过：默认离线、合成负载、真实原生、手机和部署验收分层；未重跑旧 756 项。 | docs/testing.md；limitations |
| T18 | 通过：运维纸面走查，16 条 help／源码／plist 核对，备份示例只语法检查；无真实部署或恢复。 | reader_tasks R03；help_verification |
| T19 | 通过：旧一次性授权改历史，路径非沙箱、安全存储不冒充加密，真实报告渠道与隐私扫描核对。 | K12／K15；SECURITY.md |
| T20 | 通过：原 113 路径、41 个被引用片段保留；旧历史正文保留，唯一 scope banner 比较原文通过。 | inventory；original_history_body_preserved；original_referenced_anchors_preserved |
| T21 | 通过：现有 documents 与新增根文档链接／JSON／SVG XML 检查通过。 | mechanical_checks |
| T22 | 通过：16 事实逐主题三轮核对，22 个冲突全部有依据／修改／复查，现行高影响未关闭为零。 | fact_ledger；conflict_ledger；review_rounds |
| T23 | 通过：使用者／开发者／维护者三条任务链实际阅读走查，均可从当前入口找到操作与失败处理。 | reader_tasks R01 至 R03 |
| T24 | 通过：ROADMAP 收敛当前快照，旧发布指向历史；两近期节数量、倒序和实际北京时间核对。 | ROADMAP.md；mechanical_checks |
| T25 | 通过：diff、冲突标记、中文格式／私人路径／凭据模式和变更范围通过，仅文档及 SVG。 | mechanical_checks；scope |
| T26 | 通过：D01 至 D08、Markdown／JSON／图摘要／台账范围一致；最后记录写入后复查受影响内容。 | deliverables；mechanical_checks；final_review |

| 读者任务 | 实际走查与范围 | 结论 |
| --- | --- | --- |
| R01 使用者 | 找到配置、本人绑定、前台或托管选择、首次既有／新建任务与失败处理；实际沿入口阅读并对照模板、CLI help 和路由源码；未执行安装、登录或发任务 | 通过；连续步骤齐备，说明 sessions 清目标、cd 可能创建、ID 无需显示和 unknown 不重发 |
| R02 开发者 | 准备隔离环境、找模块／合成样本、选择安全离线检查与提交前文档维护；实际检查目录／测试入口、16 条 help、示例语法、数据和权限边界；未重新安装项目环境或跑全量功能测试 | 通过；无需私人路径／生产状态即可接手；真实原生与手机验收显式分离 |
| R03 维护者 | 找到停止、备份、冻结发布、回退与 unknown 占用／投递处置；实际沿手册核对 CLI／build_release help、managed／release／schema 及 plist 模板；Python 备份例只语法解析，不操作真实库／服务 | 通过；正常 stop 与启动一次、修改 argv 需重载 job、代码回退与数据恢复分明，无 force 清锁 |

| 验收 | 实际结论 | 依据 |
| --- | --- | --- |
| A01 | 通过：十类职责与真实入口完整 | T01／T16 至 T18 |
| A02 | 通过：标准 PRD 裁剪与指标真实性 | T02／T04 |
| A03 | 通过：需求全链追溯 | T03 |
| A04 | 通过：五类实际渲染与图文实现一致 | T06／T07 |
| A05 | 通过：现行技术设计与 ADR | T14／T15 |
| A06 | 通过：开发／测试／安全／运维任务走查 | T16 至 T18／T23 |
| A07 | 通过：B01 至 B12 无扩大 | T05／T19 |
| A08 | 通过：当前重大冲突全部关闭 | T08 至 T14／T22 |
| A09 | 通过：版本和证据层级明确 | T12／T13／T17 |
| A10 | 通过：历史／编号／路径／被引用锚点保全 | T20 |
| A11 | 通过：机械与公开内容检查 | T21／T25 |
| A12 | 通过：唯一职责、维护触发与当前进度 | T01／T24 |
| A13 | 通过：D01 至 D08 实际交付及限制 | T26 |
| A14 | 通过：业务与运行零变更，无发布，必要验收满足 | scope／final_review |

命令核对实际执行了 16 条 `--help`，全部退出 0；另逐字段查看 CLI、构建脚本和 launchd 模板。Shell 示例经 zsh 语法检查，Python 备份示例只解析语法，没有操作数据库。读者验收是纸面走查加真实入口核对，不是重新安装、登录或运行生产流程。

## 检查与公开内容

现有 documents 检查、扩展到全部 Markdown（含 SECURITY）的本地链接／锚点、JSON、原路径和被引用锚点、原历史正文、源码改动范围、示例语法、隐私模式、冲突标记、中文破折号和 ROADMAP 记录数量均通过。检查计数随最终记录中的链接增加而更新，以机器摘要为准；机械检查不能替代上文语义复核。

首次中间检查发现交付文件尚未生成的链接，以及检查器把代码中的 `[...] (...)` 邻接误认成链接；文件完成后补齐，对等函数调用改用 `.get` 避免误识别，未修改检查器。初次渲染受沙箱限制，随后对准确的本地无界面渲染申请具体权限；未降低图形验收要求。

公开内容检查覆盖本轮变更文本／JSON／SVG 的私人绝对路径、凭据／私钥形态、真实 native UUID、冲突标记及人工差异；没有将原始私有材料纳入交付。它不是全历史泄露排查或完整安全审计。旧历史正文仅 bridge-supervision 新增范围提示，去掉提示后与基线逐字相同；其他旧 Goal／validation／reference 原内容保持。

## 交付与限制

| 交付 | 内容 | 路径 |
| --- | --- | --- |
| D01 | 已交付：施工定义与逐项实际验收 | `goals/20261108-0130-project-documentation-restructure.md` |
| D02 | 已交付：当前入口、规范、进度及维护 | `README.md`、`AGENTS.md`、`ROADMAP.md`、`docs/README.md` |
| D03 | 已交付：标准 PRD | `docs/product-design.md` |
| D04 | 已交付：五类图及代码职责 | `docs/architecture-design.md`、`docs/diagrams/architecture-F01.svg`、`docs/diagrams/architecture-F02.svg`、`docs/diagrams/architecture-F03.svg`、`docs/diagrams/architecture-F04.svg`、`docs/diagrams/architecture-F05.svg` |
| D05 | 已交付：现行专题、接口、数据、决策与范围 | `docs/development-contracts.md`、`docs/technical-decisions.md`、`docs/protocol-baseline.md`、`docs/state-schema.md`、`docs/command-contract-proposal.md`、`docs/async-questions.md`、`docs/image-input.md`、`docs/project-rules.md`、`docs/wechat-protocol.md`、`docs/wechat-markdown.md` |
| D06 | 已交付：接手、验证、安全与稳定运维 | `docs/development.md`、`docs/testing.md`、`SECURITY.md`、`docs/operations.md` |
| D07 | 已交付：需求证据链与兼容矩阵 | `docs/requirements-traceability.md`、`docs/protocol-baseline.md` |
| D08 | 已交付：盘点／章节去向／台账／图／检查／读者走查及限制 | `docs/validation/documentation-restructure.md`、`docs/validation/documentation-restructure.json` |

- 本轮只修改文档及派生 SVG，未重新执行 756 项功能回归、真实原生／微信或部署验收；历史结果保留原范围。
- 未重新安装或运行实际服务、未实际演练生产备份／恢复；命令核对为 help／源码／模板及示例语法和读者纸面走查。
- 图已在本机独立无界面 Chrome 实际渲染及逐图查看；未声称所有外部 Markdown 渲染器像素相同，提供 SVG 备查。
- 0.167.0 图片手机整链路和结构化异步专项未验收，异步门禁未变；同消息图文、Mac 完整排版、自然上下文失效时点、暂停队列恢复仍保留原边界。
- 公开内容检查为本轮文档／SVG 的确定性模式与差异人工审阅，不声称完整安全审计；既有第三方许可与支持政策不变。

本轮无需本人补充配合。未提交、合并、tag、推送或部署，未更改 Codex 设置、微信、原生任务或运行库；成果保留在当前工作区。Goal 的逐项记录与实际关闭见施工清单，当前进度只见 ROADMAP。

最终关闭：2026-11-08 02:16，原生 Goal 实际 complete；必要检查通过后仅记录交付状态，并复查受影响文档。
