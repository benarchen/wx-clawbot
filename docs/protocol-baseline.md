# 协议、依赖与兼容基线

适用应用 0.1.12。这里集中维护原生版本／能力／证据范围，其他页面引用本表；实际部署进度只见 [ROADMAP](../ROADMAP.md)。CLI 版本、daemon 的 initialize 版本、应用版本、SQLite schema 和路由快照不是同一对象。未知 server 版本拒绝，不能仅扩大白名单。

## 当前能力矩阵

“代码准入”表示实现允许对应版本；“schema”表示匹配二进制生成并核对的字段；“真实原生”表示实际连接／任务／交互等指定范围；“手机”只表示本人实际收发或显示。任何一栏都不能自动推出其他栏通过。

| 实际 app-server 版本 | 核心代码／schema 准入 | 真实原生证据范围 | 图片代码／schema 与手机证据 | 结构化异步问题 |
| --- | --- | --- | --- | --- |
| 0.163.0 | 允许，[fixture](../tests/fixtures/codex-contract.json) | 初始 CLI 为此版本，初始 daemon 为 0.164.0；不借 CLI 版本宣称相同 daemon 全动态验收 | 不开放 | 不开放 |
| 0.164.0 | 允许，W01 匹配 schema | [W02](validation/w02.md)、[W03](validation/w03.md)：既有对象、多轮、同步交互及专用队列，TUI 反例保留 | 不开放 | 不开放 |
| 0.165.0 | 允许，[33 份契约比较](validation/codex-0165.json) | IMG01／HOST01 相关原生任务与恢复 | 开放；[IMG01](validation/image-input.md)有单图手机闭环；同消息图文未验收 | 不开放 |
| 0.166.0 | 允许，[36 份比较](validation/codex-0166.json) | [HOST01](validation/host-lifecycle-recovery.md)、[ASK01](validation/async-questions.md)、[ENG01](validation/engineering-hardening.md)各自范围 | 开放；HOST01 2026-10-30 07:43／07:46 有原图唯一 turn 及本人收件，MD01 有单图真实任务 | 仅此版本开放；原生反例、补充模式与手机证据见 ASK01，不承诺首答独占 |
| 0.167.0 | 允许，[38 份比较](validation/codex-0167.json) | [真实冷启动](validation/iterm-cold-start-live.md)、[TGT01](validation/wechat-independent-target.md)、[TGT02](validation/native-session-no-footer.md)：各自身份、选择、创建、恢复范围；[0.1.6 发布](validation/codex-0167-release.md)后核心已交付 | 代码／schema 开放；新版图片手机整链路仍未验收，不借旧版通过填补 | 结构化入口不开放，专项动态验证未完成；核心同步协议准入不等于该能力开放 |
| 0.169.0 | 0.1.12 代码准入，[43 份契约比较](validation/codex-0169.json)，准确 managed 生成 479 份；真实只读握手／目录／额度已过 | 专用 Controller 5 次设置／3 任务及清理、本人微信统一设置／Fast／额度／桌面采用／busy 拒绝／清理及最终展示实收通过；源码纳入 0.1.12，实际运行见 ROADMAP | 本版关闭；不据结构相近开放 | 本版关闭 |

表格表示实际覆盖，没有声称每个已允许版本都重跑全部动态关卡。0.167.0 新增的可选 requiredHumanApproval／humanCommand 未声明支持；音频等新增 schema 字段也不构成本项目能力。图片仍要求当前模型支持，不自动换模型或去图重试。

维护源为 [CodexConnection](../src/wx_clawbot/agents/codex.py) 的 SUPPORTED_SERVER_VERSIONS／image_input 和 [AsyncQuestions](../src/wx_clawbot/async_questions.py) 的独立门禁。协议结构不能推导服务端幂等、两端竞争、显示或手机送达。同步／异步区别见[交互契约](async-questions.md)。

## NCM01：原生命令独立门禁

新控制入口仅允许 0.167.0／0.169.0；0.163 至 0.166 不开放。loaded-only 设置快照、联合 model／effort、Fast、事件加回读、准确任务采用和已知 busy／queued 拒绝分别已有离线及真实证据。0.169.0 的专用原生与本人手机功能验收、桌面后续采用、原设置／B／配置保护及自有终端清理通过；源码纳入 0.1.12，Git 交付与实际运行见 ROADMAP。即时 TUI 旧显示限制保留，不强制刷新；桌面竞争不承诺原子保护，Fast 不证明实际请求档位、提速或计费。

账号额度从同运行时 account/rateLimits/read 取得主次窗口和多桶，只请求 excludeResetCreditDetails=true，不传 Reserve 能力、不切账号或刷新认证；两版只读与本人手机额度实收均有证据。默认 status 按本人要求隐藏内部 token 统计，保留账号范围、未知值与北京时间查询时点；展示优化的同包检查、窄屏渲染及本人微信实收均已完成，分层证据见[专题](native-controls.md)及[0.169.0 记录](validation/codex-0169.md)。

0.169.0 设置读取的生命周期另有[真实验证](validation/native-settings-lifecycle.md)：订阅保持时关闭 TUI 仍 loaded；跨连接归档会卸载，但检查与 resume 之间发生归档时原生明确拒绝恢复。结论仅限已测路径，不扩写成所有版本或所有卸载方式的原子保护。

## 版本与重建

采用 daemon 实际报告的匹配原生可执行文件生成 `app-server generate-json-schema --experimental`，核对全部桥接所用方法和嵌入类型；稳定版另核，原生队列仍是实验接口。生成文件原始摘要与最小字段保存在 fixture／逐版本 JSON，不能把当前网络文档替代版本匹配证据。

重建环境使用 Python 3.14 和 [requirements.lock](../requirements.lock) 的精确哈希；构建后端固定 `setuptools==80.9.0`。开发安装见[开发指南](development.md)，冻结 wheel／manifest 和非 editable 安装见[运维](operations.md#eng01独立运行制品与开发隔离)。升级原生后先看实际版本和安全握手／schema，不自动安装、重启 daemon 或修改用户配置。

## 维护与许可证

下表是当前锁定职责，不是重新完成依赖安全审计；完整直接／传递版本和发行哈希以 lock 为源，许可见[第三方声明](../THIRD_PARTY_NOTICES.md)。

| 依赖 | 必要职责与标准库不足 | 已有审查来源 |
| --- | --- | --- |
| iterm2 2.30；protobuf／websockets 为传递链 | 官方宿主管理协议，标准库不能替代 SDK | W01 历史发布／维护抽样及许可证记录 |
| websockets 17.3 | 原生 Unix WebSocket，亦与 SDK 传递链共用 | W01 固定基线，离线连接契约 |
| segno 1.6.6 | QR 编码，避免自行实现或引入网络生成器 | [微信协议](wechat-protocol.md)中的固定来源与扫码证据 |
| cryptography 50.0.2；cffi／pycparser | 图片 AES 解密，不自写密码算法 | [IMG01](validation/image-input.md)发行、许可和维护抽样 |
| Pillow 13.0.0 | 完整 JPEG／PNG 解码及资源校验，不能只看扩展名 | IMG01；不调用字体功能，不声称完整字体链安全审计 |
| markdown-it-py 4.2.0；mdurl | 确认 Markdown 节点结构、保护代码／链接并分段 | [MD01](validation/wechat-markdown.md)中的选型与格式测试 |

W01 的历史 SDK／依赖样本检查只代表当时证据；新增核心依赖或变更分发形态须重新核对维护、版本和许可，不照搬旧“最新版本”。本项目 MIT 不重授权依赖，iterm2 SDK 的 GPLv2+ 组合分发边界保持。

## 连接与接口边界

native-probe 只读检查 socket 归属／模式／设备 inode、initialize 实际版本与握手；不创建、resume 或执行会话。doctor 的 verified_schema 不能证明任意 TUI 属于这个 daemon。SDK 连接授权也不能证明准确 thread 已可输入。

iTerm2 未运行时后台不反复拉起；显式合法会话命令可按需连接，可见创建须授权及准确握手。既有原生会话可在宿主缺席时复验后继续。身份及预算见[身份契约](native-session-identity.md)，宿主恢复见[运维](operations.md#iterm2-退出按需启动与恢复)。

## 微信参考冻结

腾讯公开参考固定 commit `874637a0dbc24050f72d1385add4fc6170a2d726`，package.json 2.4.10、MIT。W01 六份、W04 消息类型及 IMG01 媒体／AES／CDN 四份，共十一份固定链接与 SHA-256 见[清单](wechat-reference.json)。未 vendor 全部平台，也未访问本机其他桥接项目。逐字段请求与客户端身份见[微信协议](wechat-protocol.md)。

## ASK01：结构化异步补充

准确订阅的 item/completed agentMessage 具有 delivery=async、questions、准确 item／thread／turn 才登记；phase=final_answer 不能替代 turn 终态。通过带 expectedTurnId 和稳定 client 的 turn/steer 进入原活动轮次，原生可能同时接收两端答案。单次提交、冲突与模型采用边界见[异步契约](async-questions.md)。当前门禁只见本页矩阵，不从普通问句猜入口。

## 0.167.0 兼容核验

2026-11-07 匹配 binary 生成 470 份实验 schema，核对 38 份相关契约，与摘要匹配的 0.166.0 样本比较；原始摘要和变化路径见对应 JSON。核心修正经 712 项及真实冷启动后随 0.1.6 交付，后续 TGT02 随 0.1.8 去除 ID 显示依赖。旧“候选未部署”仅是历史时点，专项图片／异步边界仍以矩阵为准。

## 历史采样索引

| 日期／阶段 | 当时范围与局限 |
| --- | --- |
| 2026-10-24 W01 | Python 3.14.5、iTerm2 3.7.6，CLI 0.163.0／daemon 0.164.0；首次 SDK 探测失败后 W02 继续真实验证 |
| 2026-10-28 兼容 0.165.0 | 新可选列表字段及错误类型与原必需字段兼容；只读握手不代表全动态重验 |
| 2026-10-30 兼容 0.166.0 | 467 份生成、36 份核对；图片 schema 先通过，后由 HOST01 补真实图片与本人收件 |
| 2026-11-07 兼容 0.167.0 | 470 份生成、38 份核对；核心／图片 schema／异步专项区分如上 |

原维护抽样链接、完整叙述和当时测试数量保存在[整理前基线](https://github.com/benarchen/wx-clawbot/blob/8278de5645a57f2fc0348b746d59899bfe0bdadd/docs/protocol-baseline.md)及各阶段证据；本次文档整理没有重新连接或执行原生任务。

## 0.169.0 衔接核验

会话列表指定 currentAccountOnly=true／includeAttachedThreads=false，准确读取拒绝 attached 对象；模型目录的 modelProvider 使用已选原生 provider，未指定的目录查询保持运行时默认。新增结果 moderation／display 指令保守提示由原生客户端处理，不能直接透传正文；可选 environments／responsesapiClientMetadata 不发送，不管理新环境或元数据。图片和异步仍按本版门禁关闭。完整范围、失败记录及具体动态操作卡见 [0.169.0 记录](validation/codex-0169.md)。
