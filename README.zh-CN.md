# Webflow Bridge

**[English](README.md) | [中文](README.zh-CN.md)**

> 免费、本地的浏览器自动化桥 —— 驱动你**真实、已登录**的 Chrome 或 Edge。
> 无云、无账号。

**许可证:** MIT。

**支持:** macOS 与 Windows 上的 Chrome 与 Microsoft Edge（Chromium MV3 ——
两浏览器 chrome.debugger API 完全一致）。**Firefox:** 独立 Firefox 版（WebDriver BiDi 架构）——
见 [ff/README.md](ff/README.md)。不支持: Safari。

---

## 它能做什么

Webflow Bridge 让脚本驱动**你已经打开的那个浏览器标签页** —— 就是你已经
登录的那个。不需要另开自动化浏览器、不用复制 cookie、不上云。你现有的发布
脚本继续向 `http://127.0.0.1:10086/command` POST **无需改动**；Webflow Bridge
在你真实的 Chrome 标签页里执行 JS。

## 功能特点

| | |
|---|---|
| 🖥️ **真实浏览器、真实会话** | 运行在你活着的标签页上 —— 登录态、cookie、页面全局变量都在。没有需要同步的隐形浏览器。 |
| 🔌 **Agent 工具兼容** | 同样的 `POST /command` 协议。为浏览器桥写的 agent skill 可以 1:1 映射。 |
| 🎯 **30+ 动作** | 点击、输入、填表、拖放文件、截图、存 PDF、读页面、切标签、看网络流量和控制台日志，等等。 |
| 🪟 **JS 弹窗自动处理** | alert/confirm/prompt 不再卡住你的自动化 —— 程序化地确定、取消或输入答案。 |
| 📎 **文件上传不弹系统框** | 点上传按钮、交给它一个本地文件路径 —— 系统"打开文件"窗口根本不会出现。 |
| 🔓 **免疫页面 CSP** | 走 debugger 通道执行，即使在 x.com 这类严格站点也能工作。 |
| 🔒 **设计上保护隐私** | 一切都在你的机器上。无云、无账号、数据不出设备。 |
| 🧩 **一个扩展、两个浏览器** | 同一份 `extension/` 目录在 Chrome 和 Edge 都能加载。 |

## 典型用法

- **发布自动化** —— 用你的真实账号发 X / LinkedIn / Facebook / 博客，跟你手动发一模一样。
- **采集与监控** —— 读需要登录的页面、翻页点击、看 XHR 流量。
- **测试** —— 在真实浏览器会话上跑端到端流程（开不开 DevTools 都行）。
- **RPA 粘合剂** —— 任何"希望有个脚本能帮我点一下"的、纯 HTTP 搞不定的网站任务。

它一次驱动一个标签页，绝不抢你的鼠标和焦点 —— 它干活的同时你可以正常用
其他标签页、其他浏览器或任何别的软件。

---

## 架构一览

三个本地组件：你的脚本（或 AI agent）向一个小型 Python daemon POST 命令，
daemon 通过本地 WebSocket 转发给扩展，扩展再经 Chrome 的 debugger 通道在你
真实的标签页里执行。

```
┌──────────────────────────┐   POST /command   ┌──────────────────────────────┐
│  现有发布脚本(不改动)      │ ----------------> │ Python daemon  :10086 HTTP   │
│  POST 请求                │ <---------------- │ daemon/webflow_bridge.py       │
└──────────────────────────┘   JSON 响应        └──────────────┬───────────────┘
                                                              │  WebSocket ws://127.0.0.1:10087
                                                              ▼
                                             ┌────────────────────────────────┐
                                             │ Webflow Bridge (MV3 Chrome     │
                                             │ 扩展 — background.js           │
                                             │ 仅 service worker)             │
                                             └───────────────┬────────────────┘
                                                             │  chrome.debugger attach
                                                             │  CDP Runtime.evaluate
                                                             ▼
                                             ┌────────────────────────────────┐
                                             │ ACTIVE tab(你的真实 Chrome 页)  │
                                             │ 页面 MAIN world — 免疫页面 CSP  │
                                             │ (等价 DevTools 控制台);         │
                                             │ returnByValue JSON-safe 结果返回 │
                                             └────────────────────────────────┘
```

- **Daemon**: 仅用 Python 标准库(手写的最小 RFC 6455 WebSocket 服务器;零第三方
  依赖)。向后兼容 — evaluate/navigate/probe 行为与之前完全一致;下面列出的
  浏览器驱动动作是新增能力。
- **Extension**: Chrome Manifest V3 — `manifest.json`、`background.js` 和一个小
  工具栏 popup(`popup.html`/`popup.css`/`popup.js`),用于 ping 后台 worker 并
  测试评估当前标签页。worker 连接 daemon、把 `chrome.debugger` 会话 attach 到
  **活动标签页**、通过 CDP `Runtime.evaluate`(DevTools 控制台通道)执行代码片段。
  由于该会话是完整 DevTools 连接,扩展还通过通用 `cdp` 透传动作暴露**整个 CDP
  能力面**(`Input.*`、`Page.*`、`DOM.*`、`Network.*` …) — 脚本可以驱动浏览器的
  一切能力,而不只是求值。在此之上,worker 实现了**标准的浏览器桥 agent
  工具面** — find_tab/snapshot/click/fill/screenshot/upload/save_as_pdf/
  mouse_click/send_key/type_text,以及能开新标签并命名的 navigate(动作表见下)。
  **`content.js` 已移除** — 原因见「代码在页面里如何运行」。
- **smoke 测试**: 端到端冒烟测试见 `tools/p0_smoke.py`(16 项全过,需真实浏览器)。

## 文件结构

```
webflow/
├── LICENSE              # MIT
├── README.md            # 英文说明
├── README.zh-CN.md      # 中文说明
├── daemon/
│   ├── webflow_bridge.py  # HTTP :10086 (POST /command) + WS :10087
│   └── smoke.py         # 旧版端到端冒烟(真实页面)
├── docs/
│   ├── PRIVACY.md       # 英文隐私政策(商店上架用)
│   ├── HTTP_API.md      # HTTP 协议细节
│   ├── MCP.md           # MCP 服务说明
│   ├── CROSS_PLATFORM.md# 跨平台说明
│   └── STORE_LISTING.md # 商店上架文案草稿
├── extension/
│   ├── manifest.json    # MV3; permissions: scripting, activeTab, tabs, debugger, alarms, tabGroups
│   │                    # 无 content_scripts 块, 无 content_security_policy 键
│   ├── background.js    # service worker: WS 客户端 + chrome.debugger 驱动
│   │                    # (会话管理; 分发 evaluate/cdp/navigate/tabs_*/probe
│   │                    #  + find_tab/snapshot/click/fill/screenshot/upload/
│   │                    #    save_as_pdf/mouse_click/send_key/type_text/
│   │                    #    submit/fill_form/wait_for/handle_dialog/
│   │                    #    handle_file_chooser/drop/resize_page/
│   │                    #    list_network_requests/get_network_request/
│   │                    #    list_console_messages)
│   ├── popup.html       # 工具栏 popup UI
│   ├── popup.css        # popup 样式(深色主题, 无外部资源)
│   ├── popup.js         # popup <-> background 运行时消息
│   └── assets/icons/    # icon16/32/48/128.png (工具栏 / 商店)
├── mcp/
│   └── mcp_server.py    # MCP 服务入口
├── openapi/
│   └── openapi.yaml     # HTTP API OpenAPI 描述
└── tools/
    ├── p0_smoke.py      # P0 验收: 16 项全绿(需 Chrome + daemon + devtest 页)
    ├── make_icons.py    # 重新生成扩展图标 (仅需 Pillow)
    └── devtest/         # P0 测试页(本地静态服务器用)
```

## 安装 / 运行

### 1. 启动 daemon

```bash
cd /path/to/webflow        # 项目根目录(本仓库: daemon/, extension/ …)
# 方式 A — uv(推荐; 各 OS 一致):
uv run --python 3.11 daemon/webflow_bridge.py
# 方式 B — 普通 Python 3.11+(无 uv):
python3 daemon/webflow_bridge.py
```

> `python3` 在 macOS/Linux 是真解释器。Windows 上必须是真 Python 3.11
> (例如 python.org 安装的)— 不是 Microsoft Store 的假桩
> (那里用 `py -3.11 daemon/webflow_bridge.py` 也可以)。

daemon 默认开启共享密钥鉴权: 首次启动创建 `~/.webflow_bridge/token`(随机,
0600)。原生客户端每个 POST 都要带 `Authorization: Bearer <token>`(或导出
`WBF_TOKEN`);扩展通过 `GET /config` 自动引导。仅本地迁移窗口期可用
`--allow-no-auth` 关闭校验。

看到带两个监听端口的启动横幅即成功:

```
========================================
  Webflow Bridge daemon started
    HTTP  : http://127.0.0.1:10086    POST /command
    WS    : ws://127.0.0.1:10087          Chrome extension connects here
```

### 2. 加载扩展 — Chrome 或 Edge(手动, 一次性)

同一份 `extension/` 目录在两种浏览器里都能加载(同一份 `dist/` zip 同时打包
两者 — 没有 Chrome 专用 vs Edge 专用的构建)。

1. Chrome 打开 `chrome://extensions`, Edge 打开 `edge://extensions`。
2. 打开右上角**开发者模式**(两浏览器一致;Edge 显示同样的开关)。
3. **加载已解压的扩展程序** → 选择 `extension/` 文件夹(Chrome/Edge 同一份)。
4. 固定「Webflow Bridge」;让**活动标签页**停在普通网站上
   (`chrome.debugger` 无法 attach 到 `chrome://` / `edge://` 页面、商店页或
   新标签页 — 发布流程需要真实 http(s) 页面)。

> **改动后必须重载扩展**: unpacked 扩展不会热应用修改 — 改完
> `manifest.json` 或 `background.js` 后在 `chrome://extensions`(或
> `edge://extensions`)的「Webflow Bridge」卡片上点刷新(reload)图标。
> manifest 里没有 `content_security_policy` 键(MV3 禁止扩展页面允许 eval —
> Chrome 若出现会拒绝 manifest — 这里也不需要),所以没有 CSP 顾虑。移除
> content script 是无感的。

扩展会自动重连(退避最长 30 s),可以随意重启 daemon。

### 3. 用 curl 验证

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"evaluate","args":{"code":"(() => document.title)()"},"session":"default"}'
```

预期(你活动标签页的标题):

```json
{"status": "ok", "data": {"value": "..."}}
```

### 4. 冒烟测试(推荐)

```bash
# 起本地测试页(可选, P0 验收页)
cd tools/devtest && python3 -m http.server 8921 --bind 127.0.0.1

# 跑 P0 验收(需 Chrome 开着扩展 + daemon 运行 + 页面在普通 http 页)
python3 tools/p0_smoke.py
# 期望输出: summary: 16/16 passed
```

## 协议契约

`POST /command`, JSON body:

```json
{
  "action": "evaluate",
  "args":   {"code": "(() => document.title)()"},
  "session": "default"
}
```

| 响应 | 含义 |
|---|---|
| `200 {"status":"ok","data":{"value": <结果>}}` | 代码执行成功; 结果 JSON-safe(string/number/bool/array/object/null) |
| `200 {"status":"error","error":"..."}` | 执行失败(代码抛错、120 s 超时、未知动作 …) |
| `503 {"error":"extension not connected"}` | 没有扩展 WebSocket — 请启动带扩展的 Chrome |

除 `evaluate` 外,daemon 通过同一条管道转发完整的浏览器驱动动作面。动作名与
参数沿用浏览器桥 agent 工具的通用惯例(常见的 `list_tabs` 对应本桥既有的
`tabs_list`),所以按 `POST /command` 浏览器桥动作面写的 agent skill 可以 1:1
映射。所有作用于既有标签页的动作都接受可选 `"tabId"`,缺省为活动标签页(用
`tabs_list` 查标签 id);`save_as_pdf` 不接受 `tabId`(永远打印活动标签页),
`find_tab` 也不接受(它搜索所有窗口且从不新开标签):

| 动作 | `args` | 回复中的 `data` |
|---|---|---|
| `evaluate` | `{"code": "...", "tabId"?: <n>}` | `{"value": <求值结果>}` |
| `cdp` | `{"method": "...", "params"?: {...}, "tabId"?: <n>}` | `{"value": <原始 CDP 结果>}` |
| `snapshot` | `{"max"?: <int, 默认 400>, "tabId"?: <n>}` | `{"value": {url, title, nodes: [{ref: "@e0", tag, role, name, text, path}, ...]}}` |
| `click` | `{"selector": <CSS 或 "@eN">, "tabId"?: <n>}` | `{"value": {success, tag, text}}` |
| `fill` | `{"selector", "value", "mode"?: "auto"/"value"/"contenteditable", "tabId"?: <n>}` | `{"value": {success, tag, mode}}` |
| `fill_form` | `{"fields": [{selector, value}, ...], "tabId"?: <n>}` | `{"value": {success, filled: [...], errors: [...]}}` |
| `submit` | `{"selector"?: <CSS 或 "@eN">, "tabId"?: <n>}` | `{"value": {success, mode}}` (requestSubmit) |
| `wait_for` | `{"selector"?/text"?: ..., "timeoutMs"?: <int, 默认 6000>, "tabId"?: <n>}` | `{"value": {found, elapsedMs}}` |
| `handle_dialog` | `{"accept"?: <bool, 默认 true>, "promptText"?: <string>, "timeoutMs"?: <int>, "tabId"?: <n>}` | `{"value": {success, dialog: {type, message, defaultPrompt}, accept}}` |
| `handle_file_chooser` | `{"file": <本地绝对路径>, "timeoutMs"?: <int, 默认 3000>, "tabId"?: <n>}` | `{"value": {success, file, mode}}` |
| `drop` | `{"selector": <CSS 或 "@eN" 拖放区>, "files": [{name, mime, data(base64)}], "tabId"?: <n>}` | `{"value": {success}}` |
| `resize_page` | `{"width": <int>, "height": <int>, "tabId"?: <n>}` | `{"value": {success, width, height}}` |
| `list_network_requests` | `{"limit"?: <int>, "tabId"?: <n>}` | `{"value": {requests: [...]}}` |
| `get_network_request` | `{"requestId": <string>, "tabId"?: <n>}` | `{"value": {found, request}}` |
| `list_console_messages` | `{"limit"?: <int>, "tabId"?: <n>}` | `{"value": {messages: [...]}}` (log/exception) |
| `find_tab` | `{"url", "active"?: true}` (精确 → 前缀 → 子串) | `{"value": {success, url, tabId}}` 或 `{success: false, error}` |
| `navigate` | `{"url", "newTab"?: true, "group_title"?, "tabId"?: <n>}` | `{}` (标签已更新); `newTab` 时: `{"value": {success, tabId, groupId?}}` |
| `tabs_list` | `{}` | `{"value": [{id, url, title, active, windowId, index}, ...]}` |
| `tabs_open` | `{"url": "https://..."}` | `{"value": {"id": <tabId>, "url": <url>}}` |
| `tabs_close` | `{"tabId"?: <n>}` | `{"value": {"closed": <tabId>}}` |
| `tabs_close_all_but` | `{"tabId"?: <n>}` | `{"value": {"closed": <count>}}` |
| `tabs_activate` | `{"tabId"?: <n>}` | `{"value": {"tabId": <n>, "active": true}}` |
| `probe` | `{}` | `{"value": {tab, paths}}` (扩展健康矩阵) |
| `screenshot` | `{"format"?: "png"/"jpeg", "quality"?: 0-100, "selector"?, "fullPage"?: true, "tabId"?: <n>}` | `{"value": {base64, mime, width, height}}` — 客户端写文件 |
| `upload` | `{"selector", "file": <本地绝对路径>, "tabId"?: <n>}` | `{"value": {success, file, tag}}` |
| `save_as_pdf` | `{}` (总是活动标签页) | `{"value": {base64, mime: "application/pdf"}}` — 客户端写文件 |
| `mouse_click` | `{"x"?: <int>, "y"?: <int>, "selector"?, "tabId"?: <n>}` (selector 优先) | `{"value": {success, x, y}}` |
| `send_key` | `{"key", "modifiers"?: ["alt"/"ctrl"/"meta"/"shift"], "tabId"?: <n>}` | `{"value": {success, key}}` |
| `type_text` | `{"text", "selector"?, "tabId"?: <n>}` | `{"value": {success, len}}` |

`cdp` 是无白名单的通用透传: 扩展 debugger 会话能触达的任何命令都能发, 例如

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"cdp","args":{"method":"Input.insertText","params":{"text":"hi"}},"session":"default"}'

curl -s -X POST http://127.0.0.1:10086/command \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WBF_TOKEN" \
  -d '{"action":"tabs_list","args":{},"session":"default"}'
```

`data.value` 就是 CDP 方法返回的内容(像 `Input.insertText` 返回 `{}`;
`Runtime.evaluate` 返回 `{"result": {"type": ..., "value": ...}}`);`tabs_list`
每个标签一条记录, 未定义字段省略(`chrome://` 页面可能没有 url/title)。
`tabs_open` 要求 http(s) url;`tabs_close_all_but` 关闭目标标签所在窗口内除
目标外的所有标签。

脚本读取 `response.get("data", {}).get("value")`, 所以错误响应(无 `data`)
行为与之前完全一致。

鉴权与源站防护: 先校验 bearer token——没有合法 `Authorization` 头的 POST 返回
`401 {"error":"unauthorized..."}`。随后任何 `Origin` 头不是 `http://127.0.0.1:10086`
或 `http://localhost:10086` 的 POST 会得到
`403 {"error":"cross-origin POST blocked"}`(`null` 源站——sandbox iframe /
file 页面——有意拒绝,它们反正拿不到 token)。原生脚本/curl 不带 `Origin` 头,
鉴权通过后不受影响。扩展 WebSocket 握手必须带 `?token=<token>`,缺失或错误
得到纯 HTTP 403。

### 内部 WebSocket 线格式(daemon ↔ 扩展, :10087)

```jsonc
// daemon -> extension
{"id": "<request_id>", "action": "evaluate", "code": "(() => ... )()"}
{"id": "<request_id>", "action": "evaluate", "code": "(() => ... )()", "tabId": 7}
{"id": "<request_id>", "action": "navigate",  "url": "https://..."}
{"id": "<request_id>", "action": "navigate",  "url": "https://...", "tabId": 7}
{"id": "<request_id>", "action": "cdp", "method": "Input.insertText", "params": {"text": "hi"}, "tabId": 7}
{"id": "<request_id>", "action": "tabs_list"}
{"id": "<request_id>", "action": "tabs_open", "url": "https://example.com"}
{"id": "<request_id>", "action": "tabs_close",  "tabId": 7}
{"id": "<request_id>", "action": "tabs_close_all_but", "tabId": 7}
{"id": "<request_id>", "action": "tabs_activate", "tabId": 7}
{"id": "<request_id>", "action": "navigate", "url": "https://...", "newTab": true, "group_title": "Scratch"}
{"id": "<request_id>", "action": "find_tab", "url": "example.com", "active": true}
{"id": "<request_id>", "action": "snapshot", "max": 400}
{"id": "<request_id>", "action": "click", "selector": "@e0"}
{"id": "<request_id>", "action": "fill_form", "fields": [{"selector": "#name", "value": "Ada"}]}
{"id": "<request_id>", "action": "wait_for", "text": "late element", "timeoutMs": 6000}
{"id": "<request_id>", "action": "handle_dialog", "accept": false}
{"id": "<request_id>", "action": "handle_file_chooser", "file": "/abs/path/a.txt"}
{"id": "<request_id>", "action": "drop", "selector": "#dropzone", "files": [{"name":"a.txt","mime":"text/plain","data":"<base64>"}]}
{"id": "<request_id>", "action": "resize_page", "width": 900, "height": 700}
{"id": "<request_id>", "action": "list_network_requests"}
{"id": "<request_id>", "action": "list_console_messages"}
// ... find_tab/snapshot/click/fill/screenshot/upload/save_as_pdf/mouse_click/send_key/type_text
//     与以上新动作共用同一扁平信封形状(动作名 + 其 args)

// extension -> daemon
{"id": "<request_id>", "ok": true,  "value": <json-safe 结果>}
{"id": "<request_id>", "ok": false, "error": "..."}
{"type": "ping"}            // keepalive, daemon 忽略
```

daemon 也接受 `{"id", "data":{"value": ...}}` 形式的回复。

## 代码在页面里如何运行

一个 `evaluate` 片段通过 **`chrome.debugger` → CDP `Runtime.evaluate`** 在活动
标签页上运行 — 与 DevTools 控制台完全相同的通道。它执行在页面的 **MAIN
world**, 带 `returnByValue: true`, 所以片段的完成值(例如 IIFE 的返回值)以
JSON-safe 数据返回, 永不是原始 CDP 句柄。因为是 debugger 通道, 它**免疫页面
CSP**: 即使在 x.com 这类严格站点也能执行任意字符串; 因为运行在页面自己的
world, 片段能看到页面的 DOM *和* JS 全局变量, 它派发的事件(包括 `DataTransfer`
拖放文件上传、`DragEvent`、`File`/`Blob`、`.click()`)会触发页面真实监听器 —
React 的委托 handler 也在内。发布流程在 x.com 上发推/发帖就依赖这一点。

为什么不用 content script 或 `executeScript`? 这是基于实证而非理论:
content-script 的 isolated world 运行在 **Chrome 硬编码的 CSP** 下, 其允许的
`script-src` 源不含 `eval`/`new Function`, 所以 `content.js` 求值器在稳定 MV3
下无法工作, 无论 manifest 怎么写。`chrome.scripting.executeScript` 已完全不再
接受 `'code'` 字符串(只接受 `'files'` 或 `'func'`), 而在 MAIN world 编译
字符串(`func` 内调 `new Function`)会被 x.com 的**页面** CSP 拦截。唯一被实证
能承载任意字符串求值的通道就是 debugger(`Runtime.evaluate`) — 已在 Chrome 152
上于 x.com 实测验证。

扩展为每个活动标签页 attach **一个** debugger 会话并在多次 evaluate 间复用 —
长发布流程中不会出现 attach/detach 闪烁。会话在同标签页导航后存活, 所以
`navigate` 后仍保持; 在 daemon WebSocket 关闭、目标切到别的标签、触发
`chrome.debugger.onDetach`(标签关闭、DevTools 接管…)或命令因会话死亡而失败时
detach。下一次 evaluate 会透明地重新 attach。

该会话让**完整 CDP 能力面对脚本可用**: `cdp` 动作在同一托管会话上触发任何
协议方法(`Input.*` 做真实鼠标/键盘/触摸和 `DataTransfer` 拖放事件、`Page.*`
做刷新/截图/打印、`DOM.*`、`Network.*`、`Emulation.*`、`Runtime.*` …)— 无
方法白名单, 原样返回结果。传入与当前会话不同的 `tabId` 会在命令执行前把会话
切到那个标签(evaluate 用的同一套 detach/re-attach);`navigate` 从不切会话 —
CDP 会话只作用于它 attach 的那个标签, 并在同标签导航后存活。

细节:

- `"(() => {...})()"` 之所以可用, 是因为 `Runtime.evaluate` 返回最后一个表达
  式的值。
- Promise 结果会被 await(`awaitPromise: true`); 挂起的 async 片段表现为
  daemon 的 120 s 超时。
- 结果会 JSON 克隆(对象/数组/数字/字符串/布尔/null 存活;`undefined` 变成
  JSON-safe 的 `{type:"undefined"}` 标记)。
- 抛出的错误以 `{"status":"error","error":<message>}` 返回, 错误文本完整保留。
- `background.js` 用 15 s 心跳保活到 daemon 的 WebSocket, 指数退避重连(上限
  30 s)。daemon 侧另有 15 s RFC 6455 ping 防 MV3 service worker 30 s 空闲
  休眠断连。

## 弹窗与对话框处理

- **页面 JS 对话框**(alert/confirm/prompt/beforeunload): attach 时开启 Page
  域, 监听 `Page.javascriptDialogOpening`, 页面阻塞在对话框上, 用
  `handle_dialog` 决定 accept/dismiss/填 promptText。
- **文件上传**(自定义按钮/拖拽区触发 `<input type="file">`): attach 时开启
  `Page.setInterceptFileChooserDialog`, Chrome 不再弹系统"打开文件"框, 改为发
  `Page.fileChooserOpened` 事件; 用 `handle_file_chooser` 传本地绝对路径,
  程序化完成选文件。
- 两者都按标签页隔离, 不影响你同时使用其他标签页或其他软件。

## 故障排查

| 症状 | 修复 |
|---|---|
| `503 {"error":"extension not connected"}` | Chrome/Edge 开着吗? 扩展加载了吗(`chrome://extensions` / `edge://extensions`)? 查 `background.js` 控制台有没有 "connected to daemon"。 |
| evaluate 报 "no active tab found" 或 "cannot attach debugger ... chrome:// and Web Store pages cannot be debugged" | 活动标签是 `chrome://...` / 新标签页 / 商店页 — 这些不能调试。在活动标签打开真实网站重试。 |
| evaluate 失败报 "Another debugger is already attached" | 该标签开着 DevTools(或另一个 CDP 客户端)。关掉那个标签的 DevTools 再试。 |
| evaluate 报错提到 "Content Security Policy" | content-script 时代的陈旧构建(旧的 MAIN-world `new Function` / content-script eval 路径被 CSP 拦截)。在 `chrome://extensions`(或 `edge://extensions`)完整重载「Webflow Bridge」— 当前构建走 `chrome.debugger`, 页面 CSP 和扩展 CSP 都拦不住。 |
| 120 s 超时 | 活动标签忙(模态对话框/脚本阻塞)或页面代码没跑完。CDP 会 await Promise 完成值, 挂起的 async 片段会落到这里。 |
| 端口被占用 | 另一个 Webflow Bridge 实例在跑 — 先停掉它。 |
| 扩展在 daemon 重启后掉线 | 自动恢复: 指数退避重连(上限 30 s)。WS 关闭时 debugger 会话 detach, 下次 evaluate 时 re-attach — 无需操作。 |
| dialog 弹了但 handle_dialog 报 no dialog | 确认扩展是最新构建并已 reload(`chrome://extensions` 点刷新); 老构建在 attach 时没开 Page 域。 |
| 点上传按钮弹系统"打开文件"框 | 确认扩展已 reload(含 `setInterceptFileChooserDialog` 的版本); 然后 click 触发后调 `handle_file_chooser`。 |

## 遵守的约束

- 在 Windows 11 + Chrome 152 上开发与验证; 设计上平台中立 — 纯 Python 标准库
  daemon + Chromium MV3 扩展。macOS + Edge 支持; 见 `docs/CROSS_PLATFORM.md`。
- 扩展手动加载(开发者模式 → 加载已解压), 永不自动安装; 不触碰浏览器 profile。
- daemon 只用 Python 标准库。
- 隐私: 全部本地, 无云无账号; 见 `docs/PRIVACY.md`。
