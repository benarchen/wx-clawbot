# 文档导航与维护

先按角色进入，再按主题查细节。本文负责信息组织；项目规则以 [AGENTS](../AGENTS.md) 为准，当前进度只见 [ROADMAP](../ROADMAP.md)。

## 阅读路线

| 读者／任务 | 推荐顺序 |
| --- | --- |
| 使用者：首次任务 | [快速开始](../README.md) → [准备与启动](operations.md#安装与准备) → [微信登录与本人绑定](wechat-protocol.md) → [命令契约](command-contract-proposal.md) |
| 产品：范围和验收 | [PRD](product-design.md) → [需求追溯](requirements-traceability.md) → [兼容矩阵](protocol-baseline.md) |
| 开发者：接手和改动 | [项目规范](../AGENTS.md) → [开发指南](development.md) → [架构](architecture-design.md) → [开发契约](development-contracts.md) → [测试指南](testing.md) |
| 维护者：发布与恢复 | [运维手册](operations.md) → [账本](state-schema.md) → [安全边界](../SECURITY.md) → 对应版本验证记录 |
| 调研者：取舍与历史 | [ADR](technical-decisions.md) → 对应带日期 Goal 和验证记录；截图只作原始参考 |

## 主题权威位置

| 文档类别 | 回答的问题与维护源 | 不承担的职责 |
| --- | --- | --- |
| 入口 | 根 README：项目、前提、最小使用路线、许可 | 不堆放发布全过程 |
| 产品 | product-design：用户、价值、范围、P01 至 P14、验收 | 不复制 RPC 字段和施工进度 |
| 架构 | architecture-design：上下文、模块、部署、运行和质量 | 不替代命令或运维操作卡 |
| 技术设计 | development-contracts 及身份、命令、图片、异步、排版、规则等专题 | 不将概念对象冒充真实接口 |
| 兼容／数据 | protocol-baseline：逐能力版本和证据层级；state-schema：账本、容量、迁移和保留期 | 不把 schema 存在写成真机通过 |
| 决策 | technical-decisions：ADR 背景、替代、后果和重评条件 | 不把历史未验证问题当作当前待办 |
| 工程协作 | development、testing、AGENTS | 不重复全局规范，不默认操作真实终端／微信 |
| 运维／安全 | operations、根 SECURITY | 文档命令不授予执行权限，规范不冒充技术隔离 |
| 追溯 | requirements-traceability：需求→行为→设计→实现→测试→证据 | 不成为第二份进度表 |
| 进度 | 根 ROADMAP：当前快照、待办、最近完成／验证 | 长期过程保存到带日期记录 |

## 现行、历史与参考

- `docs/` 根目录的设计和契约描述当前基线；明确标注的历史段落仅适用于所述时间和版本。`native-session-evidence.md` 是早期 W02 调查，不是当前接入要求。
- `docs/validation/` 保存带版本与范围的验收、失败、发布和部署记录。结论只在其前提内成立；`local-release.md` 是分版本部署证据索引，不是第二份进度源。
- `goals/implementation-plan.md` 是 W00 至 W08 的原施工分解；带日期 Goal 保存对应范围、检查点和交付，不将旧方案直接用于当前运行。
- `docs/reference/` 和 `wechat-reference.json` 分别保存截图背景和固定协议参考，不能证明本项目已实现。
- 整理前文档的固定提交、章节去向及冲突关闭记录见 [DOC01 报告](validation/documentation-restructure.md)。保留原路径和被引用标题锚点，历史事实可按固定提交追溯，不复制到当前使用入口。

## 维护触发与核对

| 变化 | 同步维护 |
| --- | --- |
| 产品行为／范围 | PRD、命令／专题、追溯；事实变化时同步 README、架构、ROADMAP |
| 模块／进程／数据流 | 架构及图、开发契约、相关 ADR、开发／测试入口 |
| 原生版本／能力门禁 | 协议矩阵、fixture／实现证据、相关使用专题；未测层级保留 |
| schema／快照／保留期 | 账本及身份、运维／回退、迁移测试、验收记录 |
| 安装／命令／发布布局 | README、开发／运维指南、模板、安全说明；先核对真实 CLI |
| 重要验证／正式决策 | 带范围的验证／ADR、追溯、ROADMAP；不复制任务进度到每页 |

每次变更先核对权威页，再按主题查所有消费者，修正后复查例子、图、链接和范围。documents 检查负责机械约束，不能发现全部语义冲突。架构图以 architecture-design 中 Mermaid 为维护源，改变后须实际渲染和视觉检查。

目前不强制新增 CHANGELOG、独立 CONTRIBUTING 或大量 ADR 文件：版本变化由 Git 与发布记录承载，开发协作已有指南，决策集中于现有入口。有独立读者需求时再拆分并保留旧入口。
