# 0.1.8：无状态栏 ID 接入发布与本机切换

状态：本人已明确授权提交、合并、打 tag、推送 GitHub 并切换本机版本，当前发布准备中。工程候选及真实原生验收见 [TGT02 交付](native-session-no-footer.md)；本记录只在操作完成并验证后更新为实际结果。

发布目的地为既有公共仓库 https://github.com/benarchen/wx-clawbot ，沿用 dev／main。只将已验收实现提升为 0.1.8，schema 6、精确依赖与原生版本范围保持。版本声明之外的 56 个包文件须与已完成无 ID 双路径、同进程桌面切换、桥接重启及关闭／卸载边界验收的冻结候选一致。

先冻结 wheel／lock／manifest，用独立非 editable 环境运行完整工程检查，复核全部包文件、父子来源、公开文件／可达历史及实际私密值。提交前同步相关文档；dev 正常提交，专用工作树 main 正常合并，annotated v0.1.8 指向功能提交，双分支／标签正常原子推送并独立核对远端。实际结果文档另行正常提交，同步双分支，不移动标签，不创建 GitHub Release，不强推或改写历史。

部署按[操作卡](../operations.md#tgt02无状态栏-id-候选与切换)，先从同一 wheel 安装全新独立版本目录，核对原实例空闲、待发／sending 与交互。正常停止本项目唯一消费者，确认 managed 退出及锁释放后备份私有账本，并核对完整性、外键和旧业务行。仅替换本项目原 LaunchAgent 的 ProgramArguments／WorkingDirectory，再 bootout／bootstrap 原 Label；核对实际 argv／cwd／manifest、父子制品、单消费者及 host／native 状态。

旧 v1 路由仅在准确真实来源和原生指纹证明时迁移，新 v2 路由完整复验；无法恢复时保留 unrestored_selection 并通知重新选择，绝不按同名或 cwd 猜目标。历史 unknown、冻结任务／回执及占用结果分离保护，不改库清锁、不重放未知任务。正常恢复提示与额外测试发送分别记账，不把 API accepted 写成手机实收。

失败恢复只恢复兼容 schema 6 的旧独立制品及原托管参数，保留当前数据库和故障证据，不回灌旧备份。不关闭用户终端或重启 Codex／iTerm2，不修改全局状态栏／认证／插件／Skills，不操作其他项目。实际加载通过后才确认日常已具备隐藏 ID 的条件；隐藏设置本身不在本轮实施范围内。

[机器摘要](native-session-release.json)随实际阶段更新；未完成步骤不标通过。

## 发布前核验

2026-11-07 17:29，GitHub main／dev 与本地基线 `dfa5372af49852649537c391340eefeaa2e673c4` 一致，默认 main，v0.1.8 不存在。冻结非 editable 制品完整 756 项／40.883 秒，零失败／跳过，编译／依赖／文档通过；隔离副本无 Git，开发检出另执行差异检查。57 包文件与 manifest 一致，56 个非版本文件与已真实验收候选完全相同。

源码 SHA-256：`c3cca6c23cd07ebd9e9716c57f0c02e4de959f52ade6732f2bf7101045421da1`；wheel SHA-256：`d43d12b76439135afee7ba959c20101ff5a2cd3648e9b254bb0d34ebfda07842`。287 份公开文件、2875 个实际私密候选值、全部可达 Git 对象及两份制品审计零匹配；提交后及结果收尾仍复核。

同一 wheel 已预装新独立目录，manifest 精确一致，隔离父子渲染 5 段通过。原实例空闲：执行／占用、pending／sending、同步及有效异步交互均为零；原 v1 路由没有输入目标和观察角色。已保存原 plist 并生成仅 ProgramArguments／WorkingDirectory 差异，plutil 通过。预检脚本曾因旧 manifest 路径残留停止，修正后完整预检通过；发生在停服前，没有生产影响。正式仍独立 0.1.7／schema 6、host／native ready，尚未停止。
