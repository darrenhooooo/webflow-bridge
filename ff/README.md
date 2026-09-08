# Webflow Bridge for Firefox (independent edition)

Firefox 变体（独立版）：同一套 `POST /command` 协议与动作契约，脚本只需把端口从
`:10086` 换成 `:10096` 即可迁移。驱动的是**你日常在用的真实 Firefox profile**
（真实登录态/cookie 全保留，不新建不复制 profile）。

- Chrome/Edge 版（`daemon/`、`extension/`、端口 10086/10087）**零改动、不受影响**；
  两版可同机并存（不同端口、不同 daemon）。
- Firefox 版 = `ff/daemon/ff_bridge.py`（HTTP :10096）+ 原生 WebDriver BiDi 直连
  `ws://127.0.0.1:9222/session`。核心驱动**无需安装任何扩展**；可选 companion
  附加组件（`ff/extension/`，工具栏控制面板：状态/执行 JS/tabs/token，AMO 就绪）
  只做控制面，不是能力载体。
- 版本要求：Firefox **129+**（实测 155.0.1），推荐 **140+**。
- 指纹如实说明：BiDi 自动化会话中 `navigator.webdriver === true`，Firefox 无法关闭。
  产品定位是驱动**你自己已登录的站点**，不承诺反爬对抗。
- 单会话限制：一个 BiDi 端口同一时刻只有一个 session（与 daemon 单槽对齐）。

## 平台状态

| OS | 启动器 | 状态 |
|---|---|---|
| Windows 11 | `ff/ff-launch.bat` | **实测全绿**：P0+P1+P2 smoke（09-08，Firefox 155） |
| macOS | `ff/ff-launch.sh` | 脚本就绪（09-08），**待 mac 实测**（见脚本内待验证清单） |

## 安装三步

### 1. 用启动器打开真实 profile 的 Firefox（BiDi 端口 9222）

Windows:

```
ff\ff-launch.bat
```

macOS:

```bash
chmod +x ff/ff-launch.sh && ff/ff-launch.sh
```

启动器读取 profiles.ini（Windows `%APPDATA%\Mozilla\Firefox\profiles.ini`；
macOS `~/Library/Application Support/Firefox/profiles.ini`），按规则选择 profile：
规则 1 `[Install*]` 段 `Default=` 指向 → 规则 2 `Name=default-release` → 规则 3
旧式 `Default=1` 兜底（目录不存在逐级降级），并**打印所选 profile 名/路径/来源规则**。
用 `-profile <绝对路径> --remote-debugging-port 9222 -remote-allow-system-access`
启动（不新建/复制 profile）。幂等：9222 已在监听 → 提示"已在调试模式"直接退出；
Firefox 进程在但 9222 未监听 → 提示先关闭 Firefox（单实例限制）。

### 2. 启动 ff daemon

```bash
# Windows 请用真实 Python 3.11+（不是 Microsoft Store 假桩），例如：
C:/Users/darre/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe ff/daemon/ff_bridge.py
# 或 uv run --python 3.11 ff/daemon/ff_bridge.py
```

默认启用 token 鉴权：首次启动在 `~/.webflow_bridge_ff/token` 生成随机 token
（0600）。每个 POST 需带 `Authorization: Bearer <token>`（或环境变量
`WBF_FF_TOKEN`）；`GET http://127.0.0.1:10096/config` 返回 `{"token":...}`。
`--allow-no-auth` 关闭校验（仅迁移用）。可选 `--ff-port`（默认 9222）、
`--http-port`（默认 10096）、`--audit <path>`、`--humanize`（全局随机节奏）。

### 3. 冒烟验证

```bash
python ff/daemon/ff_smoke.py    # P0: 4 步（evaluate/navigate/title/tabs_list）
python ff/daemon/ff_p1_smoke.py # P1: 13 步（输入面 + screenshot/pdf/upload，本地测试页）
python ff/daemon/ff_p2_smoke.py # P2: 13 步（snapshot/network/console/dialog/humanize，本地测试页）
```

均需 Firefox 已由 ff-launch 打开。全部本地 http.server，无外网依赖（P0 的
example.com 除外）。exit 0 = 全绿。

## 动作矩阵（对齐 Chrome 协议契约）

| 动作 | Firefox 实现 | 状态 |
|---|---|---|
| `probe` | `{connected, sessionId, contexts, firefox}` | ✅ P0 |
| `evaluate` | `script.evaluate`（默认 active top-level context；`args.context` 字符串或 `tabId`） | ✅ P0 |
| `navigate` | `browsingContext.navigate` wait:complete | ✅ P0 |
| `tabs_list` / `tabs_open` / `tabs_close` / `tabs_activate` | `browsingContext.getTree` / `create` / `close` / `activate` | ✅ P0 |
| `find_tab` | URL exact→prefix→substring，`{success, url, tabId}` | ✅ P0 |
| `click` | CSS selector 或 snapshot `@eN` → 真实 pointer 点击 | ✅ P1+P2 |
| `fill` | input/textarea/select native setter + 事件；contenteditable 真实键入 | ✅ P1 |
| `type_text` | 真实 key 逐字（中文/\n/emoji） | ✅ P1 |
| `send_key` | 协议键码 + 修饰键组合 | ✅ P1 |
| `mouse_click` | selector 元素中心或 x/y 视口坐标 | ✅ P1 |
| `screenshot` | PNG/JPEG、element clip、fullPage；真实像素尺寸 | ✅ P1 |
| `save_as_pdf` | `browsingContext.print` → PDF base64 | ✅ P1 |
| `upload` | BiDi `input.setFiles`（真实文件，change 事件触发） | ✅ P1 |
| `snapshot` | 页面注入 a11y 生成器，`@eN` ref→path 缓存供 click/fill | ✅ P2 |
| `list_network_requests` / `get_network_request` | BiDi network 事件订阅 → 环形缓冲（cap 300） | ✅ P2 |
| `list_console_messages` | `log.entryAdded` 订阅 | ✅ P2 |
| `handle_dialog` | userPromptOpened 单槽状态机，accept/dismiss/promptText | ✅ P2 |
| `humanize` | per-request pacing（--humanize / body 顶层 / args.humanize） | ✅ P2 |
| `handle_file_chooser` | **不支持**：Firefox BiDi 无原生文件选择拦截 → 明确报错，用 `upload` | ⛔ P2 实测 |
| `cdp` | **不支持**：Firefox 无 CDP → 明确报错 | ⛔ P0 |

未连接 Firefox 时（除 `probe` 外）返回 `503 {"error":"firefox not connected"}`。
响应契约与 Chrome 版一致：`200 {status:ok, data:{value}}` /
`200 {status:error, error}`；跨域 POST → 403；鉴权失败 → 401。

## 与 Chrome 版差异

- 端口 10096（Chrome 10086）；`tabId` 语义 = BiDi context id（字符串）。
- `tabs_list` 无 windowId/index；`active` 用 `document.visibilityState` 近似判定。
- `cdp` / `handle_file_chooser` 明确不支持（Chrome 有 debugger/fileChooser 拦截）。
- 截图是真实像素（dpr 感知，Chrome 版口径可能不同——如需一致需对齐）。
- click 触发 JS dialog 时真实点击会挂起直到 `handle_dialog` 被并发处理
  （客户端需并发发 handle_dialog，见 ff_p2_smoke 示例模式）。

## 已知边界（实测 Firefox 155）

- **单会话/实例**：每个 Firefox 进程实例只允许一次 `session.new`，之后即使连接
  断开也报 `Maximum number of active sessions`。ff daemon 单会话常驻与之一致；
  **若 ff daemon 重启而 Firefox 未重启**，用 ff-launch 重启 Firefox 后再连。
- `browsingContext.create` 忽略 url 参数——`tabs_open` 先建 tab 再
  `navigate wait:complete`，打开即完成加载，紧随的 `find_tab` 立即可命中。
- `navigator.webdriver=true` 无法关闭；about: 等特权页 evaluate 需
  `-remote-allow-system-access`（ff-launch 已带）；冷启动首标签若是
  about:home/newtab，首个 evaluate 也依赖该 flag。
- network/console 缓冲在会话内跨页面累积（与 Chrome 语义一致）。

## 清理

- 停 daemon：Ctrl+C（Windows）/ Ctrl+C（macOS）。
- 关 Firefox（BiDi 模式）：Windows `taskkill /IM firefox.exe /F`；
  macOS `pkill -x firefox`。
- 删除即干净：整目录移除 `ff/`，Chrome 版零影响。
