# Webflow Bridge for Firefox — P0 (independent edition)

Firefox 变体（独立版）：同一套 `POST /command` 协议与动作契约，脚本只需把端口从
`:10086` 换成 `:10096` 即可迁移。驱动的是**你日常在用的真实 Firefox profile**。

- Chrome/Edge 版（`daemon/`, `extension/`, 端口 10086/10087）**零改动、不受影响**；
  两版可同机并存。
- Firefox 版 = `ff/daemon/ff_bridge.py`（HTTP :10096）+ 原生 WebDriver BiDi 直连
  `ws://127.0.0.1:9222/session`。**无需安装任何扩展**。
- 版本要求：Firefox **129+**（实测 155.0.1），推荐 **140+**。
- 指纹如实说明：BiDi 自动化会话中 `navigator.webdriver === true`，Firefox 无法关闭。
  产品定位是驱动**你自己已登录的站点**，不承诺反爬对抗。
- 单会话限制：一个 BiDi 端口同一时刻只有一个 session（与 daemon 单槽对齐）。
- `cdp` 动作在 Firefox 后端**不支持**（Firefox 无 CDP），返回明确错误。

## 安装三步

### 1. 用启动器打开真实 profile 的 Firefox（BiDi 端口 9222）

```
ff\ff-launch.bat
```

启动器读取 `%APPDATA%\Mozilla\Firefox\profiles.ini`：优先选 `Default=1` 的
profile，否则取第一个非 dev-edition 的 profile，并**打印所选 profile 名**。
用 `-profile <绝对路径> --remote-debugging-port 9222 -remote-allow-system-access`
启动（不新建/复制 profile）。幂等：9222 已在监听 → 提示"已在调试模式"直接退出；
Firefox 进程在但 9222 未监听 → 提示先关闭 Firefox（单实例限制）。

### 2. 启动 ff daemon

```bash
# Windows 上请用真实 Python 3.11+（不是 Microsoft Store 假桩），例如：
C:/Users/darre/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe ff/daemon/ff_bridge.py
# 或 uv run --python 3.11 ff/daemon/ff_bridge.py
```

默认启用 token 鉴权：首次启动在 `~/.webflow_bridge_ff/token` 生成随机 token
（0600）。每个 POST 需带 `Authorization: Bearer <token>`（或设 `WBF_FF_TOKEN`）；
`GET http://127.0.0.1:10096/config` 返回 `{"token":...}`。`--allow-no-auth` 关闭
校验（仅迁移用）。可选 `--ff-port`（默认 9222）、`--http-port`（默认 10096）、
`--audit <path>`。

### 3. 用 curl 验证

```bash
curl -s -X POST http://127.0.0.1:10096/command ^
  -H "Content-Type: application/json" ^
  -H "Authorization: Bearer %WBF_FF_TOKEN%" ^
  -d "{\"action\":\"evaluate\",\"args\":{\"code\":\"document.title\"}}"
# -> {"status":"ok","data":{"value":"..."}}
```

冒烟测试（需 Firefox 已由 ff-launch 打开）：

```bash
python ff/daemon/ff_smoke.py
# evaluate 1+1 -> 2 / navigate example.com / document.title -> "Example Domain" / tabs_list
```

## P0 动作（对齐 Chrome 协议契约）

| Action | 说明 |
|---|---|
| `evaluate` | `script.evaluate`（默认第一个顶层 context；可用 `args.context`(字符串) 或 `args.tabId`(数字=位置索引或 context 字符串)） |
| `navigate` | `browsingContext.navigate` wait:complete → `data: {}` |
| `tabs_list` | `browsingContext.getTree` → `[{id(=context), url, title?, active?}, ...]`（无 windowId/index；title/active 尽力而为） |
| `tabs_open` / `tabs_close` / `tabs_activate` | `browsingContext.create` / `close` / `activate` |
| `find_tab` | URL exact→prefix→substring；返回 `{success, url, tabId(=context)}` |
| `probe` | `{connected, sessionId, contexts, firefox(version)}` |
| `cdp` | **不支持** → `{"status":"error","error":"cdp not supported on firefox backend"}` |

未连接 Firefox 时（除 `probe` 外）返回 `503 {"error":"firefox not connected"}`。

## 已知边界（P0）

- **单会话/实例（实测 Firefox 155）**：每个 Firefox 进程实例只允许一次
  `session.new`，之后即使连接断开也会报 `Maximum number of active sessions`。
  ff daemon 单会话常驻与之一致；**若 ff daemon 重启而 Firefox 未重启**，请用
  ff-launch 重启 Firefox 后再连（连接断开自动重连只对 Firefox 重启后生效）。
- `browsingContext.create` 会忽略 url 参数（只回显）——`tabs_open` 实现为先建
  tab 再 `navigate wait:complete`，因此打开即完成加载，紧随其后的 `find_tab`
  立即可命中（加载较慢的页面会占用较多时间）。
- `evaluate` 抛错（exception）按协议契约返回 `{"status":"error",...}`；
  返回值按 BiDi RemoteValue 解包为纯 JSON（Firefox 的对象序列化为
  `[[key, RemoteValue], ...]` 对，daemon 已解回对象；无法 JSON 化的类型保留标记）。
- `tabs_list` 的 `active` 用 `document.visibilityState` 近似判定（Firefox BiDi
  无 active 查询）；`title`/`active` 字段尽力而为。无 windowId/index。
- `navigator.webdriver=true` 无法关闭；`evaluate` 在约 about: 等特权页需
  ff-launch 已带的 `-remote-allow-system-access`。
- 冷启动首标签若是 about:home/newtab，首个 evaluate 也依赖上述 flag。
- P1/P2（click/fill/screenshot/snapshot 等）见 `docs/FIREFOX_SUPPORT_PLAN.md`。

## 清理

- 停 daemon：Ctrl+C。
- 关 Firefox（BiDi 模式）：`taskkill /IM firefox.exe /F`。
- 删除即干净：整目录移除 `ff/`，Chrome 版零影响。
