# wx-clawbot 项目规范

## 定位与边界

本项目通过微信操作本机多个项目中的 iTerm2 Codex 原生会话。继承环境生效的全局规范；此处只维护项目特有规则。首版使用 Python、asyncio、iTerm2 官方 SDK、Codex 原生协议与标准库 SQLite。

- 已有终端持续运行，桥接必须连接同一运行时和 native thread；禁止复制历史、另开后台会话或伪造成功回执替代接入。
- 不读取、参考、复用或修改 openclaw-local 的代码、配置、凭据和服务；两项目完全独立。
- 桥接程序不自动修改 Codex 全局配置、认证、Skills、插件或模型。本次初始化仅获准新增 wx-clawbot 根目录的 `trust_level = "trusted"`，其余全局配置保持不变；证据见 W02 施工记录。真实测试仅使用专用终端，先用两个临时项目，再按授权在 guixu 与本项目执行只读验收。
- 首版只实现 Codex；不提前建设 Web UI、云服务、多用户、群聊、媒体或多 Agent 编排。

## 结构与文档权威

- `src/wx_clawbot/`：按实际职责逐步增加 CLI、宿主、Agent、通道与状态模块，不创建无行为的框架层。
- `tests/`：离线单元与契约测试；真实接口测试显式执行，不自动操作微信或用户终端。`tests/fixtures/` 仅放脱敏的最小协议样本。
- `config/`：无身份、无密钥的模板；真实配置与数据在用户指定的私有运行目录。
- `docs/`：设计、接口证据与使用说明；`docs/reference/` 为未独立验证的截图参考。
- `goals/implementation-plan.md`：W00 至 W08 的依赖、范围和验收要求；带时间文件保存每个 Goal 的施工定义与交付证据。
- `.tmp/<task-slug>/`：本次任务的临时数据，不作为正式实现或文档依赖。
- 本文件是项目规则唯一内容源；[产品设计](docs/product-design.md) 定义 P01 至 P14，[开发契约](docs/development-contracts.md) 定义 V00 至 V08。[README](README.md) 只写真实能力和使用方法；[ROADMAP](ROADMAP.md) 是唯一进度源。

## 工作流与验证

- 分支采用 `dev`／`main`：经核验的最小工程基线可先落在 `main`，实现与阶段提交在 `dev`；完整首版验收后合并至 `main`，再推送两个分支。未验收实现不直接进入 `main`。
- 同时只执行一个 Goal，先保存目标、边界、检查点、关键失败路径和验收方法，再创建原生 Goal；交付并通过对应关卡后才能完成。默认不委派。
- 核心动态关卡必须真实执行，模拟测试不能替代 V01 至 V08；W02、W03 未通过不扩大核心功能建设。
- 排队与交互以原生运行时为裁决点。未知执行状态不自动重放；投递重试不能重新执行任务。`/attach` 与 `/detach` 的体验在明确契约前保持未定状态，不假装成功。
- 项目内使用 `.venv` 和精确依赖锁。基础验证入口为 `.venv/bin/python -m unittest discover -s tests -v`、`.venv/bin/python -m compileall -q src tests`、`git diff --check`；检查测试数量非零。真实接口验证记录版本、步骤、实际结果及脱敏证据。
- 每次提交前同步受影响文档、运行必要验证并检查公开内容。真实配置、密钥、身份、消息、数据库、日志、会话和私人路径不得进入提交或历史。
