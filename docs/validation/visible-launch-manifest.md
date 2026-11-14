# 可见启动继承旧 manifest 的修复

状态：0.1.13 已发布并完成本机正式切换；代码、回归、架构图及真实 iTerm2 复测通过。当前进度以 [ROADMAP](../../ROADMAP.md) 为准。

## 0.1.13 发布范围

功能代码保持上述最小修复，应用版本从 0.1.12 升为 0.1.13，schema 6、路由快照 version 2 及 0.167.0／0.169.0 原生协议准入不变。正式冻结制品 source `6330afe5`／wheel `ce64f6b5`；发布前以同包完整回归、编译、依赖、文档和公开内容检查为门禁。

本人已明确授权提交 dev、正常合并 main、创建 annotated `v0.1.13`、推送 dev／main／tag，并在最后切换本机运行版本。部署使用同一冻结 wheel 的全新私有独立目录；先核活动任务、占用、交互、待投递和所选原生队列，正常停服后完整备份私有状态，仅替换本项目 launchd 的解释器、manifest 和 WorkingDirectory。旧制品与数据保留，不迁移、不覆盖恢复、不自动发送微信或重放 landrop。

## 发布与本机结果

2026-11-15 06:04 已核验：功能提交 `de4c8dddbb8c5fa8474f9e326e3ec89bd6d36de9`，dev／main 正常快进至同一提交，annotated `v0.1.13` 解引用至该提交，远端双分支及标签一致。工作树和同包各 936 项完整回归通过，编译、依赖、文档与 diff 检查通过；实际安装包 source `6330afe5`／wheel `ce64f6b5` 与冻结制品一致。

部署前活动任务／占用／交互／待投递均为零，所选准确原生会话 idle、loaded 且队列为空。旧服务正常退出 0；13 表一致性备份、完整性及外键检查通过，另保存私有配置、控制记录与启动资料。仅修改本项目 launchd 的 ProgramArguments／WorkingDirectory，新实例 21.361 秒恢复 host／native ready。

实际 argv／cwd／manifest、非 editable 包、父子来源和唯一消费者通过；9 张非路由业务表旧行精确保持，旧回执与投递尝试保持，2 条历史 unknown、11 份控制记录、12 个注册项目及原 target／observer 不变。配置、凭据、Codex 全局配置和原 Codex／iTerm2 进程保持；无 schema 迁移、数据库恢复、额外原生任务或自动微信消息。

## 根因

2026-11-15 05:14，本人 `/cd landrop` 后收到 iTerm2“会话在启动后很快结束”的通用警告。准确启动登记停在 handshaking，没有 boot 回执；项目目录和原生可执行文件均存在。

只读核对实际进程环境发现，iTerm2 从旧桥接继承了另一独立 release 的 `WX_CLAWBOT_RELEASE_MANIFEST`。新版启动器随后读取这个旧路径，`verify_active()` 按设计拒绝“当前解释器＋旧 manifest”的组合。iTerm2 不解析 manifest；它是启动器退出后的通用提示，不是 AI Coding Profile 配置错误。

原固定启动命令只携带解释器、模块、登记目录和 launch ID，错误地依赖 GUI 环境。历史冷启动测试曾用 `CandidateRegistry` 显式传入同一 manifest，证明该冲突已知，但生产入口此前没有覆盖。

## 修复与边界

`LaunchRegistry.command()` 通过 `/usr/bin/env` 固定子进程环境：正式运行显式覆盖为桥接当前 manifest；没有 manifest 的开发运行明确清除该键。解释器保持原 venv 路径和 `-I` 隔离，launcher 仍调用 `verify_active()`，exec 外部 Codex 前仍移除桥接专用变量。

没有修改 iTerm2 Profile、全局环境、Codex 配置、启动登记格式或 SQLite schema；没有自动重放已失败的 landrop 创建意图，也没有修改、提交或部署当前运行制品。

## 验证

- 新增正式覆盖及开发清除两条回归，先在原实现失败，再在修复后通过；既有固定入口、路径注入及外部 Codex 不继承桥接变量的断言保持。
- 可见启动与 release 专项 41 项通过；完整离线数量与结果见 ROADMAP 最近验证。
- F05 从架构文档 Mermaid 使用项目隔离的 Mermaid CLI 重新渲染 SVG／PNG，实际视觉检查中文、箭头和失败分支无裁切或遮挡。
- 2026-11-15 05:38 真实复测通过：独立候选 source `a53f4a68`／wheel `0eea8337` 在 iTerm2 保留旧 manifest 的条件下只新增一个自有测试窗口，12.070 秒内生成 boot 回执及唯一 completed 原生握手，准确进程／TTY／thread 复验通过；该窗口空闲后准确关闭。没有微信发送、生产账本写入、业务终端输入或配置修改。
- 测试工具前七次前置检查失败均未创建终端；最后一次成功启动不复用任何先前创建意图。候选全量测试曾有一条夹具未清除正式 manifest 的失败，修正测试环境隔离后重跑最终结果见 ROADMAP，不改写这段历史。
- 当前旧版运行服务不会因开发源码变化获得修复；本机正式部署需另行明确授权。
