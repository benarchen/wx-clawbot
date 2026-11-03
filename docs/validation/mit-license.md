# MIT 许可落实与发行核对

状态：2026-11-03 09:49 本地许可文件、制品与基础验证通过；尚未提交、合并、推送或发布新版本。运行版本仍为 0.1.1，本次未修改运行代码、依赖锁、服务配置或真实账本。

## 授权决定与范围

本人明确选择 MIT，并授权落实许可证、包元数据、第三方清单、文档和构建验证。根目录 [LICENSE](../../LICENSE) 授权本项目自有代码及文档，版权年份为 2026，公开署名沿用本仓库唯一 Git 提交作者 `benarchen`。该署名不转移第三方版权，也不将依赖及参考实现重新授权为 MIT。

本次未获得 Git 提交、分支合并、推送、创建标签或公开发布的新指令；本地许可声明从包含本次 LICENSE 的工作区版本起附带，未移动 v0.1.1 标签或重写历史。现有历史制品没有通过本次本地改动自动增加许可文件。

## 核查依据

- [MIT 标准条款](https://opensource.org/license/mit)：使用完整英文标准文本，只替换版权年份与署名，不增加使用限制。
- [PyPA 许可证元数据指南](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license-and-license-files)与[制品示例](https://packaging.python.org/en/latest/guides/licensing-examples-and-user-scenarios/)：声明 SPDX `MIT` 与实际随包的 LICENSE、THIRD_PARTY_NOTICES.md。构建后端 setuptools 80.9.0 支持该格式。
- 逐项读取 requirements.lock 固定的 10 个运行发行包元数据及其自带许可文本；未只按 PyPI classifier 推断全部条款。详细清单、内嵌组件及再分发要求见 [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)。
- 项目 Git 提交作者去重为 `benarchen`；项目声明的腾讯协议参考未 vendor 实现，保留固定 commit 及原许可入口。核对不等于替第三方作者重新作授权决定。

## SDK 的实际证据与保留边界

| 证据 | 结果 |
| --- | --- |
| PyPI iterm2 2.30 源码包 | SHA-256 为 `eaa814b64f11d58984dfa02e790016983e7c4eb4f41cceae174ba361708200ec`，与官方元数据及项目锁一致 |
| 源码包结构 | 70 个归档条目；含 README.rst，但没有名为 LICENSE／COPYING／NOTICE 的文件，已安装发行包也没有独立许可文件 |
| setup.py | 写明 `GPLv2` 和 GPLv2+ classifier；与固定源码 commit `0139844e77721d2d5e1412a946d9ce9b0f8d260e` 的 SDK setup.py 完全相同，文件 SHA-256 为 `9dbef2d0268c30e8b11689174b143580ed6df550326f8c4174d32327e7c8128f` |
| 上游根目录 LICENSE | GPLv2 全文，SHA-256 为 `990f1da86e9f58355fc82b5cd486b70aaeb53ae0ba9722424a0270ff0d458de9` |
| 上游根目录 COPYING | 说明 GPLv2 或更高版本及 iTerm2 应用的 Apache 依赖约束；SHA-256 为 `e8623589e5af3639c9725d7b3307c726c0e4428684d3c5a3c0f5fbdd98be8efd` |
| 检查到的专用授权 | 上述发行声明和根目录许可未提供可据以宣布本次 SDK 集成豁免 GPL 的例外；未取得维护者额外授权 |
| 项目实际结合方式 | 多个宿主模块直接导入 SDK 及其子模块；本次未替换 SDK，也未改变宿主架构 |

官方来源：[PyPI 2.30](https://pypi.org/project/iterm2/2.30/)、[SDK setup.py](https://github.com/gnachman/iTerm2/blob/0139844e77721d2d5e1412a946d9ce9b0f8d260e/api/library/python/iterm2/setup.py)、[LICENSE](https://github.com/gnachman/iTerm2/blob/0139844e77721d2d5e1412a946d9ce9b0f8d260e/LICENSE)、[COPYING](https://github.com/gnachman/iTerm2/blob/0139844e77721d2d5e1412a946d9ce9b0f8d260e/COPYING)。GitHub API 查询曾受匿名限流，后通过 raw 官方固定链接和 SHA-256 匹配的 PyPI 原包完成核对，未把失败请求计为有效证据。

MIT 与 GPL 依赖并存不表示自有作品不能采用 MIT；但自有 MIT 不能消除组合发行可能适用的 GPL 义务。本轮交付完成的是自有作品授权与准确披露，不是对完整组合产品闭源再发行的许可保证。若需要这种保证，应先解决额外授权或替代实现，并按实际交付形态复核。

## 验证与交付

隔离构建使用本次任务临时目录，未重写日常 editable 安装的元数据。以下检查已实际完成，机器摘要与原始许可文件摘要见 [mit-license.json](mit-license.json)。本地构建仅供验证，不作为对旧版本制品的覆盖发布。

- 580 项完整离线回归通过，35.976 秒；本地 Unix socket 用例获准后实际执行，没有跳过。编译、pip check 与 git diff --check 通过。
- 独立构建环境仅安装已固定的 setuptools 80.9.0，其元数据声明 MIT；依次调用 build_sdist 与 build_wheel。两个制品均为 Metadata-Version 2.4、License-Expression MIT，License-File 精确为 LICENSE 与 THIRD_PARTY_NOTICES.md，六个直接依赖保持。
- 源码包和 wheel 中的 LICENSE、THIRD_PARTY_NOTICES.md 与工作区原文逐字相同；wheel 在独立目标目录无依赖安装，隔离解释器确认包来自该目标且可读取 MIT 元数据及原始许可证。
- 两个制品中的 54 个 Python 源码模块与工作区逐字相同；git 核对 src、tests、requirements.lock 均未改动。制品无内置运行依赖、虚拟环境、任务临时目录、真实配置、数据库或日志。
- 10 个锁定运行发行包的许可元数据已核对，其中 9 个包共 12 份许可文件记录 SHA-256；iterm2 缺少独立许可文件的事实保留，不把缺失当作 MIT 或无约束。
- 自有 MIT 文本、README、AGENTS、协议基线及 REC01 后续说明一致；ROADMAP 将本地许可落实与组合发行待确认边界分别记录，不改写原验收历史。未操作微信 UI、发送测试消息、创建原生任务或重启服务。

源码包 SHA-256：`8dbe2fe7159b861b7e06b0ad0a55e900f35bdff4272388370d66a6da94fb7e22`；wheel SHA-256：`7d1dd52d6bb31e955ccf9dddd118a48e2522952da0f496c7988fbfd7dbe3f756`。这些值标识本轮本地验证制品，不是 v0.1.1 已公开制品的替代声明。

## 0.1.2 版本归档

此前本地许可落实的结果已纳入本人本轮明确授权的 0.1.2 提交／推送／标签范围，原许可证文本和第三方边界保持。实际 Git 结果见 [0.1.2 发布记录](ask01-publication.md)；本文件上方 09:49 记录保留当时的验证范围，不代替后续发布事实。
