# Webflow Bridge

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License: MIT"></a>
  <a href="https://github.com/darrenhooooo/webflow-bridge"><img src="https://img.shields.io/badge/GitHub-darrenhooooo%2Fwebflow-bridge-181717?style=for-the-badge&logo=github&logoColor=white" alt="GitHub: darrenhooooo/webflow-bridge"></a>
  <a href="docs/HTTP_API.md"><img src="https://img.shields.io/badge/Docs-HTTP%20API-FFD700?style=for-the-badge" alt="Docs: HTTP API"></a>
  <!-- TODO: 商店上架后把 # 换成真实的 Chrome Web Store 列表地址 -->
  <a href="#"><img src="https://img.shields.io/badge/Chrome%20Web%20Store-Coming%20soon-4285F4?style=for-the-badge&logo=googlechrome&logoColor=white" alt="Chrome Web Store — 即将上架"></a>
  <!-- TODO: 商店上架后把 # 换成真实的 Firefox AMO 列表地址 -->
  <a href="#"><img src="https://img.shields.io/badge/Firefox%20AMO-Coming%20soon-FF7139?style=for-the-badge&logo=firefox&logoColor=white" alt="Firefox AMO — 即将上架"></a>
  <a href="README.md"><img src="https://img.shields.io/badge/Lang-English-blue?style=for-the-badge" alt="English"></a>
</p>

**把浏览器交给你的 AI：全在本机运行，数据不出本机**

Webflow Bridge 不是云浏览器服务，不是 cookie 仓库，也不是需要额外维护的"第二个自动化浏览器"。你的脚本和 AI agent 向跑在本机的小型 daemon POST JSON 命令，daemon 去驱动**你已经打开的那个标签页** —— 你的会话、你的 cookie、你的登录态。一切都在本机，数据不出设备。

**Agent 工具兼容。** Webflow Bridge 说标准的 `POST /command` 浏览器桥协议，为浏览器桥写好的脚本与 agent skill 无需改动即可继续使用 —— 把地址指向 `http://127.0.0.1:10086` 就能跑。

## 它能为你解决什么

| 能力 | 解决什么问题 |
|---|---|
| 🖥️ **驱动你正在用的浏览器** | 直接操作你已登录的活动标签页 —— 真实会话、cookie 与页面状态全在，没有需要同步的隐形浏览器。 |
| 🤖 **为脚本与 Agent 而生** | 统一的 `POST /command` 协议；浏览器桥的 agent skill 可 1:1 映射。 |
| 🎯 **30+ 浏览器动作** | 点击、输入、填表、上传/拖放文件、截图、存 PDF、读页面、切标签、看网络流量与控制台日志——以及更多。动作失败时自动留下当前标签页截图，请求还可选择对瞬时错误自动重试。 |
| 🪟 **JS 弹窗不卡流程** | alert / confirm / prompt 自动应答：确定、取消或输入答案。 |
| 📎 **上传不弹系统框** | 点上传按钮、交给它本地文件路径即可 —— 系统"打开文件"窗口根本不会出现。 |
| 🔓 **严格站点也能跑** | 页面禁用自身脚本的站点照常执行 —— x.com 等实测可用。 |
| 🌍 **会说 16 种语言** | 弹窗与简介句跟随浏览器语言自动切换，零配置。支持：阿拉伯语、简体中文、繁体中文、英语、法语、德语、印地语、印度尼西亚语、意大利语、日语、韩语、葡萄牙语、俄语、西班牙语、泰语、越南语。 |
| ⚡ **点一下就连上** | 弹窗显示**已激活**或**未激活**。未激活时点一下状态卡，它会主动帮你连 daemon；连不上会直接说明原因：daemon 没运行，或已被另一个浏览器占用。 |
| 🔁 **macOS 常驻** | 一行命令把 daemon 交给 launchd，开机即在 —— 不用一直开着终端窗口。 |
| 🔒 **天生隐私** | 一切都在你的机器上。无云、无账号、无遥测，数据不出设备。 |
| 🧩 **一份扩展、两个浏览器** | 同一份 `extension/` 目录 Chrome、Edge 通用；Firefox 另有独立版（见 [ff/README.md](ff/README.md)）。 |

## 典型用法

- **发布自动化** —— 用你的真实账号发 X / LinkedIn / Facebook / 博客，跟你手动操作一模一样。
- **采集与监控** —— 读你本来就能访问的页面、翻页点击、看网络流量与控制台日志。
- **端到端测试** —— 在真实浏览器会话上跑完整流程（开不开 DevTools 都行）。
- **RPA 粘合剂** —— 任何"希望有个脚本能帮我点一下"、纯 HTTP 又搞不定的网站任务。

它一次只驱动**一个标签页**，绝不抢你的鼠标和焦点 —— 它干活的同时，你照常用其他标签页、其他浏览器或任何别的软件。想让它重启后继续待命？macOS 上一行命令交给 launchd 即可。

## 和其他方案怎么选

| 如果你需要…… | 用…… |
|---|---|
| 让 AI agent 在你真实登录态的浏览器里做一件事 | **Webflow Bridge** |
| 让 agent 自己跑多页任务，要云端并发 / 内置模型 | Browser Use 那类 agent 框架 |
| 用 Playwright 生态做端到端测试 | Playwright MCP |
| 要 DevTools 深度能力（性能 trace、网络、Lighthouse） | Chrome DevTools MCP |

Webflow Bridge 的不同之处：它驱动的是你已经打开、已经登录的那个浏览器 —— 同一个 profile、同一套 cookie、同一个会话，走的是浏览器扩展权限加本地令牌。数据不出本机，也不会留一个暴露给本机其他进程的远程调试端口。Firefox 上同样如此：驱动的是你日常那个真实 profile，而非另一个自动化专用的浏览器构建。

## 实测，不是宣称

同一台机器、十个脚本化浏览器任务、每个跑三次：

|  | 固定本地命令（无模型） | LLM agent 驱动浏览器 |
|---|---|---|
| 模型 token | 0 | prompt 1,518,312 + completion 114,303 |
| 30 次总耗时 | 11.00 秒 | 915.15 秒 |
| 花费 | $0 | $0.172496（估算，不是账单） |

这十个任务上两侧成功率相当 —— 差别在一次运行花多少钱、以及能不能重复跑出一样的结果。固定的 `POST /command` 命令序列根本不需要模型，token 和等待时间都能归零；而让模型一步步决策的路径没有这个选项。

边界说明：这十个都是本地小测试页，数字不等于真实大页面的成本；对手侧是版本快照（browser-use 0.13.10），它一升级数字就会漂。方法与原始日志、以及全部诚实说明：[docs/BENCH.md](docs/BENCH.md)、[bench/](bench/)。

---

## 安装

需要 **Python 3.11+** 和 Chrome、Edge 或 Firefox —— 全程本地，无账号、无云、无 API key。

- **Chrome / Edge** —— 启动 daemon，再解压加载一次 `extension/`：`python3 daemon/webflow_bridge.py`（Windows：`py -3.11 daemon/webflow_bridge.py`），然后 `chrome://extensions`（Edge：`edge://extensions`）→ 开发者模式 → **加载已解压的扩展程序** → `extension/`。
- **Firefox** —— 独立版、端口 `10096`：`ff/ff-launch.sh && python3 ff/daemon/ff_bridge.py`（Windows：`ff\ff-launch.bat && py -3.11 ff/daemon/ff_bridge.py`）。
- **macOS 常驻** —— 按 [docs/INSTALL.md](docs/INSTALL.md) 完成一次 launchd 配置后，这行会让它每次登录自动启动：`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.webflow.bridge.plist`。

完整细节 —— 两种启动方式、launchd/systemd、端口与 token、卸载与排错：**[docs/INSTALL.md](docs/INSTALL.md)**。

## 把它交给你的 agent

把下面这段直接粘给 coding agent（Claude Code、Codex、Hermes 等），让它自己接上：

> 你要接入本仓库的 Webflow Bridge。先在仓库根目录启动 daemon（`python3 daemon/webflow_bridge.py`，Windows 用 `py -3.11 daemon/webflow_bridge.py`）。然后按 `docs/MCP.md` 注册 MCP server，并按该文档的要求重载/重启你的 MCP 客户端。最后读 `llms.txt` 与 `docs/AGENTS.md`，据此通过 `POST /command` 或 MCP 工具驱动浏览器。
>
> 有一步必须先由人来做：在 `chrome://extensions` 或 `edge://extensions` 里以解压方式加载 `extension/` 文件夹（开发者模式 → 加载已解压的扩展程序）。扩展尚未上架浏览器商店，所以无法自动安装。

## 常见问题速查

- **`503 {"error":"extension not connected"}`** —— Chrome/Edge 没开，或扩展没加载。启动浏览器后，看「Webflow Bridge」popup 是否显示 *Daemon: connected*。
- **报 "chrome:// … cannot be debugged"** —— 活动标签页必须是普通 http(s) 页面；`chrome://`、商店页、新标签页都不行。
- **报 "Another debugger is already attached"** —— 该标签开着 DevTools（或另一个 CDP 客户端）。关掉再试。
- **端口被占用** —— 已有另一个 Webflow Bridge 实例在跑，先停掉它。
- **报错提到 "Content Security Policy"** —— 你还在 content-script 时代的旧构建上。到 `chrome://extensions` 完整重载扩展；当前构建走调试通道，页面 CSP 拦不住。

完整故障排查表见 [docs/INSTALL.md](docs/INSTALL.md)。

## 支持平台

| 浏览器 | 状态 | 方式 |
|---|---|---|
| Chrome —— macOS & Windows | ✅ | `extension/` 解压加载；`chrome.debugger` |
| Microsoft Edge —— macOS & Windows | ✅ | 同一份 `extension/` 目录 |
| Firefox | ✅ 独立版 | WebDriver BiDi、端口 `:10096` —— [ff/README.md](ff/README.md) |
| Safari | ❌ 不支持 | — |

如实说明边界：一次只驱动**一个标签页**，不抢鼠标和焦点；`chrome://` 类页面、商店页和新标签页无法调试；Firefox 版 `navigator.webdriver === true` 无法关闭（定位是驱动你自己的已登录站点，不承诺反爬对抗）。

## 隐私与约束

- **全本地。** daemon 跑在你自己的机器上，命令与结果不出设备。无云、无账号、无遥测 —— 见 [docs/PRIVACY.md](docs/PRIVACY.md)。
- **仅回环。** daemon 只绑定 `127.0.0.1` —— 不向你的网络或其他机器暴露任何端口。
- **仅手动安装。** 扩展由你亲自加载（开发者模式 → 加载已解压），永不自动安装；不触碰、不复制、不重写任何浏览器 profile。Firefox 版同样驱动你日常在用的真实 profile。
- **零第三方依赖。** daemon 只用 Python 标准库。
- **MIT 许可** —— 自由使用、修改与嵌入。

## 文档导航

| 文档 | 内容 |
|---|---|
| [docs/INSTALL.md](docs/INSTALL.md) | 安装、launchd/systemd 常驻、端口与 token、验证、卸载、完整故障排查。 |
| [docs/HTTP_API.md](docs/HTTP_API.md) | `POST /command` 协议契约 —— 每个核心动作一条 curl、错误结构、零 SDK 完整 demo 流程。 |
| [docs/PRIVACY.md](docs/PRIVACY.md) | 通俗英文隐私政策（扩展做什么、数据、权限）。 |
| [ff/README.md](ff/README.md) | Firefox 独立版 —— 安装、动作矩阵、平台状态、已知边界。 |
| [Releases](https://github.com/darrenhooooo/webflow-bridge/releases) | 版本历史与发布说明。 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 如何参与贡献。 |
| [SECURITY.md](SECURITY.md) | 安全策略与漏洞报告方式。 |

## 许可证与支持

Webflow Bridge **免费开源（MIT）** —— 见 [LICENSE](LICENSE)。如果它帮你省了时间：

- ⭐ 点 Star —— [github.com/darrenhooooo/webflow-bridge](https://github.com/darrenhooooo/webflow-bridge)
- 🐛 报 Bug / 提需求 —— [Issues](https://github.com/darrenhooooo/webflow-bridge/issues)
- 📦 Releases —— [v1.5.0](https://github.com/darrenhooooo/webflow-bridge/releases)
- ✉️ 联系 —— darren.hou@outlook.com
