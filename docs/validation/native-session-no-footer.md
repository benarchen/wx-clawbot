# TGT02：无状态栏 ID 的原生会话接入验证

状态：G00 至 G09、T01 至 T32 适用范围及 A01 至 A12 已验收通过，候选交付完成。源码候选暂沿用 0.1.7／schema 6，尚未发布或部署；日常仍运行原独立 0.1.7，首次发现仍需 ID。范围见[施工清单](../../goals/20261107-1453-native-session-no-footer.md)，行为见[身份契约](../native-session-identity.md)，[机器摘要](native-session-no-footer.json)仅保存可公开结果。

## 协议基线

2026-11-07，本机 daemon 0.167.0；匹配 binary SHA-256 为 `030316ecfbb41f4e7946e584b0063ef333b7a36cd312ba349f2f6869e39b62cc`，用该可执行文件生成 470 个 schema。没有扩大版本白名单，没有借用其他版本的接口声明。

| 接口／对象 | 已核对字段与使用边界 |
| --- | --- |
| thread/list | cwd 为精确路径过滤；cursor、limit、useStateDbOnly 已有使用依据；不能用根目录查询冒充递归覆盖，不调用无 cwd 的全量私人历史列表 |
| thread/read | 必需 threadId，includeTurns=false 用于元数据核验；返回 ID 必须准确匹配 |
| thread/loaded/list | 分页返回已加载 ID，只用于可用性核验，不证明当前哪个窗口显示它 |
| Thread | id、sessionId、cwd、status 等为原生身份／可用性字段；fork 共享 session 根不能合并完整 thread |
| thread/resume | 作为现有订阅入口时须先证明已加载并复核返回身份，不用于恢复存档对象制造可用性 |
| thread/queue/add | 必需 threadId、clientUserMessageId、input，接收回执与原生执行终态分别核验 |

注册本项目根的只读列表首页面返回 34 条、无后续页；没有读取未注册项目历史或产生模型任务。已有精确根信任项，不保存新全局 trust。可行性试验优先保持全局配置，通过单进程隐藏设置验证；若本地 daemon 复用受到配置参数影响，使用明确同一既有端点并记录原生代次，不能无证据假定仍在同一运行时。

## 实现与真实结果

G01 先行修改 AGENTS／产品／架构／命令契约；开发契约已同步新含义。既有对话直接按注册 cwd、完整 loaded 集合与准确原生身份发现，endpoint 为可选真实来源；新建保留 boot PID／启动时间／TTY／可执行文件、准确项目和单次 nonce 的唯一 completed 握手。没有修改 Codex CLI、标题 ID、Hooks、全局设置或版本白名单。

2026-11-07，0.167.0 真实流程使用已受信任的本项目根，未新增临时项目 trust；这不代表两个不同项目的新版真实验收。原 TUI 从进程启动前用单次配置隐藏 Thread ID／Session ID，标题也无准确 ID；`--remote` 显式连接原 daemon。两个真实 TUI 的 source 实测为 vscode，因此没有把 sourceKinds=cli 误当作 TUI 资格筛选。

1. 独立最小试验：既有 A 与新建探针 B 均从无 ID 状态首次按后台原生对象接入，原上下文标记在不提供原值的追问中准确返回。两个业务输入各自唯一 client／turn、completed、零工具。
2. 完整候选：保留 A、清理探针 B，在同一自有窗口创建候选 B；使用真实 Catalog／Controller／Execution／事件流及隔离 SQLite、合成 Inbox／Outbox。首次 `/sessions`／`/focus` 选择 A，没有预先交给控制器的 A binding；候选 `/new` 通过实际无页脚握手绑定 B。
3. 显式 A／B 切换、`/cd` 精确复用、attach／detach 独立角色通过；重复入站只保留一条任务，重复 launch 不增加标签，两条并发创建中后一个在副作用前明确拒绝。
4. 正常结束候选连接后，以同一 daemon 新连接和同一隔离账本重建控制器，准确恢复 B，稳定编号不变；继续原上下文完成。
5. 原 A 所在 TUI 执行 `/new` 转入新桌面对话，进程不变。微信仍选 A，原上下文续接；桌面新对话的历史未变。原菜单读屏仅验证准确选项，不参与 thread 路由。
6. 关闭自有 TUI 后，原 A 在已确认订阅下仍加载，准确 A 又完成一次任务。退订后 15 秒内未卸载，验收器停止；随后只读确认真实 notLoaded，以显式 `--finish` 续做拒绝和清理。finish 从原快照重建保留选择的拒绝场景，不授予新资格，也不声称卸载后重启恢复成功。失败输入没有新任务、队列提交、resume 或改投，原生历史未变，明确告知“不会自动切换”。这是延迟卸载的实际证据，不承诺退订立即卸载。

候选流程共 7 个业务 client／turn，分别属于准确 A／B，全部 completed、零工具、零串投；另有 1 个专用桌面输入。路由命令／新建的生产读屏身份入口被替换为主动报错；恢复及其他边界另有离线陷阱回归。最多一个自有窗口、两个标签，完成后自有终端归零；配置／凭据／Codex 全局设置／托管定义摘要保持。没有发送真实微信消息，没有操作用户工作终端、部署制品或直接写生产账本，不能称作手机实收验收。

## 编号与兼容

稳定编号基于 native-v1、运行代次、完整 thread／native session 与规范 cwd；宿主退出不改变编号。快照 version 2 补充原生字段，schema 仍为 6。v1 仅凭准确真实端点／进程与原生身份重建旧指纹后迁移选择；缺证据通知重新选择，原选择保留为 unrestored_selection 诊断。旧任务／冻结目标不改写。

旧 unknown 的结果对账可只读核验原生准确 thread／cwd、稳定元数据及唯一原 client／turn 的终态，即使 notLoaded 也不创建订阅或恢复存档；不授予新派发资格。仓库占用继续独立遵守原严格证据条件。无效输入、重复／合并 client、错目录与身份缺失保持 unknown。

## 自测映射

以下表中“真实”仅指上述原生专用流程，“离线”为本次完整回归中的确定性测试；没有把模拟 daemon 换代或 PID 重用写成真实操作系统复现。

| 编号 | 证据及结果 |
| --- | --- |
| T01 | probe／flow：两条从启动前隐藏的首次接入真实通过 |
| T02 | flow 命令／创建读屏陷阱；test_native_target_lifecycle、test_visible_launch、test_sessions 的无宿主／读屏陷阱通过 |
| T03 | flow：已有 A 首次选择及原上下文记忆真实通过 |
| T04 | test_catalog 同目录无窗口关联与顺序；test_native_identity 稳定键；test_controller 旧列表失效通过 |
| T05 | test_native_target_lifecycle 多端点同 thread 去重通过；未制造同一 thread 的第二真实 TUI |
| T06 | flow：候选实际 boot／唯一完成握手、无 ID B 通过 |
| T07 | test_visible_launch 零／多 nonce、fork、越界页；test_engineering_boundaries 错项目通过 |
| T08 | test_visible_launch 缺回复／inProgress、test_sessions 原生 session 变化通过 |
| T09 | test_visible_launch 创建回执丢失、取消、重复意图；flow 重复 launch 无多余标签通过 |
| T10 | test_visible_launch 进程变化／runtime 换代；test_discovery 进程／TTY 边界通过 |
| T11 | test_native_identity notLoaded 不 resume；test_codex_connection 不支持版本拒绝通过 |
| T12 | test_sessions 身份／cwd；test_native_identity 共享根的 fork 分离通过 |
| T13 | test_controller 提交前换代、未知回执不重投；test_independent_target 卸载拒绝通过 |
| T14 | flow：同进程桌面切换后准确 A 完成，桌面新对话历史不变 |
| T15 | test_controller 接收顺序及冻结目标；flow 显式 A／B 切换通过 |
| T16 | flow attach／detach；test_controller、test_interactions、test_async_questions 准确请求与 send 路由通过 |
| T17 | flow：cd 复用与 new 真实创建；test_independent_target 失败不替代通过 |
| T18 | flow：关闭候选连接并重建，准确恢复 B、编号稳定通过 |
| T19 | test_native_target_lifecycle 缺身份／换代不恢复，旧选择诊断跨重启保留通过 |
| T20 | test_native_identity 同路径 socket 更换前／中拒绝；test_runtime_lifecycle 换代及未知保护通过；未重启共享 daemon |
| T21 | flow：关闭仍加载 A 继续、真实 notLoaded 后拒绝，两条边界通过 |
| T22 | test_native_target_lifecycle v1 精确指纹兼容／不猜恢复／v2 恢复通过 |
| T23 | test_native_target_lifecycle 卸载旧结果不改目标；test_admission_recovery 晚到结果与占用独立通过 |
| T24 | test_sessions、test_visible_launch、test_engineering_boundaries 未注册／消失／符号链接越界拒绝通过 |
| T25 | test_native_target_lifecycle 准确子 cwd 显式登记／范围提示／256 上限通过；未在新 trust 目录创建真实 TUI |
| T26 | test_native_identity 完整 loaded 分页；test_engineering_boundaries 多页／循环／重复／畸形拒绝通过 |
| T27 | test_engineering_boundaries 十页、总页数／条数／字节／总截止；test_routing 快照上限通过 |
| T28 | test_catalog 登记并发；test_controller 未提交选择不可见及 revision／恢复保护通过 |
| T29 | flow 并发创建明确拒绝／重复入站一条任务；test_visible_launch 持久化 launch 去重通过 |
| T30 | test_controller 订阅拒绝、队列满、原生终态先于回执及 unknown；test_subscriptions 真实 ACK 契约通过 |
| T31 | test_controller 同仓库／worktree、桌面忙碌、等待后一次派发；test_admission_recovery 占用边界通过 |
| T32 | test_image_controller／test_image_media、test_controller、test_async_questions、test_output 与回执系列既有能力回归通过；0.167.0 异步问题能力门禁保持原限制 |

## 制品与工程检查

第一次正常权限全量发现历史核对测试样本／断言问题；修正后 754 项／40.614 秒及编译／依赖／差异／文档通过。另加 2 项准确子目录与候选上限测试，12 项组合测试通过；最终数量与耗时由冻结检查摘要记录。早期沙箱 Unix socket bind 拒绝及自动审核超时均未冒充代码通过，之后已取得正常本地测试权限。

冻结候选在私有 `.tmp/native-session-no-footer/artifacts/`，57 个包文件与实际原生验收源码逐项一致；这些源码文件的最后修改均早于第一条原生业务输入。源码 SHA-256：`25c0bdf58fc43856a9380633a0c2c1478d0956d9cc05039a309c313c50082958`；wheel SHA-256：`746d2ab5489a9aa4b86af9b6187e529b684adcd7d70edd8c992dca2afb8d37e8`。

Python 3.14.5 的独立非 editable 安装、release manifest 验证及全部包文件比较通过。隔离副本使用该冻结解释器，以 `-I` 执行完整 `scripts/check.py`：756 项／40.640 秒，零失败、零跳过，编译／依赖／文档通过；检查器子进程总时长 42.165 秒。隔离副本无 Git，差异检查明确记为 not_a_git_checkout，根检出另执行 `git diff --check` 通过，不把该项当作跳过测试。最后文档收尾再执行链接／锚点、JSON、进度记录数量及公开内容检查，未因文档重复整轮测试。

## 交付与限制

候选代码、最小脱敏协议样本（test_native_identity／test_visible_launch 内联 fixture）、[显式探针](../../tests/integration/native_session_no_footer.py)、[完整验收器](../../tests/integration/native_session_no_footer_flow.py)、身份／兼容说明和[后续切换操作卡](../operations.md#tgt02无状态栏-id-候选与切换)均可审查。D01 至 D07 及逐项验收结论见施工清单。私有记录位于 `.tmp/native-session-no-footer/`，不进入 Git；未执行提交、标签、推送或部署，日常 ID 目前应继续保留。
