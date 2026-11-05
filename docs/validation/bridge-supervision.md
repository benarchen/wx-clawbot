# 微信桥接进程恢复与托管

AUD01 交付补充：native_unavailable 的脱敏分类、异常组有界展开及故障日志限频已实现，并已按后续授权加载到日常托管进程，最初为[独立 0.1.4](aud01-local-deployment.md)，当前已按授权升级为[独立 0.1.5](iterm-cold-start-release.md)。原有权限／轮转保持，实际回归和适用边界见[AUD01 记录](native-diagnostics-rules.md)，操作语义见[运维说明](../operations.md#aud01候选诊断与规则验收)。本说明不改写下述历史验收结果。

2026-10-29 20:51，北京时间。本人已明确同意恢复原配置桥接，并补齐持续运行、异常退出记录及恢复机制。本项为 HOST01 联试前的运维补救，不创建新 Goal，MD01 继续待正式开工。

## 已确认的故障与恢复

- 20:48 只读检查：前台状态 stopped、消费者锁空闲、原记录进程不存在；最后收发为 12:01:27，18:00 后入站记录为 0。
- 旧前台没有持久 stdout 日志，原工具句柄也已不可用。不能据此确定进程退出的时间、信号或异常原因，不把推测写为根因。
- 20:51 按本人授权复用原配置、绑定与 schema 3 账本启动，host／native 均 ready。本人随后截图确认新 `/help`、`/status` 收件；未选择执行目标，两条原 unknown 仍保留，不重放。

## 本次实施契约

采用用户级 launchd，仅管理 wx-clawbot。计划对象为 `~/Library/LaunchAgents/local.wx-clawbot.plist`；日志与托管记录仅放本人原私有运行目录。配置、凭据、schema、Codex／iTerm2 全局设置及业务项目不修改；不会配置第二个消费者，不重启原生运行时。

- B01：保存当前基线并恢复收发，记录本人截图与账本证据。
- B02：新增独立托管入口，复用既有 serve；记录启动、正常退出、异常类型、信号及前次未能观察的退出，不记录任意 stdout／stderr、消息正文或凭据。私有日志轮转，单文件最多 1 MiB、保留 3 份备份。
- B03：用户登录启动；异常退出后由 launchd 限速恢复，ThrottleInterval 为 30 秒；主动 stop 正常退出码为 0，不立即拉起。Stop 与 bootout 各自的语义须明确。运行时仍用原身份核验和未知不重放规则。
- B04：验证日志脱敏／容量／权限、重复启动保护、异常及正常退出、状态只读；全套回归、编译和差异检查。用独立测试 Label 与无网络替身真实验证 launchd 重启及正常退出不重启，然后移交正式进程；不以杀死用户业务会话测试保活。
- B05：安装并仅注册本项 Label，正常停止临时恢复实例后才交接。核对单消费者、ready、配置摘要与任务状态；本人真机回复与 HOST01 应用重启关卡分别记录。最终同步指南、ROADMAP、HOST01 和 MD01 基线失效说明。

回退：仅 bootout 本项 Label，确认消费者停止后使用原前台 serve 命令；保留私有日志、账本与凭据，不操作其他服务。托管只在本人登录的 GUI 会话下运行，电脑睡眠／关机期间不承诺微信在线，尚未完成的跨重启验收保持未验证。

依据：[Apple launchd 说明](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)及本机 `man launchd.plist`；已核对 SuccessfulExit、ThrottleInterval、RunAtLoad 与 ExitTimeOut。完整应用／宿主验收仍按 [HOST01 记录](host-lifecycle-recovery.md)。

## 实施结果

2026-10-29 21:02：B01 至 B05 的本次恢复／托管交付已通过。完整机器摘要见 [JSON](bridge-supervision.json)。

| 对象 | 实际验证结果 |
| --- | --- |
| 离线回归 | 最新 443 项，全部通过，24.438 秒；包含 11 项托管专测及 2 项新增状态／身份回归 |
| 其他检查 | 编译、依赖完整性、模板 plutil 及差异格式通过 |
| 真实 launchd 策略 | 独立无网络测试 Label 下，退出码 7 后 30.054 秒重新启动；第二次退出码 0 后观察 35 秒，启动次数仍为 2；自有测试 Label 已卸载，微信及原生调用为 0 |
| 正式交接 | 先一致性备份私有 schema 3 账本并 integrity_check，通过正常 stop 释放临时实例，再注册唯一正式 Label；没有两个消费者并行 |
| 实际脱离工具 | bootstrap 命令结束后，由独立只读命令核对 launchd PID 与桥接完整身份一致，supervision running；服务不依赖原工具前台句柄 |
| 数据保护 | 原配置摘要、全部任务 ID／状态／client 摘要及 schema 均一致；源码摘要与通过回归的版本相同，两条 unknown 原样保留 |
| 私有日志 | bridge.jsonl 及 managed.json 均为 0600；启动与依赖状态事件落盘，普通输出及原始错误正文不落盘 |
| 本人真机 | 托管后新 `/sessions` 有 2 条 accepted 回执，最后回执约 0.903 秒；新 `/status` 有 1 条 accepted 回执，约 0.559 秒，本人截图确认收件；未决回执 0 |

21:02 交付时加载的源码 SHA-256：`1db4fed7bdce578553abfbf7221ee80fb24844cd3d766e6c46eade07778cc14b`。旧前台退出的具体原因仍无法追溯，不因新增日志而补造历史原因。21:02 交付时尚未执行 Mac 重启；后续本人实际重启及核验另记如下，不与无网络替身证据混合。

本次只注册本人专用启动项，没有提交、推送、合并，未改其他服务或 Codex／iTerm2 全局设置。HOST01 的应用整体退出／重启、按需启动和原会话连续性继续按其原关卡验收，不因本次托管交付而完成 HOST01。MD01 开工前须以该版本或后续 HOST01 最终版本重建基线，12:34 快照只保留为历史。

2026-10-29 21:20 补记：本人因电脑问题实际重启 Mac，系统启动时间核对为 21:07:19。只读确认 managed 进程在本次开机后启动、launchd PID 与有效桥接身份一致，原配置／schema／任务计数及已验收源码摘要保持；本轮没有手动启动桥接。host not_running、native unavailable，本人确认重启后 `/help`、`/projects`、`/status` 均有回复。该证据证明本次登录启动恢复；不保证关机／睡眠期间在线，也不证明旧原生进程跨重启存活。后续按新一轮继续 HOST01。

2026-10-29 23:47 HOST01 后续源码交接：授权超时分类及非交互传输探测修正后，450 项回归通过；通过既有托管入口正常 stop／启动加载最终源码，配置／schema／任务计数保持，原 Codex 及准确 focus／observer 保留，host／native ready。此处更新加载版本，不重新宣称本文件历史托管测试已在全部新场景重跑；HOST01 真实故障修正版复测仍待执行。

2026-10-30 07:43 HOST01 日常恢复交接：现场已核验 0.166.0，最终 456 项回归通过，宿主恢复及只读终态对账修正版已加载。验收临时配置已结束；正常退出码 0、单 Label bootout／原 plist 精确恢复／bootstrap 通过，原两项目配置／凭据／global／schema／task ID、state、client 摘要保持，历史 unknown 2 不重放，host／native ready。原生 daemon 未停止，临时测试信任及自有终端已清理。最后本人微信收件和 HOST01 完成状态以 HOST01 记录为准，不改写此前托管策略实测的版本与结果。
