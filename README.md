# wx-clawbot

通过本人微信选择本机多个注册项目中的准确 Codex 原生会话，提交任务、接收结果并处理交互。iTerm2 用于可见创建和桌面操作；微信选择独立于电脑当前画面，首次接入无需状态栏或终端标题显示 Session ID。

当前源码版本 `0.1.12`，运行账本 schema 6，路由快照 version 2。本轮 Git 交付见[0.1.12 记录](docs/validation/native-controls-release.md)，唯一进度源见 [ROADMAP](ROADMAP.md)。本机已加载已发布的 `0.1.12` 正式独立制品；后续工作区修正与交付状态见 ROADMAP，实际来源和旧数据保护见发布记录。

## 能力与前提

- 本人绑定、注册项目／合法目录、既有已加载对话选择、单次派发、持续选择、独立观察与可见新建。
- 当前源码支持总目录一层初始化，以及本机／微信 `project list/add/remove/check`；保留 `/projects`，注册变更即时生效，只维护已有目录关联。此能力已完成 PRJ01 验收，属于 0.1.11；旧 0.1.10 不支持新子命令，详见[项目管理](docs/project-management.md)。
- 原生队列、进展／文本结果、同步审批／追问、停止和恢复核对；unknown 不自动重放，投递失败不重新执行任务。
- 0.1.12 支持 `/model`、`/model list`、`/model set <模型名称> [推理强度]`、`/fast [on|off]` 及 `/codex status`。只改微信选中的会话，忙碌时拒绝；省略推理使用模型目录默认，Fast 仅确认开关设置。状态页显示模型、思考等级和账号剩余额度，默认隐藏 token 明细；[原生命令](docs/native-controls.md)说明版本及竞争边界。该能力已经过 0.169.0 原生及本人手机功能验收。
- 单张静态 JPEG／PNG 入站、原会话处理及文本结果。逐原生版本的代码准入、schema、真实原生和手机证据见[兼容矩阵](docs/protocol-baseline.md)，不能把某版核心通过当作全部功能验收。

需要 macOS、Python 3.14、Git、已登录 Codex 的既有受支持 daemon，以及可见创建所需的 iTerm2 Python API。电脑需开机联网，睡眠或关机期间不保证在线。注册根和已知准确 cwd 才在发现范围内，不递归搜索全部子目录／私人历史；详见[原生身份](docs/native-session-identity.md)。

当前只面向本人、本机、Codex；同消息图文、多图／其他媒体、图片结果回传、群聊／多用户、Web UI、云服务和多 Agent 编排不在已交付范围。Android 已验格式和 Mac 已知限制见[排版说明](docs/wechat-markdown.md)。

## 快速开始

以下是开发检出的安装与前台路线。日常托管用[独立非 editable 制品](docs/operations.md#eng01独立运行制品与开发隔离)，避免开发改动影响运行；不要同时启动前台与既有托管消费者。

1. 在仓库根准备项目环境，不安装全局 Python 包：

   ```sh
   python3.14 -m venv .venv
   .venv/bin/python -m pip install --require-hashes -r requirements.lock
   .venv/bin/python -m pip install --no-deps -e .
   ```

2. 按[配置模板](config/config.example.json)在本人私有目录准备配置，将 root 占位值换成真实绝对路径。默认私有状态根为用户 `Library/Application Support/wx-clawbot/`，目录 0700、敏感文件 0600，真实配置不入仓库。先只读诊断：

   ```sh
   .venv/bin/wx-clawbot doctor --config /absolute/path/to/private/config.json
   ```

   `runtime.verified_schema` 为 false 时先核对协议，不只修改版本列表。实际 server 版本以 daemon 为准，CLI 版本可以不同。显式 `doctor --iterm2` 可能触发脚本授权，不启用 API、不发终端输入。

3. 首次按[微信扫码与本人绑定](docs/wechat-protocol.md#前台扫码与本人联调)完成登录、核对对象和明确确认。已有本项目绑定可复用，不读取其他项目凭据。诊断 echo 不是 Agent 桥接，不能与 serve 同时占用绑定。

4. 开始前台运行，所有命令使用同一状态根；自定义目录加 `--state-dir`：

   ```sh
   .venv/bin/wx-clawbot serve --config /absolute/path/to/private/config.json
   ```

   既有旧库先执行 `migrate-state` 只读查看计划；serve 不自动升级。明确升级和备份步骤见[账本](docs/state-schema.md)。socket、原生可执行文件和 Codex home 的显式参数见[运维手册](docs/operations.md#启动查询与退出)。

5. 本人微信逐条操作，等待明确回执：

   ```text
   /projects
   /sessions
   /focus 1
   检查当前项目结构，先给建议，不修改文件。
   ```

   `1` 替换为本次列表的准确序号。`/sessions` 仅查询，保留输入目标和观察订阅，不启动 iTerm2；序号十分钟有效。退出输入目标使用 `/unfocus`；`/send 1 指令` 单次派发不改焦点。`/cd sample-one` 选择受管对话、没有时可见创建，`/new 标题` 在当前目录新建；窗口出现不等于握手成功。全部命令和别名见[命令契约](docs/command-contract-proposal.md)。

6. 另一个普通 Shell 查询或正常停止桥接；原生任务可能继续：

   ```sh
   .venv/bin/wx-clawbot status
   .venv/bin/wx-clawbot stop
   ```

   等待 stopped、消费者锁释放及原 job 停止后再启动。托管安装、备份、迁移、版本切换和失败恢复见[运维](docs/operations.md)。

## 使用时需要分清的边界

`/focus` 选择普通消息目标，`/attach` 独立观察桌面任务，`/detach` 只退订。桌面在同一 TUI 从 A 切到 B 不改变微信所选 A；A 仍准确加载可核验时继续，否则提示失败，不改投、不复制历史或恢复存档。接收时固定目标，后续切换不迁移旧任务。

同步追问的多题答案是原生题目 ID 到回答数组，例如 `{"choice":["PHONE_ALPHA"]}`；异步 `q-` 多题是全部题键到字符串，例如 `{"q1":"答案一","q2":"答案二"}`。按通知的准确 ID 使用 `/answer`，不要裸发选项猜请求。异步不保证任务暂停、模型采用或跨端首答互斥；门禁及期限见[异步契约](docs/async-questions.md)。

任务已接收、入队、原生执行完成、API accepted 和手机实际收到各有证据含义。`/status <任务 ID>` 分看结果、占用和投递；unknown 不自动重跑，少数异常按[准入处置](docs/operations.md#rec01-候选的准入诊断与受控切换)核验，不直接清锁。`/stop` 等待准确原生中断确认，不能保证所有已启动的系统子进程被杀死。

桌面忙碌时，另一个普通 Shell 可用核对过的原生入口：

```sh
codex queue --remote unix:///absolute/path/to/native-control.sock \
  --thread 'EXACT_NATIVE_THREAD_ID' --message '当前工作完成后，再检查测试结果'
```

先核 socket 和完整 native thread，不能拿桥接 s- 编号代替。原 TUI Enter／Tab 沿用原生语义，不作为统一队列入口；反例与边界见[桌面排队契约](docs/desktop-queue-contract.md)。

项目规则采用[原生限制契约](docs/project-rules.md#已确认的原生限制契约)：桥接不承诺规则热更新、变化检测或自动阻断。规则改变后本人明确新建可见会话并复验，旧队列不自动迁移／取消／重放。桥接不自动修改 Codex 全局设置，显示偏好由本人决定。

## 开发与文档

开发接手见[开发指南](docs/development.md)，按风险验证见[测试指南](docs/testing.md)。统一离线检查入口：

```sh
.venv/bin/python scripts/check.py
```

该入口不访问微信、不执行真实原生任务或切换生产服务。真实验收显式安排，不能用离线结果替代。文档总入口见[文档导航](docs/README.md)，其中包含 PRD、架构图、ADR、技术设计、运维、安全与需求追溯。

## 许可证

本项目自有代码和文档采用 [MIT License](LICENSE)。第三方依赖保持原授权；iterm2 Python SDK 声明 GPLv2+，自有 MIT 不代表完整组合产品可按 MIT 闭源再发行。清单与发行边界见[第三方声明](THIRD_PARTY_NOTICES.md)，信任与敏感数据见[安全说明](SECURITY.md)。
