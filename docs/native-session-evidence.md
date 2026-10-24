# W02 原生连接证据

## 测试边界

本记录区分真实 daemon 握手、离线测试与终端产品验收。实际进度见 [ROADMAP](../ROADMAP.md)。没有向工作终端注入文本，没有创建替代 runtime 或复制历史。

## 真实握手定位与结果

2026-10-24，CLI 0.163.0、共享 daemon 0.164.0，Python 3.14.5。

首次原型经 `app-server proxy --sock` 向标准输入发送 JSONL，initialize 超时。随后核对 OpenAI 固定源码：proxy 使用 `tokio::io::copy` 透传原始字节，Unix 控制端点执行 WebSocket upgrade；它不做 JSONL／WebSocket 转换。依据：[proxy 分派](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/cli/src/main.rs)、[字节透传](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/stdio-to-uds/src/lib.rs)、[Unix transport](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/app-server-transport/src/transport/unix_socket.rs)。该源码为当前官方固定提交，不假定与安装二进制逐字相同；实际行为另行核对。

修正为已锁定 websockets 的 Unix WebSocket 连接，发 initialize（clientInfo、experimentalApi），收到响应后发 initialized。真实结果：握手成功，返回平台 unix／macos，版本 0.164.0。只关闭本桥接连接；未启动、停止、升级 daemon，未读取 thread 列表或正文，未提交模型任务。

## 已实现的安全边界

- socket 必须属于当前用户且禁止组／其他用户访问；未核对的版本拒绝接入。
- RPC 请求按带类型的 ID 关联；异步接收原生事件与请求。超时返回结果未知，不重放；断连失败所有待请求；事件队列满时连接进入故障状态，不悄悄丢审批。
- 宿主只读端点检查核对 session ID、job PID、进程启动时间、可执行路径与 TTY。普通 Shell、TTY 不符或退出端点均不会作为 Codex 候选。候选仅代表进程证据，尚不代表 native thread 已绑定；PID 启动时间精度及实际重用场景仍需 V01 验证。

## 未通过关卡

iTerm2 SDK 真实连接 localhost:1912 被拒绝，等待启用 API 与脚本授权。两个私有临时测试项目已准备；未创建或操作测试终端。

V01 的 terminal／process／runtime／thread 四方关联及 V02 的桌面 → 桥接 → 桌面三轮仍未验证。不能把本阶段的握手成功称为原终端接入，也不能进入依赖它的 W03 验收。

离线测试使用内存对端及本地临时 Unix WebSocket 服务器，分别覆盖乱序响应、整数／字符串 ID、原生请求分类、超时与迟到响应、EOF、RPC 错误、畸形消息、事件溢出、版本拒绝及 socket 权限。它们不是 Codex 双端交互的实测。
