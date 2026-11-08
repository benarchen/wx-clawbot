# 0.1.9：文档整理、查询边界与冷启动修复发布

状态：本人于 2026-11-08 明确授权提交、合并、打 tag、推送 GitHub 和切换本机版本，当前正在准备发布。尚未完成的阶段不作成功声明；实际结果与摘要随后追加，进度以 [ROADMAP](../../ROADMAP.md) 为准。

## 本次范围与顺序

发布到既有公共仓库 https://github.com/benarchen/wx-clawbot ，沿用 dev／main，版本为 0.1.9，annotated v0.1.9 指向功能提交；schema 6、路由快照 version 2、依赖锁和原生能力门禁保持。远端与本地起点均为 `8278de5645a57f2fc0348b746d59899bfe0bdadd`，默认 main，标签尚不存在。

包含 [DOC01 文档整改](documentation-restructure.md)、[sessions 纯查询及 help 核对](sessions-query-help.md)、[冷启动零额外 Shell](iterm-single-window.md)。保留首轮冷启动失败及旧版本验收边界，不将此前 0.1.8 冻结测试改写为 0.1.9 的结果。

先提升版本并同步现行文档，冻结独立非 editable wheel／lock／manifest，运行完整检查；包文件应与已完成真实验收的第二候选逐项相同，仅 __init__.py 的版本声明变化。公开内容、实际私密值、两份制品及全部可达 Git 对象审计通过后，在 dev 正常提交，main 专用工作树快进合并，打注释标签并正常原子推送；独立读取 GitHub 引用复核。实际发布／部署结果另行正常提交并同步双分支，不移动已发布标签，不强推或创建额外 GitHub Release。

## 本机操作与恢复

遵循[独立制品切换操作卡](../operations.md#eng01独立运行制品与开发隔离)。从同一 wheel 预装全新私有 release，核对候选来源、原实例、活动任务／占用、交互及 sending／pending；正常停止原消费者，确认退出及锁释放后，使用 SQLite backup 保存一致副本并检查完整性与外键。

只替换本项目原 LaunchAgent 的 ProgramArguments 和 WorkingDirectory，保留 Label、config、state-dir、PATH、日志与托管策略；校验后 bootout／bootstrap 原 Label 一次。核验实际 argv／cwd／manifest、父子来源、唯一消费者、host／native、旧任务／unknown／冻结回执及路由。当前 schema 无变化，不运行迁移或数据恢复，不改库清锁、不重放任务、不发送额外微信测试消息、不退出或重启 Codex／iTerm2。

若切换失败，先保留当前数据库与诊断，保持停止并核对准确失败阶段；只恢复兼容 schema 6 的原独立 0.1.8 制品及原托管参数，不用旧备份覆盖已有新写入。配置、凭据和全局设置不在本轮变更范围。预检与制品验证均在正常停服之前完成，停服期间不等待模型或授权。

[机器摘要](maintenance-release.json)按实际阶段更新；日常加载通过前仍以原 0.1.8 为运行版本。

## 发布前核验

0.1.9 的独立非 editable 制品完整 771 项／40.413 秒通过，零失败、零错误、零跳过；编译、依赖、文档及差异检查通过。57 个包文件与 manifest 一致；相较已完成真实冷启动验收的第二候选，仅 __init__.py 的版本声明变化，其余 56 个包文件保持。

源码 SHA-256：`ebc003f60509152906f31af84ae4a6c1a44f4acbdd396743fc08e5158bd8fa47`；wheel SHA-256：`52fdeee15c281f3bed9a04bdd5a2f547171686e5213b00cfec79af1b3dad2a7c`。首次依赖安装被沙箱网络限制阻止，随后在正常权限下继续完成本轮隔离环境的精确锁安装与冻结，未变更依赖声明或锁文件，未将失败安装算作验证通过。

发布前公开内容与实际私密值比较：306 份文件、3118 个私密候选、918 个 blob／396 个 tree／57 个 commit／7 个 tag，以及 wheel／sdist 两份制品，零匹配。新增发布记录与提交／部署收尾仍继续复核，不把这组计数当作后续全部审计数量。

同一 wheel 已预装到全新私有版本目录，manifest 完全一致；隔离渲染子进程输出五段并通过来源核验。当前 0.1.8 正式实例可核验、host／native ready，活动任务、等待／持有占用、pending／sending、同步及有效异步交互均为零。仅 ProgramArguments／WorkingDirectory 的 plist 差异已生成，plutil 校验通过，原 plist 已私有留存；此时尚未停止日常服务。
