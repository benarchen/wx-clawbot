# W01 协议与依赖证据

## 版本与重建

2026-10-24 现场：Python 3.14.5、iTerm2 3.7.6；CLI 0.163.0，已运行 daemon 0.164.0。不自动升级、重启或修改 Codex 配置。协议分别由本机两个对应版本的 `app-server generate-json-schema --experimental` 生成；最小字段与原始摘要保存在 [契约 fixture](../tests/fixtures/codex-contract.json)。稳定版 schema 另行生成核对，队列属于实验接口。

2026-10-28 08:01 兼容扩展：现场 CLI 为 0.164.0，既有 daemon 为 0.165.0。原版本校验在 initialize 后拒绝连接，doctor 显示 `verified_schema: false`；已使用匹配 daemon 的本机可执行文件生成实验 schema，与原 0.164.0 基线逐项比较桥接所用的 33 份定义及其嵌入类型。除说明文字外，差异仅为可选 `attachedToThreadId` 列表过滤字段和 `CodexErrorInfo` 新增 `modelNotFound`，已有请求必需字段、队列关联、审批／追问与终态结构兼容；桥接不传新过滤字段，错误继续使用通用渲染。各文件原始摘要及差异见[对比记录](validation/codex-0165.json)。已补充 0.165.0 基线并保留未知版本拒绝；真实只读握手与 doctor 成功，323 项离线测试通过。未升级、重启 daemon 或修改全局配置；这不是新版全部动态关卡重新验收。

2026-10-30 07:29 现场再次出现新运行时 `0.166.0`：初始化被旧版本门禁准确拒绝。使用匹配的本机官方可执行文件生成 467 份实验 schema，核对桥接所用 33 份及本次设置／后台资源检查 3 份，共 36 份；差异仅为新增错误类型、可选条目时间／图片生成 ID 和上下文名称，已有必需字段不变。[逐字段记录](validation/codex-0166.json)。新增版本握手回归先失败，兼容后 451 项全套通过，未知版本仍拒绝。另核对 UserInput／TextElement／ImageDetail 与 input 结构均未变化，补齐 `0.166.0` 图片准入后 451 项回归再次通过；新版图片真机烟测待完成，不据 schema 冒充通过。现场原线程及旧追问处理记录见 [HOST01](validation/host-lifecycle-recovery.md)。

运行依赖固定为 iterm2 2.30、protobuf 7.36.2、websockets 17.3，含全部发行文件哈希的 [锁文件](../requirements.lock)。第二个隔离虚拟环境使用 `pip install --require-hashes -r requirements.lock` 重建并成功导入全部依赖。构建依赖 setuptools 80.9.0 固定在 pyproject.toml，不进入服务运行链。

iterm2 提供系统终端管理能力，标准库不能替代其宿主协议；protobuf 与 websockets 是 SDK 声明的传递依赖。未添加额外 HTTP、ORM 或测试框架。

## 维护与许可证

IMG01 新增 cryptography 50.0.2、Pillow 13.0.0，及哈希锁定的 cffi／pycparser。标准库和现有依赖缺少 AES 与完整 JPEG／PNG 解码，因此不自写密码算法或只凭扩展名接收。发行、许可、Python 3.14、维护回应及已知限制核查见 [IMG01 证据](validation/image-input.md)。Pillow 仅开放 JPEG／PNG Image.open 与解码，不调用 ImageFont／FreeType；已知字体依赖问题保留，不称完整安全审计。

当前图片准入为 0.165.0／0.166.0，前者已有 IMG01 真机证据，后者的现场验证见 HOST01 记录；模型支持以原生实际结果为准；其他已支持版本保持文本范围，未知版本拒绝。原生 inline image 使接收帧扩展为有界 16 MiB，事件字节及分页限制见 [运维](operations.md)；图片手机整链路不能由 schema 或离线测试替代。

- iterm2：PyPI 2.30 发布于 2026-10-12；源码仓库在 2026-10-24 有提交。抽样 issue #797 于 10 月 16 日创建，维护者 gnachman 于 10 月 23 日回复并关闭；样本只能说明近期活动，不能保证响应质量。[发行与许可证](https://pypi.org/project/iterm2/)、[源码快照](https://github.com/gnachman/iTerm2/commit/0139844e77721d2d5e1412a946d9ce9b0f8d260e)、[issue](https://github.com/gnachman/iTerm2/issues/797)。SDK 声明 GPLv2+；本项目自有代码和文档现采用 [MIT](../LICENSE)，依赖原授权与组合发行边界见[第三方声明](../THIRD_PARTY_NOTICES.md)，不据项目 MIT 声明推定完整产品可闭源发行。
- protobuf：安装包声明 3-Clause BSD，2026-10-24 仍有[维护提交](https://github.com/protocolbuffers/protobuf/commit/1d3458ec804bc5a9fc177952fdab12735db8e15f)；websockets 声明 BSD-3-Clause，2026-10-22 有[维护提交](https://github.com/python-websockets/websockets/commit/60bc20095093a5f7e6083640db5ffd56f1378da6)。许可证以安装发行元数据核对，未声称完成安全审计。

## 连接与接口边界

只读真实 SDK 连接尝试返回 OSError，IPv4／IPv6 localhost:1912 均拒绝连接。没有读取终端正文、发送输入或改设置。需核对 iTerm2 Settings → General → Magic → Enable Python API server，并允许项目脚本授权；启用后重新执行 `wx-clawbot doctor --iterm2`。[SDK 设置依据](https://pypi.org/project/iterm2/)。

daemon version 真实查询成功。CLI 与 daemon 不同版本不能混为同一协议基线；后续连接校验实际 initialize 结果和所用字段，发现不支持时明确拒绝。

[官方 App Server 文档](https://learn.chatgpt.com/docs/app-server) 是接口入口，本阶段只证明生成的字段存在。原终端、共享交互、队列行为仍须 V01 至 V04 真实验证，不能据 schema 宣称通过。

## 微信参考冻结

腾讯公开参考固定在 commit `874637a0dbc24050f72d1385add4fc6170a2d726`，package.json 版本 2.4.10、MIT。W01 核对协议、API、登录、发送、package 与 LICENSE 六份文件，W04 补充消息类型；IMG01 再补充同一 commit 的媒体下载、图片解密、AES 和 CDN URL 四份，共十一份固定链接及 SHA-256 见 [参考清单](wechat-reference.json)。未 vendor 源码或安装其 OpenClaw 依赖，也未读取本机其他项目。实际字段选择、独立客户端标识与扫码展示依赖见 [微信通道协议](wechat-protocol.md)，真实联调进度只见 ROADMAP。

## ASK01：结构化异步补充

现场 0.166.0 的 agentMessage 在 item/completed 携带 delivery=async、questions 和准确 item／thread／turn；phase=final_answer 不能代替 turn 终态。TurnSteerParams 使用 expectedTurnId、稳定 clientUserMessageId 和 text input，答案为第二条 userMessage。该能力仅对实证 0.166.0 开启，其他已支持版本的核心队列／同步交互不受影响。

467 份本机官方 schema、原始 ClientRequest 摘要、单题／自由／多题／连续问题、连接失效、中断和两个相反答案均接收的反例见[验证记录](validation/async-questions.md)。当前原语没有问题级首答独占或异步 resolved；桥接不伪造该语义。最终候选真实原生闭环与 fake 微信／本地 Unix 测试分别记录，不混同手机实收。

## 0.167.0 兼容核验

2026-11-07 本机 daemon／managed executable 均为 0.167.0。依据[官方版本匹配 schema 说明](https://learn.chatgpt.com/docs/app-server)，用该可执行文件生成 470 份实验 schema，对照原有摘要匹配的 0.166.0 样本，核对 38 份桥接相关契约；[逐字段记录](validation/codex-0167.json)保存两侧摘要和变化路径。新增可选 requiredHumanApproval／humanCommand 未声明支持、不启用；音频文件引用扩展不影响既有文字／图片输入。原有必需字段、队列／历史及同步交互接口保持，未知版本仍拒绝。

开发候选新增 0.167.0 握手和图片 schema 准入；这不等同于新版图片手机验收。异步问题继续只对实证 0.166.0 开放，0.167.0 尚未完成异步动态验收，保留门禁。真实冷启动结果与候选交付状态后续单列，不升级／重启 daemon 或改全局配置。

2026-11-07 07:40：0.167.0 连接回归先失败后通过，712 项全量与隔离候选真实冷启动已通过，一条命令创建一次、准确原生身份及启动终态核验成功；[复测记录](validation/iterm-cold-start-live.md)。本轮未部署生产兼容版，异步和新版图片手机验证边界保持。
