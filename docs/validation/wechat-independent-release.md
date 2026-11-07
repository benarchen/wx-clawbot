# 0.1.7：微信独立选择发布与本机切换

状态：本人已明确要求提交、合并 main、打 tag、推送 GitHub 并切换本机版本，当前发布准备中。功能与真实原生验收见 [TGT01 交付](wechat-independent-target.md)，实际 Git 与部署结果在完成后更新；进度以 [ROADMAP](../../ROADMAP.md) 为准。

本轮版本为 0.1.7，schema 6、依赖锁和原生版本范围保持。核对候选包除版本声明外与已通过原生 A→B、准确 A 上下文续接、显式 B 切换和关闭拒绝的实现相同。构建冻结 wheel 并在独立非 editable 环境执行完整检查，不以开发 editable 环境替代制品验收。

发布目的地为既有 https://github.com/benarchen/wx-clawbot ，沿用 dev／main。功能提交后在专用工作树将 main 快进至 dev，创建 annotated v0.1.7，正常原子推送双分支和标签；独立核验远端后再切换本机。实际发布／部署结果文档另行正常提交、同步双分支，不移动已发布标签，不创建 GitHub Release，不强推或改写历史。

切换前准备同一冻结 wheel 的独立版本目录，核对无活动执行／占用、待答交互或 sending。正常停止唯一消费者，确认旧托管退出 0 后保存私有一致性账本备份。只修改本项目 LaunchAgent 的 ProgramArguments／WorkingDirectory，配置、状态根、Label、日志策略保持，再 bootout／bootstrap 原服务。核对新实际 argv／cwd／manifest、父子来源、schema、单消费者、组件状态、旧回执及 unknown 保护。

若切换失败，保持当前账本与故障证据，按 schema 6 兼容性恢复旧独立代码和原托管定义；不恢复旧数据库、不清理未知任务或重放。仅本项目桥接受短暂重启影响，不关闭 iTerm2、不重启 Codex、不操作其他项目服务，不向微信发送额外测试消息。原制品、原托管定义和备份保留。

## 2026-11-07 11:08 发布前核验

远端 main／dev 与本地基线 `e687a982eea66a48e90cc98abc8c072dfbdc875f` 一致，默认 main，v0.1.7 不存在。独立非 editable 制品完整 723 项／40.526 秒及编译／依赖／文档通过，开发仓库另核对 diff；57 个包文件与 manifest 一致，已验收候选的 53 个非版本 Python 文件未变。

源码 SHA-256 为 `b4f2e9403d4f405808117300a2bb8c19e043280e87141b2b8546dc7b0a7c2a32`，wheel SHA-256 为 `328e8a77338fb884b2e804530e7413b3154e73a0490c82d0c7cb9efc48d2f2b9`。276 份公开文件、2827 个私密候选、两份制品及全部可达对象检查零匹配；新增提交仍须复核。

同一 wheel 已预装独立版本目录，manifest 相同，父子隔离渲染 5 段通过。活动任务／占用／待发／sending／同步与有效异步交互均为零；原托管定义备份、仅 ProgramArguments／WorkingDirectory 差异及 plutil 检查通过。生产仍独立 0.1.6／schema 6、host／native ready，尚未停止或切换。[机器摘要](wechat-independent-release.json)。
