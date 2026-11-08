# 开发指南

面向接手当前 MVP 的开发者。先读 [AGENTS](../AGENTS.md)、[ROADMAP](../ROADMAP.md)、[README](../README.md)，再读[架构](architecture-design.md)、[开发契约](development-contracts.md)及本次改动的专题。规范和权限只在 AGENTS 维护，本页不追加提交或发布授权。

## 环境与安装

使用 macOS、Python 3.14 和 Git。项目元数据要求 `>=3.14,<3.15`，运行依赖固定于 [pyproject.toml](../pyproject.toml)和含完整哈希的 [requirements.lock](../requirements.lock)。在仓库根：

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m pip check
.venv/bin/wx-clawbot --help
```

editable 仅用于开发；正式制品不依赖开发路径。构建后端精确版本为 setuptools 80.9.0；需要构建时在项目 venv 安装，不全局安装。不要只改版本范围或绕过哈希锁解决兼容问题。环境无法联网时保留安装未验证，不能用已有包冒充重建。

离线单元／文档检查不要求登录微信或启动原生任务。真实宿主／Codex 测试另需已核验版本、本人授权和专用资源；不为跑普通检查打开用户应用。

## 目录与阅读地图

| 路径 | 用途与阅读入口 |
| --- | --- |
| `src/wx_clawbot/cli.py`、`__main__.py` | argparse 入口，先看 help 与参数默认值 |
| `service.py`、`runtime_lifecycle.py`、`managed.py` | 单桥接进程、依赖恢复与日志／托管入口 |
| `commands.py`、`config.py`、`routing.py`、`controller.py` | 纯解析、目录校验、快照及选择事务 |
| `catalog.py`、`sessions.py`、`subscriptions.py` | 有界原生发现、准确身份与引用式订阅 |
| `agents/`、`hosts/`、`launcher.py` | 原生协议／队列与 iTerm2 生命周期／可见握手 |
| `execution.py`、`admission*.py`、`results.py` | 派发、仓库准入、结果／占用恢复、结果工作槽位 |
| `runtime_state.py`、`schema.py`、`occupancy.py`、`async_state.py` | 同一 SQLite 执行器下的事务及状态 |
| `channels/`、`images.py`、`image_files.py` | HTTPS、本人绑定、媒体和私有附件 |
| `interactions.py`、`async_questions.py` | 同步决定与异步补充，不能混用语义 |
| `output.py`、`render_worker.py`、`delivery.py`、`release.py` | 结果展示、冻结投递及父子制品来源 |
| `tests/test_*.py`、`tests/fixtures/` | unittest、最小 schema／SQL／格式样本 |
| `tests/integration/` | 显式合成负载、冻结制品和真实原生入口；名字不决定是否可自动执行 |
| `scripts/`、`config/` | 离线检查／制品准备，无身份模板 |
| `docs/`、`goals/`、`.tmp/<task>/` | 正式主题文档、施工与证据、被忽略的临时资料 |

完整职责关系见架构 F03；不要因目录表未列所有辅助文件而将其判为死代码。

## 从改动到验证

1. 先定义可观察行为、范围、失败路径和验证方式。产品／架构新方向按授权规则处理；修复默认保持其他外部行为。
2. 从现有测试寻找最小复现和拒绝路径。路由优先看 independent_target／native_identity／native_target_lifecycle，恢复看 recovery_state／admission_recovery，通道看 wechat_*，格式看 markdown_*。
3. 用现有标准库／依赖和直接职责实现，补充有价值的边界回归；不为一次性情况扩通用框架，不把业务消息放 fixture。
4. 按[测试指南](testing.md)运行相关检查和项目必要离线检查。涉及原生语义先保留静态／离线结论，再显式安排真实关卡，不能以 fake 通过结案。
5. 同步受影响的产品、技术、架构图、追溯和 ROADMAP；按[维护触发](README.md#维护触发与核对)核对其他消费者。提交前检查公开内容；只有明确要求提交才 add／commit。

## 合成数据与调试

使用 `tempfile` 或项目 `.tmp/<task>/` 下新建的合成状态根、测试 Credentials 和 fake 原生／微信对象。参考现有 tests 的 setUp／asyncSetUp，不将生产库复制进测试、不读取私人对话凑样本。对实际 ledger 的 `RuntimeState.open` 可能恢复写状态，不能作为“只读预检”。

单文件回归使用 discover，避免假设 tests 是可导入包：

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_independent_target.py' -v
```

调试记录准确失败位置、预期／实际、源码基线和安全分类。异步竞态用可控事件／fake 时钟，检查任务未重发、冻结目标未变和资源确实回收；不要靠更长 sleep 隐藏竞态。数据、RPC 及 HTTP 意图持久化和完成分开核对。

## 常见接手问题

| 情况 | 处理 |
| --- | --- |
| Python 版本被拒绝 | 使用项目要求的 3.14，不随意放宽 requires-python |
| 子进程导入不同包 | 正式环境核 manifest 与 `python -I` 实际加载；不能靠 PYTHONPATH 修补生产 |
| 新 daemon 连接被拒绝 | 读取真实版本并生成匹配 schema，逐能力核验；不只增加支持列表 |
| 单元测试通过但界面不符 | 原生、API、手机显示／复制分开取证，查对应真实关卡 |
| 提交未知或 case 已有意图 | 只读 report／准确对账，不删除 case 或重跑旧输入 |
| 文档链接通过仍矛盾 | 按共同事实台账逐主题核所有现行消费者，不能只搜索版本字符串 |

## 构建与协作入口

统一离线入口 `.venv/bin/python scripts/check.py`，结果仅放 `.tmp/check/`。构建 `scripts/build_release.py` 默认计划，`--apply` 才写全新制品目录；冻结安装与实际切换见[运维](operations.md#eng01独立运行制品与开发隔离)。无自动发布流水线承诺，不因构建成功自行 push／tag／部署。

分支、中文 commit、规范与真实测试纪律见 AGENTS；安全和依赖变更见 [SECURITY](../SECURITY.md)。本页与测试指南已承担开发贡献说明，无需另建空的 CONTRIBUTING。
