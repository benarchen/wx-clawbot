# ASK01 异步补充答复契约

本文定义本人于 2026-11-03 接受的异步补充接口，已在本机 0.1.2／schema 6 加载；完整验收和实际状态见 [ROADMAP](../ROADMAP.md)，证据见[验证记录](validation/async-questions.md)。同步审批／追问的原生首答裁决保持原规则。

## 能力边界与原生依据

仅对现场已实证的 app-server 0.166.0 开启结构化异步问题处理。准确已订阅 thread 的 `item/completed` 中，`agentMessage` 同时具有 `delivery=async`、非空合法 questions、item ID 和 turn ID，才可登记；started 不完整事件不生成卡，普通疑问句不生成请求。其他版本或损坏结构提示原终端处理，不生成可提交入口。

异步问题不暂停任务。答案通过 `turn/steer` 的准确 `threadId`、`expectedTurnId`、稳定 `clientUserMessageId` 和单个 text input 补充到原活动轮次；原生没有问题级答复原语或首答独占。同步审批或确实需要阻塞的动作继续依靠原生同步请求及真实执行门禁。不得用异步答案授予执行权限。

桥接本入口对每个问题最多提交一次，电脑和微信仍可能同时被原生接收。已观察到未登记输入时关闭尚未提交入口；已提交答案遇到未登记输入则明确提示冲突，原业务结果继续遵循多输入 unknown 保护。历史、空队列及事件暂未显示另一答案不能证明没有竞争。

## 问题、答案与证据

- 请求 ID 为 `q-` 加稳定 UUID；唯一键为准确 runtime 身份、thread、turn、item。题键按原顺序生成 `q1` 至 `q20`，选项保持原字符串及顺序，无选项允许自由文字。重复选项、空题或不完整结构拒绝；同 item 内容变化使旧入口失效，不悄然改写原题或答案。
- `/answer <q-id> <单题文本>`，或多题 `/answer <q-id> {"q1":"答案一","q2":"答案二"}`。JSON 必须完整覆盖所有题键；拒绝重复 JSON 键、空答案、非法类型、单题超 4000 字符及组合超 32000 字符。不根据选项序号代选；自由补充不受选项文本限制。
- 提示包含原项目、问题、选项、请求 ID、600 秒本地有效期，以及任务可能继续和跨端竞争说明。题目／选项放入确定性选长的代码围栏，作为字面内容展示；总提示超过 7000 字符不截断开放入口。单事件不超过 1 MiB，同一 turn 最多保留 256 个问题；同步与异步的活动记录共享 256 条／16 MiB，超限固定提示原终端处理，不能丢弃未结记录腾空间。
- 本地有效期同时使用固定墙钟期限与进程内 monotonic 上界，时钟跳变不延长入口。过期只关闭入口，不取消任务、不释放占用，不推断原生问题已过期。
- 新答案完整复验原 terminal／PID／启动／TTY／可见 thread／runtime／native session／cwd，以及当前代次和准确 turn。通知沿准确已核验订阅保留原目标，不因 focus／attach 切换改投。

| 状态 | 证据与含义 |
| --- | --- |
| pending | 完整问题和冻结通知在同一事务登记，本地入口可答，任务仍运行 |
| sending | 精确答案正文、摘要、稳定 client 已提交；任何第二份微信答案均拒绝 |
| accepted | 原生 RPC 明确返回同一 turnId；仅表示已接受补充，不证明模型采用 |
| observed | 准确历史或原生事件出现同一 answer client，正文摘要精确一致；仅表示输入可见，不伪造模型处理或 resolved |
| stale | 本地超时、题目变化、原 turn 结束、目标／连接失效或已知其他输入；没有自动新任务 |
| refused | 原生明确拒绝；仍不自动重试或改答案 |
| unknown | 调用可能到达但未得到确定结果；保留意图，拒绝重试。后续可由精确输入证据收敛为 observed |
| conflict | 已提交补充且观察到未登记的其他输入；可能同时有效，不决定谁胜出，保留业务歧义保护 |

断连／重启：pending 变 stale，sending 变 unknown；已 accepted／observed 的证据保留，但旧连接不能恢复提交资格。任何旧卡均不重发。turn 终态立即关闭其未提交入口，已提交记录保留真实状态和结束时间，不启动后续轮次。

## 持久化及严格任务关联

schema 6 在 RuntimeState 的同一 SQLite 单写入执行器下增加 `async_questions`，不复用同步 RPC interactions。固定字段为：`public_id,source,thread_id,turn_id,item_id,revision,questions,question_sha256,target,task_id,generation,state,reason,expires_at,answer_client,answer_text,answer_sha256,created_at,updated_at,closed_at`。`public_id` 主键；`(source,thread_id,turn_id,item_id)` 唯一；`answer_client` 唯一且可空；task 外键；状态 CHECK；索引为原 thread／turn、本地活动入口和 task。revision 初始为 1，变化仅递增并关闭入口，不覆盖原 questions 或答案证据。

题目与渲染后冻结通知在同一事务写入。答案使用带 pending、generation、revision 和期限前置的原子 UPDATE，提交 sending 后才允许外部调用。取消恰好发生在事务提交后也不得重试；调用不明只落 unknown。终态或冲突在 RPC 期间到达不能被晚到 ACK 复活。

辅助输入必须同时匹配预先持久化的原来源、thread、turn、稳定 answer client 和正文摘要；输入恰好有原业务 client 一次，其他输入全部属于该任务已登记答案，才可保留独立结果。错正文、错 turn／thread、重复 client、跨任务冒用及任何未登记输入均不放行。事件路径先分类辅助输入，避免误收养成桌面任务；在线完成、普通／外部恢复及换代核对使用一致规则。

仓库占用仍由 REC01 独立判断：unknown 结果可以在准确原生终态、完整空队列及代次证据后释放，答案 ACK 不授予释放资格。辅助答案不新建业务任务、不新增容量或原任务派发。

显式 1／2／3／4／5→6 迁移保留维护锁、绑定校验、私有备份、事务及旧业务行／冻结摘要核对；旧库启动不隐式升级。默认不清除异步记录；unknown、未结、未见输入和分类证据保护。30 天清理仅可在维护入口明确 apply 后处理已关闭且可确认处置的记录，并须保留原任务仍需要的辅助分类证据。

## 实施及验证入口

状态持久化放在 `src/wx_clawbot/async_state.py`，协议校验／展示／Execution 协作放在 `src/wx_clawbot/async_questions.py`；不创建第二个消费者、daemon 或通道。基础测试继续 unittest，真实原生测试显式入口为 `tests/integration/async_questions_native.py`，120 秒本地负载为 `tests/integration/async_questions_load.py`；原生入口要求准确 owned case、显式确认和全新报告，不接入用户工作终端。当前版本为 0.1.2。手机发送须另有准确内容与条数授权，API 接受和手机实收分列。

示例：单题 `/answer q-<收到的准确 ID> PHONE_ALPHA`；多题 `/answer q-<收到的准确 ID> {"q1":"答案一","q2":"答案二"}`。不要发送尖括号占位符或自行猜 ID。`/status` 查看活动入口，`/status <原任务 ID>` 查看准确状态、题目摘要及原因。已结束问题需要补充时，由本人明确选择目标并发送新的普通任务，旧 `/answer` 不会自动启动它。
