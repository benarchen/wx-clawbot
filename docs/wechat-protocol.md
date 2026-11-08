# 微信通道协议与联调入口

输入固定于 [腾讯参考清单](wechat-reference.json) 的同一 commit；W04 补充消息类型文件，IMG01 再核对四份图片下载、解密及 CDN 源码。本文描述本项目具体实现与测试方法，当前进度以 [ROADMAP](../ROADMAP.md) 为准。

## 请求字段与本项目选择

| 路径 | 本项目请求形态 |
| --- | --- |
| `POST ilink/bot/get_bot_qrcode?bot_type=3` | `local_token_list: []`，只申请独立二维码；没有其他客户端 token、`base_info` 或 Bearer |
| `GET ilink/bot/get_qrcode_status` | URL 编码的 qrcode，可选配对码；仅应用 headers，不带 POST 鉴权头 |
| `POST ilink/bot/getupdates` | 自有 bot token、已确认游标 `get_updates_buf`、`base_info`；不用已废弃的 `sync_buf` |
| `POST ilink/bot/sendmessage` | `from_user_id: ""`，收件人必须是扫码且明确确认的 owner；稳定 `client_id`，type／state 为 2，单个 type 1 文本 item，原消息回复上下文 |

出站 Markdown 仍通过文本 item 的 `text_item.text` 发送，没有新增 `parse_mode` 或其他未经核验的模式字段。新回执在入账前完成兼容渲染和结构分段，发送器逐字使用冻结正文；升级不重排历史 outbox，投递重试不重新执行任务。接口 accepted、本人实际显示和实际复制分别记录，客户端兼容范围见[排版说明](wechat-markdown.md)及[真机证据](validation/wechat-markdown.md)。

公共 `iLink-App-Id` 采用参考中的 `bot`；客户端版本按参考的 uint32 算法编码本项目自身版本；历史 `0.1.0.dev0` 对应 256，当前 0.1.11 对应 267。`base_info.channel_version` 使用本项目版本，`bot_agent` 为 `wx-clawbot/<version>`，不伪装成参考插件及其版本。真实接口已完成独立扫码、鉴权轮询及本人手机文本往返。

POST 加入 `Content-Type: application/json`、`AuthorizationType: ilink_bot_token` 和随机 uint32 十进制字符串的 base64 `X-WECHAT-UIN`。只有已登录 bot POST 才加入 Bearer。HTTPS 服务地址仅接受经校验的微信域名与标准端口；HTTP 重定向不自动跟随。登录的 IDC 跳转按应用层状态核对新 host，不能把凭据带到任意返回地址。

HTTP 错误、非零业务码、会话失效和未知投递区分处理。消息与发送回执 ID 用 Python 无损整数／十进制字符串处理；响应有上限，非对象、重复 JSON 字段和非法数值拒绝。登录、轮询和发送各用单工作线程与独立槽位，取消调用者不会提前释放仍在运行的槽位；关闭需要等待有限超时的请求排空，不能仅宣称已停止输出。

真实 `getupdates` 可省略 `ret`，与固定类型定义中的可选字段一致；只有返回可识别的消息列表和非空游标时才接受这种响应，空对象、无游标的无状态响应、显式 null／错误类型及非零业务码仍拒绝。接收与事务层共用同一校验，不能在接收层通过后又因同一可选字段丢弃整批消息。此规则只适用于接收，不自动推断缺少发送成功回执等于已送达。

真实 `sendmessage` 返回过仅含 `message_id` 的响应，ret 也为可选字段。本项目接受明确 `ret: 0`，或无业务错误且带有效正 uint64 原生消息 ID 的成功回执；ID 无损处理，布尔值、零、负数、浮点数、非数字及越界值不能充当该回执。正消息 ID 同时伴随业务错误时保守记为 unknown，不冒充明确拒绝；格式错误、HTTP 失败、空对象及无法识别的回执也进入 unknown，不自动重试。

## 身份、去重、游标和回复上下文

首次扫码仅保存待确认凭据，不允许收发。本人明确确认后，客户端仍逐条核对发件人为 owner、收件人为该 bot，拒绝群聊、非用户消息与未完成消息。诊断入口保持纯文本；当前产品交付一张静态 JPEG／PNG；解析器另可保留同消息图文，但该形态经本人明确后置，尚无单条真机交付证据。其他媒体或多图整条拒绝，不只执行残余文字。缺少稳定原生 message ID 的输入不进入任务链路，不用正文哈希吞掉相同文本的不同消息。

`ChannelState` 使用独立私有 SQLite。inbox 与非空游标在同一事务提交；中途存储失败全部回滚。重复 message ID 不再次交付，原 ID 下的不同正文标记冲突；不同 ID 的相同正文各自保留。旧消息或重复消息不会替换较新回复上下文。未知身份不保存其消息正文。新版 runtime 对已核验本人的不支持媒体记录稳定摘要和错误类别以明确回执，不保存被拒媒体正文或下载材料；支持图片的有序内容及附件引用同事务保存。

图片字段优先 image_item.aeskey；否则解析 media.aes_key 的 base64 原始 16 字节或十六进制字符串。完整 URL 优先于 encrypt_query_param；只允许固定微信 CDN HTTPS origin，不跟随重定向、不带 bot Bearer。有密钥时按 AES-128-ECB／PKCS#7 解密，无密钥也须完整解码。现有 HTTPS CONNECT 代理保持原主机名 TLS 校验；直连解析只允许公网且连接已核验地址。资源上限、附件保护及使用方式见 [图片指南](image-input.md)，两端可行性与整链路验收分开见 [IMG01 记录](validation/image-input.md)。

诊断接收标记为 `diagnostic`，不转为 Agent 任务，不因后续接入路由而回放历史个人消息。测试回显只匹配明确口令；每条原消息先保存发送意图再调用 API。断连或缺少明确成功回执进入 unknown，不能自动重新发送，更不能重新执行任务。API `ret: 0` 或有效原生消息 ID 仅表示服务端接受；手机实际收到还须本人核对。

回复上下文按绑定账号和原入站消息保存，不拿其他账号或任意值替代。受控真机测试中，531 秒前的旧上下文及人工构造的无效上下文都被服务端接受，且本人确认手机收到。该观察不证明接口永远不检查上下文，也不证明自然过期后的恢复已经通过；不据此删除 context_token、硬编码未经验证的有效期或自动修改凭据。详细证据见[W04 验证记录](validation/w04.md)。

## 前台扫码与本人联调

默认私有目录为 `~/Library/Application Support/wx-clawbot/`。目录 0700，凭据、二维码及状态文件 0600；已有凭据不会被新扫码静默覆盖，同一状态数据库有独占消费者锁。所有示例在本项目安装后、普通 Shell 中执行。

```sh
.venv/bin/wx-clawbot wechat login --open
```

命令申请二维码并打开本地页，等待本人操作。请使用本人测试微信，在手机核对绑定对象；若提示替换现有连接，先停止确认并核对影响。配对码若被要求，通过私有 stdin 管道传入 `--verify-code-stdin`，不放进命令参数或日志。二维码过期后可明确使用 `--fresh` 刷新；请求结果未知时不盲目重发。

扫码完成后输出待确认状态及 owner 指纹。只有本人明确确认该测试账号与联调对象，才执行：

```sh
.venv/bin/wx-clawbot wechat bind --confirm-self --owner-fingerprint '<scanned-owner-fingerprint>'
```

本人联调使用随机测试口令，在已绑定聊天连续发送两次相同口令，核对各自收到一条编号回显：

```sh
.venv/bin/wx-clawbot wechat echo --challenge '<random-test-challenge>' --count 2 --timeout 180
```

口令须为 8 至 128 个英文字母、数字、下划线或连字符。回显命令只回复该口令，普通文本不回显，也不调用 Codex。`--state-dir` 可明确选择本项目自己的私有目录，不能指向其他项目凭据。前台 Ctrl+C 停止后未知投递不会自动重试，原 Codex 终端不受影响。

## 新增二维码依赖

标准库与当时已有依赖不提供 QR 编码。选择 `segno==1.6.6` 仅生成标准 PNG，不因二维码引入 Pillow 或网络依赖；IMG01 后来另为完整图片解码引入 Pillow，见 [依赖证据](protocol-baseline.md)。Python 3.14 下真实生成 PNG 并用于登录页，手机扫码为 V06 的最终可读性验证。

[PyPI](https://pypi.org/project/segno/) 核对发行日期 2025-03-12、哈希和 Python 要求；[官方源码](https://github.com/heuer/segno/commit/b11dc2913c22b22b3bc0a6efaa989904c44977bf) 最近抽样提交为 2026-07-23，许可证 BSD-3-Clause。抽样 issue #153 的三条评论均为 NONE 角色，不能证明维护者及时响应；不把这些检查称为完整安全审计。依赖只在项目虚拟环境安装，精确版本与分发哈希进入 requirements.lock。
