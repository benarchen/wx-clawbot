# 项目管理：PRJ01 契约与实现设计

状态：本能力已随 0.1.11 公开发布并本机加载；835 项离线、专用原生、本人手机及真实忙碌保护验收通过，原项目注册配置保持。发布与实际加载见[0.1.11 交付](validation/project-management-release.md)，工程与手机证据见[验证记录](validation/project-management.md)，进度见 [ROADMAP](../ROADMAP.md)。范围与验收编号以[施工清单](../goals/20261108-2048-project-management.md)为准。

## 命令与产品边界

本机 `wx-clawbot project init --root <目录>` 只预览第一层候选，输出确认摘要；同一命令加 `--apply --confirm <摘要>` 才登记。既有项保留，不在启动／查询／重连时扫描；设置总目录不等于注册整个总目录，不创建目录或会话。禁止目录（含大小写变体）先排除，链接只准落在总目录真实直接子层，不递归或读取项目内容。初始化确认十分钟有效，绑定当前配置摘要及候选路径身份。

本机 `wx-clawbot project list/add/remove/check` 与本人微信 `/project`、`/project list/add/remove/check` 共用服务；`/projects` 兼容 list。add 参数为目录名，含空格用引号，可用 `--alias` 明确合法别名；remove 只按别名。目录名不符合现有 ASCII 别名规则时不自动改名。初始化只在本机提供；后续新增也限总目录直接子目录。旧格式已登记的外部项目保留，暂不支持多个总目录、换根、重命名或 force。

list 只显示注册目录及可访问状态；check 只检查注册和目录问题，不能替代 doctor／工程测试或原生接入验证。`check --request <请求 ID>` 核对最近管理请求记录，避免把未知写结果当作失败重做。本机支持明确的 `--config`／`--state-dir`；与活跃实例不匹配时拒绝，不能悄悄写另一文件。

微信列表展示约定：`/project`、`/project list` 和 `/projects` 使用紧凑列表，标题含项目数，项目名加粗且每项一行，不添加会话序号。已设置的总目录只显示一次；项目准确目录等于「总目录／项目别名」且可访问时省略重复路径和正常状态，否则补充完整路径，异常项注明目录不可访问。未初始化的旧清单不推测总目录，各项保留完整路径。空清单明确提示，非空清单提示使用 `/cd 项目名`；超长列表按完整项目分组，避免整个长段落触发渲染器片段保护；`/project check` 保留逐项完整路径、状态和请求诊断。本机 CLI 的结构化 JSON 保持不变。此展示优化的发布状态见 ROADMAP，不能仅凭文档更新认定日常实例已经切换。

remove 在该项目有输入目标、观察、已接收／预留任务、选择／可见创建意图、未结交互或等待／持有占用时拒绝。未选中的空闲原生会话和无活动占用的历史 unknown 不永久阻塞；保留历史账本、对账及回执。成功后旧会话列表失效，清除该项目已知目录及 cwd 的选择资格，不改投其他项目；重新注册不恢复旧授权。零项目时管理与微信通道可用，会话操作明确提示。

## 配置与写入协议

旧格式示例保留在[原模板](../config/config.example.json)，新格式示例见[注册模板](../config/project-registry.example.json)。推荐让 init 生成新配置及请求记录，不手工填修订。旧版 0.1.10 不能使用新模板；制品版本和源码摘要须分别核对。

单份配置为注册权威来源。兼容旧 `{"projects":[...]}`，新格式采用 `version:1`、`workspace_root`、`revision`、`projects` 和最近 `operations`；不迁移 SQLite。旧格式启动不自动写；不存在的配置只有显式 init apply 可以创建。新格式容许零项目及失效目录，失效通过 list／check 呈现，派发仍严格核验真实路径。别名和真实目录唯一，拒绝重复 JSON 键与未知字段。

资源边界：配置至多 64 KiB、256 个注册项目，初始化至多枚举 1024 个直接目录项；超过上限拒绝完整导入，不静默截断。最近已提交管理变更保留 128 个摘要，含请求 ID、参数指纹、提交修订及取消注册的别名，不存微信正文或身份。路由快照另记 registry_revision；恢复时按取消修订撤销旧选择／受管偏好，避免取消后重新注册复活旧授权。缺少足够历史时保守拒绝恢复，不猜测。预览摘要绑定生成时刻、原配置摘要、总目录与候选 inode／路径状态；十分钟过期或任何身份变化拒绝提交。

写入在私有项目锁内核对当前文件摘要，先保存 0600 原配置备份，再用同目录临时文件刷新、原子替换并刷新目录。注册服务只在准确新文件落盘后同步安装运行快照；安装失败则关闭新派发资格，尝试从已提交清单收敛，无法收敛时令实例正常失败退出，不自动恢复旧文件覆盖后续变更。回执失败不回滚已提交注册，超时返回结果待核对及请求 ID，不自动重放。连接关闭阶段的预期 BrokenPipe／连接重置不覆盖原操作结果或原异常；文件和账本失败仍保持明确失败／未知语义。

任意手工编辑不在热加载协议内：检测摘要变化后拒绝覆盖，按运维停服、校验再启动处理。新格式不被旧 0.1.10 解析；回退前须评估当前清单并显式转换兼容配置，不能把旧备份直接覆盖当恢复，更不能恢复旧库清理占用。

## 双端协调、锁与运行快照

运行时由准确桥接实例处理所有变更；本机通过私有 Unix socket 提交同一协议，微信直接调用同一服务。仅当前 UID、0700 状态根、0600 socket 和准确实例代次／配置摘要可接入；不监听网络，不提供 Shell／任意文件操作。单请求／响应至多 64 KiB、连接超时 5 秒、运行请求 30 秒、并发连接最多 16；迟到结果不自动重试。客户端超时或消费者忙但实例不可核验时拒绝直接文件写入。

停止时 CLI 持私有项目锁并取得消费者锁，锁内重验无实例后操作；服务启动在同一项目锁内取得消费者锁及加载配置，随后释放项目锁。运行变更锁序为注册服务 gate → runtime.transition → controller.changes；文件锁只覆盖提交段，不跨网络 await。已有会话操作使用 gate 与修订检查，receive 阶段保留项目引用，防止 remove 穿过已接收意图；任务一旦持久化，由账本／占用接替保护。

运行快照安装同步更新 BridgeRuntime、当前控制器的 Routes／SessionCatalog 及下次离线重建的来源，保留其他项目目标和订阅。注册变更令旧会话列表及旧 prepare 修订失效；恢复不沿用原构造参数。native／宿主离线也可管理，但不能忽略账本引用。原生事件／历史核验只保留其原身份，不借历史资格授予新路由。

## 失败与验收

预览、参数校验、冲突、备份及写入失败均不能声称已生效；提交后回执丢失与提交前失败分列。IPC／启动／并发写入用真实隔离进程与本地 socket 验证，派发竞争及崩溃窗口注入失败验证；详见 T01 至 T34、A01 至 A15。真实原生和手机范围分别验收，未完成时不声明 Goal 完成或日常可用。

项目列表各项使用独立段落，避免微信客户端折叠 Markdown 硬换行；正常项目仍只列名称，例外详情就近补充。真人实收结果与适用候选见 ROADMAP。

## 使用与故障核对

本机使用 0.1.11 或后续兼容制品对应的准确解释器／CLI；以下路径均为占位，实际执行不省略 config 与 state-dir，避免操作另一实例：

```sh
wx-clawbot project init --root /absolute/path/to/projects --config /absolute/path/to/private/config.json --state-dir /absolute/path/to/private
wx-clawbot project init --root /absolute/path/to/projects --apply --confirm EXACT_PREVIEW_TOKEN --config /absolute/path/to/private/config.json --state-dir /absolute/path/to/private
wx-clawbot project add "sample app" --alias sample-app --config /absolute/path/to/private/config.json --state-dir /absolute/path/to/private
wx-clawbot project list --config /absolute/path/to/private/config.json --state-dir /absolute/path/to/private
wx-clawbot project check --request EXACT_REQUEST_ID --config /absolute/path/to/private/config.json --state-dir /absolute/path/to/private
wx-clawbot project remove sample-app --config /absolute/path/to/private/config.json --state-dir /absolute/path/to/private
```

CLI 输出结构化 JSON。微信的 `/project` 和 `/project list` 显示简短列表，`/project add "sample app" --alias sample-app` 成功后即可查询；注册并不自动选择会话。可见创建仍显式使用 `/cd sample-app`，输入与观察仍用原有 `/focus`／`/attach`。取消注册被阻塞时先按提示正常 unfocus／detach 或等待任务终态，不能直接删库或备份回滚清占用。

配置／目录变动后确认失效就重新预览；写结果未知则用回执中的请求 ID 查询最近记录和当前清单。查询、预览及未产生变更的结果不新增提交记录；记录超出最近 128 项时只能说明本窗口无记录，不能认定从未执行。磁盘／备份失败时保留诊断，核对原文件摘要；外部手改不自动覆盖。持久化后不能安装运行态且恢复失败时，监督协程令桥接失败退出，保留当前库，不自动改投／重放。

退出桥接不会删除注册项或终止原生对象。候选回退旧制品前须正常停止、核对活动任务与占用、备份当前配置和账本；新格式要按当前清单明确转换为旧格式，不能无条件覆盖历史备份。SQLite schema 6 保持，路由快照 version 2 的 registry_revision 是可选扩展，不是数据库迁移。
