# iTerm2 冷启动默认 Shell 修复

2026-11-08 13:50，第二冻结候选真实冷启动验收通过：iTerm2 3.7.7／Codex daemon 0.167.0，一次应用启动、一个自有窗口、两个 Codex 标签，零额外普通 Shell；两个项目分别重复 cd 均复用原会话，自有测试终端已清理并复验缺席，受保护配置及持久启动偏好保持。首轮 AppleScript launch 失败证据保留；本轮未提交或部署，也不代表手机实收验收。[机器摘要](iterm-single-window.json)、发布／部署状态见 [ROADMAP](../../ROADMAP.md)。

## 原因与改动

原 `ItermBackend.launch()` 使用 `open -g -b` 拉起应用，iTerm2 可以自行打开默认 Shell；随后 `ItermWindowStarter` 创建桥接拥有的 Codex 窗口，因此留下普通 Shell 和 Codex 两个窗口。[旧冷启动记录](iterm-cold-start-live.md)已明确记录测试结束后保留应用默认 Shell，原“可见会话就绪”验收不代表这个体验问题已解决。

当前候选通过系统 osascript 的 JavaScript／Objective-C 桥接调用 AppKit `NSWorkspace.openApplicationAtURL:configuration:completionHandler:`，固定 bundle ID、后台启动、首事件 ascr／noop，并且仅传入 `-OpenNewWindowAtStartup NO`。仍使用有截止时间、取消时回收的子进程入口；失败不回退到普通 open 或重复创建。API 的进程核对、传输等待和授权保持；SDK 创建自有窗口／标签、boot 进程与唯一原生 completed 握手保持。未增加依赖、持久偏好写入、普通 Shell 识别／接管／关闭代码。

该参数进入退出即失效的 NSArgumentDomain，[Apple 文档](https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/UserDefaults/AboutPreferenceDomains/AboutPreferenceDomains.html)明确其临时覆盖语义。只覆盖 startup 的默认新窗分支，不设置控制恢复的 `OpenNoWindowsAtStartup`／`OpenArrangementAtStartup`，也不设置控制 Dock 后续打开窗口的 `OpenUntitledFile`。[匹配版本设置定义](https://github.com/gnachman/iTerm2/blob/v3.7.7/sources/Settings/iTermAdvancedSettingsModel.m)与[读取实现](https://github.com/gnachman/iTerm2/blob/v3.7.7/sources/Settings/iTermUserDefaults.m)已核对；AppKit 参数及首事件语义另核本机 macOS SDK 的 NSWorkspace.h、NSAppleEventDescriptor.h。进程级启动参数不是永久全局偏好变更，也不能用更宽的禁用恢复开关替代。

同时纠正 `HostUnavailable("not_running")` 的遗漏提示：按需启动入口为 `/cd`、`/new`，`/sessions` 仅查询，不启动应用。其他查询边界保持[上轮修复](sessions-query-help.md)。

## 一手证据与验证前提

本机安装版本经 Info.plist 核对为 iTerm2 3.7.7。读取匹配标签的[应用启动实现](https://github.com/gnachman/iTerm2/blob/v3.7.7/sources/AppKit/iTermApplicationDelegate.m)及[初始窗口状态机](https://github.com/gnachman/iTerm2/blob/v3.7.7/sources/AppLaunch/iTermUntitledWindowStateMachine.m)：初始窗口受启动活动、窗口恢复及偏好共同影响。因此 `launch` 是否满足本机冷启动的零额外 Shell 要求必须实测，不能从事件名称或旧版本声明推定。

本轮不修改窗口恢复偏好；恢复的用户窗口不当作冗余窗口。为得到明确的零额外 Shell 验收，先由本人保存工作、关闭现有终端窗口并完全退出应用。Agent 不代替本人退出或清空工作终端。

## 已执行

下表保留首轮基础验证；第二候选的冻结检查及最终真实结果分别见后文。

| 验证对象 | 方式与实际结果 |
| --- | --- |
| 首轮启动脚本 | 本机正常权限下 osacompile 成功，仅编译、不执行；初次沙箱无法解析应用 ID 的失败保留，不算应用不支持 |
| 首轮已运行应用 | 实际向正在运行的应用发送候选 launch；同一 PID、两个窗口及全部标签／终端 ID 保持，配置／凭据／Codex 全局配置／托管定义及 iTerm2 plist 摘要保持；未读屏、输入或关闭终端 |
| 新回归有效性 | 在旧 lifecycle 实现上运行同一组两个新断言，启动事件和 sessions 错误提示均出现预期失败，无测试错误 |
| 宿主回归 | 34 项通过：单次应用启动、非零返回不回退、取消回收、失败不授权／不重试、已运行不再次启动，以及既有延迟就绪、换代和并发单次行为 |
| 完整离线检查 | 771 项／40.418 秒，零失败、零错误、零跳过；编译、依赖、文档与差异检查通过 |
| 显式验收入口 | [iterm_single_window.py](../../tests/integration/iterm_single_window.py) 的 help 与编译通过；首轮真实失败，第二轮真实通过，分别保留准确 case |

### 首轮失败与第二候选

本人已保存并退出应用后，以首个冻结候选运行一条合成 cd：launch／wait_ready／connect／create_terminal 各一次，准确 Codex 握手 ready，但实际有两个单终端窗口。脚本按预定失败条件停止，仅核对原进程、idle 和空队列后关闭自有 Codex 测试终端，额外普通 Shell 保留，未接管或关闭。第一候选源码摘要 `b7c88e4966e9132a7857adfe6a9f5f1fc6909399cb0836e1dade7dbd02e933ca`；失败 case 保留为 unexpected_windows，不能重跑或改成成功。

依据匹配版本 `performStartupActivities`／`shouldOpenUntitledFileAfterRunningAutoLaunchScripts:` 的主动新窗分支，第二候选同时采用 noop 初始事件和临时 startup 开关。只读参数探针中，JavaScript null 到 Objective-C 描述符的桥接曾崩溃；核对 SDK 头文件与崩溃栈后改为 JXA 的 `$()` nil，描述符事件类／事件 ID 实际读回正确，期间没有启动应用或写配置。随后第二入口在已运行应用上实测：原 PID、一个窗口及全部标签／终端保持，受保护配置与 iTerm2 plist 摘要保持。

第二候选 771 项／40.557 秒及编译／依赖／文档／diff 通过。全新非 editable 制品源码摘要 `0ee94920f638653a2bd57e6d0d8061b94e87c00cbb051dd2f5776e7887df7bc2`，wheel 摘要 `eedce51cd55bd7242326fc7fd32d4cacc76169c6b80a02cdc490edd7afed086e`；与第一候选分目录保存，没有覆盖失败制品。后续验收必须使用第二候选准确 manifest。

第二候选的独立非 editable 解释器再次执行完整检查：771 项／40.319 秒、编译／依赖／文档／diff 全部通过。正式验证器另核 help／编译和失败 case／自有清理边界，记录自身摘要并复验自有终端确实消失；此前文档与 sessions 修复保持，未扩展到部署。冻结阶段仅记录离线通过；本人再次退出应用后才执行下面的真实冷启动，没有把等待期间的离线检查当作真实通过。

私有原始记录位于 `.tmp/iterm-no-default-shell/`。隔离非 editable 候选与正式日常版本分离；不通过开发导入路径修改正在运行的制品。

## 真实冷启动验收

仅在确认 iTerm2 完全退出后，以准确冻结 manifest 运行显式入口，创建两个临时项目和独立合成账本；不连接真实微信收发接口，不直接写生产账本。脚本拒绝已有应用进程和重复 case 意图，失败后先检查私有记录，不直接重跑。

第二轮以全新 case 实际执行四条合成命令：A 项目 cd、A 重复 cd、B 项目 cd、B 重复 cd。两个新建分别完成唯一原生启动握手，并核对准确 cwd、启动进程／TTY 及原生加载身份；两个重复命令均保持准确目标、没有新增创建。核验阶段总计 26.344 秒，不作为首次 cd 的单独延迟或性能提升数据。

| 检查点 | 验收标准 | 当前结果 |
| --- | --- | --- |
| 首次冷启动 | 合成的一条 `/cd` 完成准确原生握手，应用只启动一次；仅一个自有窗口、一个 Codex 终端，零额外普通 Shell | 真实通过 |
| 第二项目 | 同一应用与自有窗口新增一个标签，准确新对话／cwd；不额外创建默认 Shell | 真实通过；合计创建两个终端，应用／连接／就绪等待均一次 |
| 重复 cd | 两个项目分别重复 cd，复用准确受管对象，应用／终端创建次数不增加 | 两条真实命令均通过 |
| 失败边界 | 超时／拒绝／取消不重复启动或创建，不假报 ready；额外或恢复窗口存在时不接管、不关闭，保留证据 | 超时／拒绝／取消为离线验证；首轮额外窗口为真实反例，准确中止且保留 |
| 保护与清理 | 全局及生产配置保持；准确自有进程、idle 与空队列核对后才关闭测试终端，未知资源保留 | 两个自有终端均清理并复验缺席；配置及四项持久启动偏好保持 |

独立只读收尾确认：iTerm2 仍运行，窗口与终端均为零，未留下普通 Shell；第二候选实际安装的 lifecycle 文件与开发源码逐字节一致，四项持久启动偏好与第二轮前快照一致。原生会话的后续卸载仍由原生运行时决定，不将终端清理当作删除聊天记录。

当前验收覆盖上述版本和专用场景，没有额外执行“恢复已保存用户窗口”或“Dock 点击”的 UI 专项；相关开关未被覆盖，保持既有原生机制，已运行用户窗口保护另有真实验证。恢复窗口不当作冗余窗口，未知窗口仍不接管或关闭。未提交、打标签、推送、部署或宣称手机实收通过；日常服务仍加载原 0.1.8，须另行发布部署才获得本次代码行为。


## 2026-11-08 14:07 后续公开交付

本页保留工程验收时点的版本、未提交／未部署和失败记录；本人后续明确授权后，成果已随 0.1.9 完成 GitHub 提交／main 合并／注释标签／推送，并在本机加载独立制品。实际引用、候选差异与旧数据保护见[版本交付](maintenance-release.md)，不改写本页原始验收摘要或冒充手机实收。
