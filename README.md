# wx-clawbot

面向本机 iTerm2 Codex 原生会话的微信桥接项目。

当前提供严格的项目配置读取、目录边界校验和只读环境诊断。

## 安装与使用

使用 Python 3.14，在仓库根目录执行：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/wx-clawbot doctor
```

按 [配置模板](config/config.example.json) 准备本机配置，项目 root 使用真实绝对路径，再运行：

```sh
.venv/bin/wx-clawbot doctor --config /absolute/path/to/private/config.json
```

诊断输出只包含版本、配置状态和项目数量；无效配置返回非零状态，不打印配置内容。

## 开发与文档

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q src tests
git diff --check
```

[项目规范](AGENTS.md) · [当前进度与阻塞](ROADMAP.md) · [产品设计](docs/product-design.md) · [架构](docs/architecture-design.md) · [技术决策](docs/technical-decisions.md) · [开发契约](docs/development-contracts.md) · [施工清单](goals/implementation-plan.md)
