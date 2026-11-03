# 第三方授权与发行边界

本项目自有代码和文档按 [MIT License](LICENSE) 授权。第三方软件、引用资料及其中的版权和许可声明保持各自原授权；本文件是依赖清单和发行说明，不修改第三方授权，也不授予第三方应用、账号或服务的使用权限。

## 本项目制品的范围

本项目源码包和 wheel 不内置下表中的依赖实现、依赖 wheel、原生库、iTerm2／Codex 应用或微信客户端；运行依赖通过 `Requires-Dist` 与 [requirements.lock](requirements.lock) 单独安装。依赖清单中的 GPL 不因未内置而自动失效：是否构成受 GPL 约束的组合作品仍须按实际结合和发行方式判断。

`pyproject.toml` 中的 `license = "MIT"` 描述本项目制品内自有作品的授权，不表示所有依赖均为 MIT，也不保证安装依赖后的完整组合产品可按 MIT 闭源再发行。若以后加入第三方实现或改变打包方式，应重新核对许可证表达式及随包声明。

单独安装的依赖应保留其发行包自带的许可证文件。若重新分发依赖、虚拟环境、容器、独立应用或原生动态库，须随实际交付内容保留完整版权、许可证和其他必要声明，并履行适用的源码提供等义务；本清单和链接不能替代这些义务。

## 锁定运行依赖

下表依据 `requirements.lock`、已安装的同版本发行元数据及其许可证文件核对。许可证名称是主项目声明，不能代替某个 wheel 内嵌组件的逐项授权；尤其 Pillow 的发行 `LICENSE` 还包含图像库等组件声明。

| 软件及版本 | 关系 | 发行声明／许可证文件核对 | 官方来源 |
| --- | --- | --- | --- |
| iterm2 2.30 | 直接依赖 | GPL-2.0-or-later；元数据同时写 `GPLv2` 与 GPLv2+ classifier；分发问题见下节 | [发行页](https://pypi.org/project/iterm2/2.30/) |
| websockets 17.3 | 直接依赖及 SDK 依赖 | BSD-3-Clause | [发行页](https://pypi.org/project/websockets/17.3/) |
| segno 1.6.6 | 直接依赖 | BSD-3-Clause；依据发行 `LICENSE` 的三条条件核对 | [发行页](https://pypi.org/project/segno/1.6.6/) |
| cryptography 50.0.2 | 直接依赖 | Apache-2.0 OR BSD-3-Clause；保留其选择说明及相关文本；含原生组件的制品另核对组件声明 | [发行页](https://pypi.org/project/cryptography/50.0.2/) |
| Pillow 13.0.0 | 直接依赖 | MIT-CMU；不等同于根目录 MIT；完整发行 `LICENSE` 含其他组件条款 | [发行页](https://pypi.org/project/Pillow/13.0.0/) |
| markdown-it-py 4.2.0 | 直接依赖 | MIT；发行包另含原 markdown-it 的 `LICENSE.markdown-it` | [发行页](https://pypi.org/project/markdown-it-py/4.2.0/) |
| protobuf 7.36.2 | iterm2 的传递依赖 | BSD-3-Clause；保留发行 `LICENSE` 内的附加声明 | [发行页](https://pypi.org/project/protobuf/7.36.2/) |
| cffi 2.1.1 | cryptography 的传递依赖 | MIT-0；发行文本要求同时留意局部例外声明 | [发行页](https://pypi.org/project/cffi/2.1.1/) |
| pycparser 3.12 | cffi 的传递依赖 | BSD-3-Clause | [发行页](https://pypi.org/project/pycparser/3.12/) |
| mdurl 0.1.2 | markdown-it-py 的传递依赖 | MIT；保留发行 `LICENSE` 中全部版权及附加声明 | [发行页](https://pypi.org/project/mdurl/0.1.2/) |

可从同版本安装包的 `*.dist-info/METADATA` 和 `*.dist-info/licenses/` 查验原始声明；protobuf 与 mdurl 的许可证位于其 `*.dist-info/LICENSE`。iterm2 2.30 的已核对源码包和安装包未附独立许可证文件，不能据此视为无授权限制。

## iterm2 SDK 的 GPL 边界

- 本项目直接导入 `iterm2` 及其子模块，包括 `hosts/connection.py`、`hosts/lifecycle.py` 等；不能仅按“独立程序间通过协议通信”推断整个 SDK 集成已豁免 GPL。
- [官方 SDK setup.py](https://github.com/gnachman/iTerm2/blob/0139844e77721d2d5e1412a946d9ce9b0f8d260e/api/library/python/iterm2/setup.py) 声明 `license="GPLv2"` 和 GPLv2+ classifier，且与 SHA-256 核验通过的 PyPI 2.30 源码包中的 setup.py 完全相同。该源码包的许可声明、上游根目录 [LICENSE](https://github.com/gnachman/iTerm2/blob/0139844e77721d2d5e1412a946d9ce9b0f8d260e/LICENSE) 与 [COPYING](https://github.com/gnachman/iTerm2/blob/0139844e77721d2d5e1412a946d9ce9b0f8d260e/COPYING) 未提供本次集成可直接采用的 SDK 专用链接例外。上游 COPYING 关于 iTerm2 应用整体因 Apache 依赖实际采用 GPLv3 的说明，不直接替代 SDK 自己的发行声明。
- 本项目的 MIT 授权只授予自有作品的相应权利；如果对外发行的组合作品受 GPL 约束，应保留 MIT 声明，并履行组合发行适用的 GPL 条件。不能仅添加此文件或让用户自行安装 SDK，就宣称完整组合产品可不受 GPL 条件限制地闭源发行。
- 若将来需要承诺完整产品可闭源再发行，应先取得明确覆盖该集成的额外授权，或评估能够证明许可兼容的替代实现。当前没有取得此类额外授权，也没有为此替换 SDK；完整组合产品的闭源发行兼容性仍待确认。源码与打包核对证据见 [MIT 落实记录](docs/validation/mit-license.md)。

## 公开参考与构建工具

- 微信协议参考为腾讯公开的 openclaw-weixin 2.4.10，固定 commit `874637a0dbc24050f72d1385add4fc6170a2d726`，原项目采用 MIT。本项目记录协议字段和参考证据，未 vendor 上游实现；文件来源与原始 SHA-256 见 [参考清单](docs/wechat-reference.json)，原版权及条款见[上游 LICENSE](https://github.com/Tencent/openclaw-weixin/blob/874637a0dbc24050f72d1385add4fc6170a2d726/LICENSE)。本项目 MIT 声明不取代该参考的原声明。
- 构建后端为 `setuptools==80.9.0`，其项目声明为 MIT；构建工具及其 vendored 依赖不内置到本项目 wheel。若对外复制构建环境，需另行保留工具发行包自己的完整许可声明。

本清单覆盖当前锁定依赖与制品范围；新增依赖、复制第三方代码、捆绑二进制或改变发行形态时须同步复核。
