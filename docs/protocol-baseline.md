# W01 协议与依赖证据

## 版本与重建

2026-10-24 现场：Python 3.14.5、iTerm2 3.7.6；CLI 0.163.0，已运行 daemon 0.164.0。不自动升级、重启或修改 Codex 配置。协议分别由本机两个对应版本的 `app-server generate-json-schema --experimental` 生成；最小字段与原始摘要保存在 [契约 fixture](../tests/fixtures/codex-contract.json)。稳定版 schema 另行生成核对，队列属于实验接口。

运行依赖固定为 iterm2 2.30、protobuf 7.36.2、websockets 17.3，含全部发行文件哈希的 [锁文件](../requirements.lock)。第二个隔离虚拟环境使用 `pip install --require-hashes -r requirements.lock` 重建并成功导入全部依赖。构建依赖 setuptools 80.9.0 固定在 pyproject.toml，不进入服务运行链。

iterm2 提供系统终端管理能力，标准库不能替代其宿主协议；protobuf 与 websockets 是 SDK 声明的传递依赖。未添加额外 HTTP、ORM 或测试框架。

## 维护与许可证

- iterm2：PyPI 2.30 发布于 2026-10-12；源码仓库在 2026-10-24 有提交。抽样 issue #797 于 10 月 16 日创建，维护者 gnachman 于 10 月 23 日回复并关闭；样本只能说明近期活动，不能保证响应质量。[发行与许可证](https://pypi.org/project/iterm2/)、[源码快照](https://github.com/gnachman/iTerm2/commit/0139844e77721d2d5e1412a946d9ce9b0f8d260e)、[issue](https://github.com/gnachman/iTerm2/issues/797)。SDK 声明 GPLv2+，本项目尚未选择发行许可证，不作法律兼容性结论。
- protobuf：安装包声明 3-Clause BSD，2026-10-24 仍有[维护提交](https://github.com/protocolbuffers/protobuf/commit/1d3458ec804bc5a9fc177952fdab12735db8e15f)；websockets 声明 BSD-3-Clause，2026-10-22 有[维护提交](https://github.com/python-websockets/websockets/commit/60bc20095093a5f7e6083640db5ffd56f1378da6)。许可证以安装发行元数据核对，未声称完成安全审计。

## 连接与接口边界

只读真实 SDK 连接尝试返回 OSError，IPv4／IPv6 localhost:1912 均拒绝连接。没有读取终端正文、发送输入或改设置。需核对 iTerm2 Settings → General → Magic → Enable Python API server，并允许项目脚本授权；启用后重新执行 `wx-clawbot doctor --iterm2`。[SDK 设置依据](https://pypi.org/project/iterm2/)。

daemon version 真实查询成功。CLI 与 daemon 不同版本不能混为同一协议基线；后续连接校验实际 initialize 结果和所用字段，发现不支持时明确拒绝。

[官方 App Server 文档](https://learn.chatgpt.com/docs/app-server) 是接口入口，本阶段只证明生成的字段存在。原终端、共享交互、队列行为仍须 V01 至 V04 真实验证，不能据 schema 宣称通过。

## 微信参考冻结

腾讯公开参考固定在 commit `874637a0dbc24050f72d1385add4fc6170a2d726`，package.json 版本 2.4.10、MIT。W01 核对协议、API、登录、发送、package 与 LICENSE 六份文件，W04 补充同一 commit 的消息类型定义，共七份固定链接及 SHA-256 见 [参考清单](wechat-reference.json)。未 vendor 源码或安装其 OpenClaw 依赖，也未读取本机其他项目。实际字段选择、独立客户端标识与扫码展示依赖见 [微信通道协议](wechat-protocol.md)，真实联调进度只见 ROADMAP。
