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

**免费、本地的浏览器自动化桥 —— 驱动你真实、已登录的 Chrome 或 Edge。无云、无账号、不复制 cookie。**

Webflow Bridge 不是云浏览器服务，不是 cookie 仓库，也不是需要额外维护的"第二个自动化浏览器"。你的脚本和 AI agent 向跑在本机的小型 daemon POST JSON 命令，daemon 去驱动**你已经打开的那个标签页** —— 你的会话、你的 cookie、你的登录态。一切都在本机，数据不出设备。

**Agent 工具兼容。** Webflow Bridge 说标准的 `POST /command` 浏览器桥协议，为浏览器桥写好的脚本与 agent skill 无需改动即可继续使用 —— 把地址指向 `http://127.0.0.1:10086` 就能跑。

## 它能为你解决什么

| 能力 | 解决什么问题 |
|---|---|
| 🖥️ **驱动你正在用的浏览器** | 直接操作你已登录的活动标签页 —— 真实会话、cookie 与页面状态全在，没有需要同步的隐形浏览器。 |
| 🤖 **为脚本与 Agent 而生** | 统一的 `POST /command` 协议；浏览器桥的 agent skill 可 1:1 映射。 |
| 🎯 **30+ 浏览器动作** | 点击、输入、填表、上传/拖放文件、截图、存 PDF、读页面、切标签、看网络流量与控制台日志——以及更多。 |
| 🪟 **JS 弹窗不卡流程** | alert / confirm / prompt 自动应答：确定、取消或输入答案。 |
| 📎 **上传不弹系统框** | 点上传按钮、交给它本地文件路径即可 —— 系统"打开文件"窗口根本不会出现。 |
| 🔓 **严格站点也能跑** | 页面禁用自身脚本的站点照常执行 —— x.com 等实测可用。 |
| 🔒 **天生隐私** | 一切都在你的机器上。无云、无账号、无遥测，数据不出设备。 |
| 🧩 **一份扩展、两个浏览器** | 同一份 `extension/` 目录 Chrome、Edge 通用；Firefox 另有独立版（见 [ff/README.md](ff/README.md)）。 |

## 典型用法

- **发布自动化** —— 用你的真实账号发 X / LinkedIn / Facebook / 博客，跟你手动操作一模一样。
- **采集与监控** —— 读你本来就能访问的页面、翻页点击、看网络流量与控制台日志。
- **端到端测试** —— 在真实浏览器会话上跑完整流程（开不开 DevTools 都行）。
- **RPA 粘合剂** —— 任何"希望有个脚本能帮我点一下"、纯 HTTP 又搞不定的网站任务。

它一次只驱动**一个标签页**，绝不抢你的鼠标和焦点 —— 它干活的同时，你照常用其他标签页、其他浏览器或任何别的软件。

---

## 快速安装

你需要：**Python 3.11+** 和 Chrome 或 Edge。全程本地运行 —— 无账号、无云、无 API key。

### Chrome & Edge —— macOS / Windows

**1. 启动 daemon**（在仓库根目录，一条命令）：

```bash
# macOS / Linux（或 Windows 的 Git Bash）
python3 daemon/webflow_bridge.py
```

```powershell
# Windows（原生 —— 用真实 Python 3.11+，不是 Microsoft Store 假桩）
py -3.11 daemon/webflow_bridge.py
```

装有 [uv](https://astral.sh/uv/) 的系统可统一用：`uv run --python 3.11 daemon/webflow_bridge.py`

首次启动会在 `~/.webflow_bridge/token` 生成随机共享密钥并开启鉴权。扩展会自动引导拿到 token；你自己的脚本每次 POST 需带 `Authorization: Bearer <token>`（或导出 `WBF_TOKEN`）。`--allow-no-auth` 仅作本地迁移窗口。

看到带两个监听端口的启动横幅即成功：

```
========================================
  Webflow Bridge daemon started
    HTTP  : http://127.0.0.1:10086    POST /command
    WS    : ws://127.0.0.1:10087          Chrome extension connects here
========================================
```

**2. 加载扩展** —— 一次性、约 30 秒，刻意保持手动（永不自动安装）：

1. Chrome 打开 `chrome://extensions`，Edge 打开 `edge://extensions`。
2. 打开右上角**开发者模式**（两个浏览器开关一致）。
3. **加载已解压的扩展程序** → 选择 `extension/` 文件夹（Chrome/Edge 同一份）。
4. 固定「Webflow Bridge」，并让**活动标签页**停在普通网站上 —— `chrome://` 页、商店页和新标签页无法被调试。
5. 改动 `manifest.json` 或 `background.js` 后需重载扩展 —— unpacked 扩展不会热应用修改。

**3. 一条命令验证** —— 应返回你活动标签页的标题：

```bash
# macOS / Linux
export WBF_TOKEN="$(cat ~/.webflow_bridge/token)"
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"evaluate","args":{"code":"(() => document.title)()"},"session":"default"}'
```

```powershell
# Windows（PowerShell）
$env:WBF_TOKEN = (Get-Content "$HOME\.webflow_bridge\token" -Raw).Trim()
curl.exe -s -X POST http://127.0.0.1:10086/command -H "Content-Type: application/json" -H "Authorization: Bearer $env:WBF_TOKEN" -d '{"action":"evaluate","args":{"code":"(() => document.title)()"},"session":"default"}'
```

预期结果：`{"status": "ok", "data": {"value": "<你的标签页标题>"}}`

**4.（可选）冒烟测试** —— 逐项打印 PASS/FAIL，失败时非零退出：

```bash
python3 daemon/smoke.py          # Windows: py -3.11 daemon/smoke.py
```

### Firefox（独立版）

Firefox 走自己的 daemon、端口 `:10096`，基于 WebDriver BiDi —— 核心驱动**无需安装任何扩展**，驱动的是你日常在用的真实 Firefox profile。动作契约与 `POST /command` 形状一致，脚本只需把地址从 `:10086` 换成 `:10096`：

```bash
# Windows
ff\ff-launch.bat
py -3.11 ff/daemon/ff_bridge.py

# macOS
chmod +x ff/ff-launch.sh && ff/ff-launch.sh
python3 ff/daemon/ff_bridge.py
```

完整指南（启动器、鉴权、动作矩阵、已知边界）：**[ff/README.md](ff/README.md)**。

## 用自己的代码驱动 —— 零 SDK

上面那条 curl 就是全部协议。下面是同一调用用纯 Python 标准库写的样子 —— 也就是你现有发布脚本已经在用的形态：

```python
import json, os, urllib.request

token = open(os.path.expanduser("~/.webflow_bridge/token")).read().strip()

def command(action, **args):
    req = urllib.request.Request(
        "http://127.0.0.1:10086/command",
        data=json.dumps({"action": action, "args": args,
                         "session": "default"}).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + token})
    return json.load(urllib.request.urlopen(req))

print(command("evaluate", code="(() => document.title)()")["data"]["value"])
```

daemon 开着、活动标签页停在普通网站上时运行它，会打印该标签页标题。凡是能说 `POST /command` 的都一样能用：curl、Python、Node，或带浏览器桥工具的 AI agent。完整的零 SDK 演练（5 步、真实页面）见 [docs/HTTP_API.md](docs/HTTP_API.md)。

## 常见问题速查

- **`503 {"error":"extension not connected"}`** —— Chrome/Edge 没开，或扩展没加载。启动浏览器后，看「Webflow Bridge」popup 是否显示 *Daemon: connected*。
- **报 "chrome:// … cannot be debugged"** —— 活动标签页必须是普通 http(s) 页面；`chrome://`、商店页、新标签页都不行。
- **报 "Another debugger is already attached"** —— 该标签开着 DevTools（或另一个 CDP 客户端）。关掉再试。
- **端口被占用** —— 已有另一个 Webflow Bridge 实例在跑，先停掉它。
- **报错提到 "Content Security Policy"** —— 你还在 content-script 时代的旧构建上。到 `chrome://extensions` 完整重载扩展；当前构建走调试通道，页面 CSP 拦不住。

完整故障排查表在本文件末尾。

## 文档导航

| 文档 | 内容 |
|---|---|
| [docs/HTTP_API.md](docs/HTTP_API.md) | `POST /command` 协议契约 —— 每个核心动作一条 curl、错误结构、零 SDK 完整 demo 流程。 |
| [docs/PRIVACY.md](docs/PRIVACY.md) | 通俗英文隐私政策（扩展做什么、数据、权限）。 |
| [docs/STORE_LISTING.md](docs/STORE_LISTING.md) | Chrome Web Store 上架素材包 —— 名称、摘要、描述、敏感权限说明。 |
| [CHANGELOG.md](CHANGELOG.md) | 版本历史。 |
| [docs/VERSIONING.md](docs/VERSIONING.md) | 版本策略与 bump 检查清单。 |
| [ff/README.md](ff/README.md) | Firefox 独立版 —— 安装、动作矩阵、平台状态、已知边界。 |

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

## 完整故障排查

| 症状 | 修复 |
|---|---|
| `503 {"error":"extension not connected"}` | Chrome/Edge 开着吗？扩展加载了吗（`chrome://extensions` / `edge://extensions`）？查后台 worker 控制台有没有 "connected to daemon"。 |
| evaluate 报 "no active tab found" 或 "chrome:// … cannot be debugged" | 活动标签是 `chrome://…`、新标签页或商店页 —— 都不能调试。在活动标签打开真实网站重试。 |
| evaluate 报 "Another debugger is already attached" | 该标签附着着 DevTools（或另一个 CDP 客户端）。关掉再试。 |
| evaluate 报错提到 "Content Security Policy" | content-script 时代的陈旧构建。到 `chrome://extensions`（或 `edge://extensions`）完整重载「Webflow Bridge」—— 当前构建走调试通道，页面 CSP 和扩展 CSP 都拦不住。 |
| 120 s 超时 | 活动标签忙（模态框/脚本阻塞），或 async 片段一直没跑完 —— CDP 会 await Promise 完成值。 |
| 端口被占用 | 另一个实例在跑 —— 先停掉。 |
| daemon 重启后扩展掉线 | 自动恢复：指数退避重连（上限 30 s）；下次 evaluate 自动 re-attach —— 无需操作。 |
| JS 弹窗出现了但 `handle_dialog` 报 no dialog | 旧版扩展（attach 时没开 Page 域）。到 `chrome://extensions` 重载扩展。 |
| 点上传按钮弹系统"打开文件"框 | 旧构建没有文件选择拦截。重载扩展后，click 触发再调 `handle_file_chooser`。 |

## 许可证与支持

Webflow Bridge **免费开源（MIT）** —— 见 [LICENSE](LICENSE)。如果它帮你省了时间：

- ⭐ 点 Star —— [github.com/darrenhooooo/webflow-bridge](https://github.com/darrenhooooo/webflow-bridge)
- 🐛 报 Bug / 提需求 —— [Issues](https://github.com/darrenhooooo/webflow-bridge/issues)
- 📦 Releases —— [v1.1.0](https://github.com/darrenhooooo/webflow-bridge/releases)
- ✉️ 联系 —— darren.hou@outlook.com
