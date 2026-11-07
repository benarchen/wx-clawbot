# 0.1.7：微信独立选择发布与本机切换

状态：2026-11-07 11:12，0.1.7 功能提交、main 快进合并、annotated v0.1.7 及双分支／标签原子推送完成，独立远端核验通过；随后本机已加载同一独立制品，host／native ready，旧数据保护通过。功能与真实原生验收见 [TGT01 交付](wechat-independent-target.md)，进度以 [ROADMAP](../../ROADMAP.md) 为准。

本轮版本为 0.1.7，schema 6、依赖锁和原生版本范围保持。核对候选包除版本声明外与已通过原生 A→B、准确 A 上下文续接、显式 B 切换和关闭拒绝的实现相同。构建冻结 wheel 并在独立非 editable 环境执行完整检查，不以开发 editable 环境替代制品验收。

发布目的地为既有 https://github.com/benarchen/wx-clawbot ，沿用 dev／main。功能提交后在专用工作树将 main 快进至 dev，创建 annotated v0.1.7，正常原子推送双分支和标签；独立核验远端后再切换本机。实际发布／部署结果文档另行正常提交、同步双分支，不移动已发布标签，不创建 GitHub Release，不强推或改写历史。

切换前准备同一冻结 wheel 的独立版本目录，核对无活动执行／占用、待答交互或 sending。正常停止唯一消费者，确认旧托管退出 0 后保存私有一致性账本备份。只修改本项目 LaunchAgent 的 ProgramArguments／WorkingDirectory，配置、状态根、Label、日志策略保持，再 bootout／bootstrap 原服务。核对新实际 argv／cwd／manifest、父子来源、schema、单消费者、组件状态、旧回执及 unknown 保护。

若切换失败，保持当前账本与故障证据，按 schema 6 兼容性恢复旧独立代码和原托管定义；不恢复旧数据库、不清理未知任务或重放。仅本项目桥接受短暂重启影响，不关闭 iTerm2、不重启 Codex、不操作其他项目服务，不向微信发送额外测试消息。原制品、原托管定义和备份保留。

## 2026-11-07 11:08 发布前核验

远端 main／dev 与本地基线 `e687a982eea66a48e90cc98abc8c072dfbdc875f` 一致，默认 main，v0.1.7 不存在。独立非 editable 制品完整 723 项／40.526 秒及编译／依赖／文档通过，开发仓库另核对 diff；57 个包文件与 manifest 一致，已验收候选的 53 个非版本 Python 文件未变。

源码 SHA-256 为 `b4f2e9403d4f405808117300a2bb8c19e043280e87141b2b8546dc7b0a7c2a32`，wheel SHA-256 为 `328e8a77338fb884b2e804530e7413b3154e73a0490c82d0c7cb9efc48d2f2b9`。276 份公开文件、2827 个私密候选、两份制品及全部可达对象检查零匹配；新增提交仍须复核。

同一 wheel 已预装独立版本目录，manifest 相同，父子隔离渲染 5 段通过。活动任务／占用／待发／sending／同步与有效异步交互均为零；原托管定义备份、仅 ProgramArguments／WorkingDirectory 差异及 plutil 检查通过。生产仍独立 0.1.6／schema 6、host／native ready，尚未停止或切换。[机器摘要](wechat-independent-release.json)。

## 2026-11-07 11:12 实际发布与部署

26 文件功能提交为 `219912c64b20b720fda50684b8bb9f2a60cf6a4e`，dev 正常提交、专用工作树 main 快进合并，annotated v0.1.7 指向该提交。正常原子推送 main／dev／标签后，独立读取 GitHub 双分支、默认 main、标签对象及 peeled 提交，均准确匹配。实际结果文档随后正常提交并同步双分支，不移动标签，不创建 GitHub Release。

本机由独立 0.1.6 正常切至同一冻结 0.1.7，schema 6 不变。旧消费者与 managed 正常退出 0，锁释放后完成 13 表一致性备份、完整性及外键检查；只修改本项目托管 ProgramArguments／WorkingDirectory，bootout／bootstrap 原 Label。新实际进程 argv／cwd／manifest、父子加载、唯一消费者与 host／0.167.0 native ready 通过，请求正常停止至验收 7.692 秒，该指标包含退出、备份及检查时间。

原路由角色／目标、587 条冻结回执及其旧投递尝试、两条 unknown 保持一致，另外 10 张业务表逐行一致；没有新增恢复通知、任务提交或额外微信测试消息。配置、凭据、Codex 全局设置与原生进程保持；没有迁移、数据恢复或任务重放。旧 0.1.6 独立目录、原托管定义及私有备份保留。

发布前后 277 份公开文件、2827 个私密候选、两份制品及可达历史检查零匹配；包源码／manifest 一致，53 个非版本 Python 文件与已验收候选相同。首次发现仍依赖准确页脚，手机真实传输和未新增验收的原生场景保持原边界。

[功能提交](https://github.com/benarchen/wx-clawbot/commit/219912c64b20b720fda50684b8bb9f2a60cf6a4e) · [v0.1.7](https://github.com/benarchen/wx-clawbot/tree/v0.1.7) 。
